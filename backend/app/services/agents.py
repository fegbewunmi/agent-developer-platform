import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import Stage
from app.models.identity import Team, User
from app.models.skill import AgentVersionSkill
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.services.manifest import resolve_manifest


async def create_agent(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    team_id: uuid.UUID,
    description: str | None,
    requires_ci_provenance: bool = False,
) -> Agent:
    if not permissions.can_create_agent(actor, team_id):
        raise PermissionDeniedError("not authorized to create an agent for this team")

    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if team is None:
        raise NotFoundError(f"no team with id {team_id}")

    existing = (await db.execute(select(Agent.id).where(Agent.name == name))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"an agent named {name!r} already exists")

    agent = Agent(
        id=uuid.uuid4(),
        name=name,
        team_id=team_id,
        description=description,
        requires_ci_provenance=requires_ci_provenance,
    )
    db.add(agent)
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="agent.created",
        entity_type="agent",
        entity_id=agent.id,
        payload={"name": name, "team_id": str(team_id)},
    )
    await db.commit()
    await db.refresh(agent)
    return agent


async def list_agents(db: AsyncSession) -> list[Agent]:
    result = await db.execute(select(Agent).order_by(Agent.name))
    return list(result.scalars().all())


async def get_agent(db: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"no agent with id {agent_id}")
    return agent


async def create_agent_version(
    db: AsyncSession,
    *,
    actor: User,
    agent_id: uuid.UUID,
    manifest: dict,
    via_ci: bool = False,
    provenance: dict | None = None,
) -> AgentVersion:
    """Creates one immutable AgentVersion, its skill pins, and its initial
    (draft) lifecycle row, in a single transaction - all-or-nothing, matching
    docs/agent-versioning.md's write-once guarantee and
    docs/agent-versioning.md#the-stage-vs-content-split (stage lives on
    AgentVersionLifecycle, never as a mutable field here).

    Phase 8 (ADR-0023, ADR-0024): `via_ci`/`provenance` are only ever set by
    app/api/ci_publish.py, after CIPublisherAuth has already verified the
    caller's real Google-signed OIDC token - never by the human-facing route
    (app/api/agents.py), which always calls this with the defaults. An Agent
    with `requires_ci_provenance=True` accepts versions ONLY via that path;
    manual creation is rejected outright regardless of the actor's role/team,
    since the whole point is that no human can type a version into existence
    for an integrated agent.
    """
    agent = await get_agent(db, agent_id)

    if agent.requires_ci_provenance and not via_ci:
        raise PermissionDeniedError(
            "this Agent requires CI-published versions with verified source provenance - "
            "manual creation is disabled (docs/adrs/0023-registry-not-deployment-platform.md)"
        )

    if not via_ci and (
        not permissions.can_create_agent(actor, agent.team_id)
        or not permissions.demo_containment_ok(actor, agent.team_id)
    ):
        raise PermissionDeniedError("not authorized to create a version for this agent")

    # Required only when the Agent demands it - but recorded whenever a real
    # CI caller genuinely supplies it, even for an Agent not (yet, or ever)
    # flagged requires_ci_provenance=True. Discarding real, verified
    # provenance just because the flag happens to be off would throw away
    # a true fact for no reason.
    if agent.requires_ci_provenance and (
        not provenance or not provenance.get("git_repo") or not provenance.get("git_commit_sha")
    ):
        raise ValidationError(
            "CI-published versions for this Agent require provenance.git_repo and "
            "provenance.git_commit_sha"
        )

    resolved_provenance: dict | None = None
    if via_ci and provenance and provenance.get("git_repo") and provenance.get("git_commit_sha"):
        resolved_provenance = {
            "git_repo": provenance["git_repo"],
            "git_commit_sha": provenance["git_commit_sha"],
            "git_ref": provenance.get("git_ref"),
            "image_digest": provenance.get("image_digest"),
            "publisher": "ci",
            "published_at": datetime.now(timezone.utc).isoformat(),
            # The agent-eval AgentVersion registered for this exact publish, if
            # any - set by app/api/ci_publish.py after a successful
            # agent_eval_client.register_agent_version() call. None when no
            # live evaluation target is configured for this Agent yet.
            "agent_eval_agent_version_id": provenance.get("agent_eval_agent_version_id"),
        }
        # Idempotent publication (the brief's explicit requirement): a CI
        # retry for the same commit must never create a duplicate version -
        # returns the existing one instead of erroring or double-publishing.
        existing_for_commit = (
            await db.execute(
                select(AgentVersion).where(
                    AgentVersion.agent_id == agent.id,
                    AgentVersion.provenance["git_commit_sha"].astext == resolved_provenance["git_commit_sha"],
                )
            )
        ).scalar_one_or_none()
        if existing_for_commit is not None:
            return existing_for_commit

    resolved = await resolve_manifest(db, agent, manifest)

    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        version_label=resolved.version_label,
        manifest=manifest,
        content_hash=resolved.content_hash,
        source_ref=resolved.source_ref,
        provenance=resolved_provenance,
        created_by=actor.id,
    )
    db.add(version)
    await db.flush()

    for skill_version_id in resolved.skill_version_ids:
        db.add(AgentVersionSkill(agent_version_id=version.id, skill_version_id=skill_version_id))

    db.add(
        AgentVersionLifecycle(
            agent_version_id=version.id,
            agent_id=agent.id,
            stage=Stage.DRAFT,
            entered_by=actor.id,
        )
    )

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="agent_version.created",
        entity_type="agent_version",
        entity_id=version.id,
        payload={
            "agent_id": str(agent.id),
            "version_label": resolved.version_label,
            "content_hash": resolved.content_hash,
            "skill_version_ids": [str(i) for i in resolved.skill_version_ids],
            "provenance": resolved_provenance,
        },
    )
    await db.commit()
    await db.refresh(version)
    return version


