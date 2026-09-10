import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import Stage
from app.models.identity import Team, User
from app.models.skill import AgentVersionSkill
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.services.manifest import resolve_manifest


async def create_agent(
    db: AsyncSession, *, actor: User, name: str, team_id: uuid.UUID, description: str | None
) -> Agent:
    if not permissions.can_create_agent(actor, team_id):
        raise PermissionDeniedError("not authorized to create an agent for this team")

    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if team is None:
        raise NotFoundError(f"no team with id {team_id}")

    existing = (await db.execute(select(Agent.id).where(Agent.name == name))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"an agent named {name!r} already exists")

    agent = Agent(id=uuid.uuid4(), name=name, team_id=team_id, description=description)
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
) -> AgentVersion:
    """Creates one immutable AgentVersion, its skill pins, and its initial
    (draft) lifecycle row, in a single transaction - all-or-nothing, matching
    docs/agent-versioning.md's write-once guarantee and
    docs/agent-versioning.md#the-stage-vs-content-split (stage lives on
    AgentVersionLifecycle, never as a mutable field here).
    """
    agent = await get_agent(db, agent_id)

    if not permissions.can_create_agent(actor, agent.team_id):
        raise PermissionDeniedError("not authorized to create a version for this agent")

    resolved = await resolve_manifest(db, agent, manifest)

    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent.id,
        version_label=resolved.version_label,
        manifest=manifest,
        content_hash=resolved.content_hash,
        source_ref=resolved.source_ref,
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