async def list_agent_versions(db: AsyncSession, agent_id: uuid.UUID) -> list[AgentVersion]:
    await get_agent(db, agent_id)
    result = await db.execute(
        select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.created_at)
    )
    return list(result.scalars().all())


async def get_agent_version(db: AsyncSession, version_id: uuid.UUID) -> AgentVersion:
    version = (
        await db.execute(select(AgentVersion).where(AgentVersion.id == version_id))
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"no agent version with id {version_id}")
    return version


async def get_agent_version_lifecycle(db: AsyncSession, version_id: uuid.UUID) -> AgentVersionLifecycle:
    lifecycle = (
        await db.execute(
            select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version_id)
        )
    ).scalar_one_or_none()
    if lifecycle is None:
        raise NotFoundError(f"no lifecycle row for agent version {version_id}")
    return lifecycle


async def list_pinned_skill_versions(db: AsyncSession, version_id: uuid.UUID) -> list[uuid.UUID]:
    result = await db.execute(
        select(AgentVersionSkill.skill_version_id).where(AgentVersionSkill.agent_version_id == version_id)
    )
    return list(result.scalars().all())


async def get_catalog_overview(db: AsyncSession) -> dict[uuid.UUID, dict]:
    """Phase 5: the Agent catalog page needs "which version is
    recommended" and a lifecycle-status rollup per Agent without an N+1 query
    per row - a display aggregation over AgentVersionLifecycle, not new
    domain logic (every fact here is already what
    app/models/agent.py::AgentVersionLifecycle.stage means)."""
    rows = await db.execute(
        select(AgentVersionLifecycle, AgentVersion)
        .join(AgentVersion, AgentVersion.id == AgentVersionLifecycle.agent_version_id)
        .order_by(AgentVersion.created_at)
    )
    overview: dict[uuid.UUID, dict] = {}
    for lifecycle, version in rows.all():
        entry = overview.setdefault(
            lifecycle.agent_id,
            {
                "recommended_version_id": None,
                "recommended_version_label": None,
                "stage_counts": {},
                # Phase 9: "what's the newest thing published" is a distinct
                # question from "what's currently recommended" -
                # docs/phase-notes/phase-9.md. Ordered by created_at above,
                # so the last row seen per agent is always the latest.
                "latest_version_id": None,
                "latest_version_label": None,
            },
        )
        entry["stage_counts"][lifecycle.stage.value] = entry["stage_counts"].get(lifecycle.stage.value, 0) + 1
        entry["latest_version_id"] = str(version.id)
        entry["latest_version_label"] = version.version_label
        if lifecycle.stage == Stage.RECOMMENDED:
            entry["recommended_version_id"] = str(version.id)
            entry["recommended_version_label"] = version.version_label
    return overview
