import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import SkillStage, Stage
from app.models.identity import Team, User
from app.models.skill import AgentVersionSkill, Skill, SkillVersion, SkillVersionLifecycle
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError


async def create_skill(
    db: AsyncSession, *, actor: User, name: str, owner_team_id: uuid.UUID, description: str | None
) -> Skill:
    if not permissions.can_publish_skill_version(actor, owner_team_id):
        raise PermissionDeniedError("not authorized to create a skill for this team")

    team = (await db.execute(select(Team).where(Team.id == owner_team_id))).scalar_one_or_none()
    if team is None:
        raise NotFoundError(f"no team with id {owner_team_id}")

    existing = (await db.execute(select(Skill.id).where(Skill.name == name))).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"a skill named {name!r} already exists")

    skill = Skill(id=uuid.uuid4(), name=name, owner_team_id=owner_team_id, description=description)
    db.add(skill)
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="skill.created",
        entity_type="skill",
        entity_id=skill.id,
        payload={"name": name, "owner_team_id": str(owner_team_id)},
    )
    await db.commit()
    await db.refresh(skill)
    return skill


async def list_skills(
    db: AsyncSession,
    *,
    search: str | None = None,
    owner_team_id: uuid.UUID | None = None,
    framework: str | None = None,
) -> list[Skill]:
    """Phase 9: the Skills catalog needs to be searchable/filterable to be a
    real registry a developer can discover from, not just a flat list -
    docs/phase-notes/phase-9.md. `framework` filters against any published
    SkillVersion.compatible_frameworks for that skill (a Skill itself has no
    framework field - that's per-version, see SkillVersion)."""
    stmt = select(Skill)
    if search:
        pattern = f"%{search.lower()}%"
        from sqlalchemy import func, or_

        stmt = stmt.where(or_(func.lower(Skill.name).like(pattern), func.lower(Skill.description).like(pattern)))
    if owner_team_id is not None:
        stmt = stmt.where(Skill.owner_team_id == owner_team_id)
    if framework:
        stmt = stmt.where(
            Skill.id.in_(
                select(SkillVersion.skill_id).where(SkillVersion.compatible_frameworks.any(framework))
            )
        )
    stmt = stmt.order_by(Skill.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_skill(db: AsyncSession, skill_id: uuid.UUID) -> Skill:
    skill = (await db.execute(select(Skill).where(Skill.id == skill_id))).scalar_one_or_none()
    if skill is None:
        raise NotFoundError(f"no skill with id {skill_id}")
    return skill


async def create_skill_version(
    db: AsyncSession,
    *,
    actor: User,
    skill_id: uuid.UUID,
    version: str,
    purpose: str,
    input_contract: str | None,
    output_contract: str | None,
    implementation_ref: str | None,
    compatible_frameworks: list[str],
) -> SkillVersion:
    skill = await get_skill(db, skill_id)

    if not permissions.can_publish_skill_version(actor, skill.owner_team_id):
        raise PermissionDeniedError("not authorized to publish a version of this skill")

    if not version:
        raise ValidationError("version is required")

    existing = (
        await db.execute(
            select(SkillVersion.id).where(SkillVersion.skill_id == skill_id, SkillVersion.version == version)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"skill {skill.name!r} already has a version {version!r}")

    skill_version = SkillVersion(
        id=uuid.uuid4(),
        skill_id=skill_id,
        version=version,
        owner_user_id=actor.id,
        purpose=purpose,
        input_contract=input_contract,
        output_contract=output_contract,
        implementation_ref=implementation_ref,
        compatible_frameworks=compatible_frameworks,
    )
    db.add(skill_version)
    await db.flush()

    # Every SkillVersion gets a lifecycle row at creation, same as
    # AgentVersion - starts PUBLISHED, never RECOMMENDED by default. Becoming
    # RECOMMENDED requires an independent reviewer (see
    # app/services/skill_reviews.py), not automatic on publish.
    lifecycle = SkillVersionLifecycle(
        skill_version_id=skill_version.id, skill_id=skill_id, stage=SkillStage.PUBLISHED, entered_by=actor.id
    )
    db.add(lifecycle)
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="skill_version.published",
        entity_type="skill_version",
        entity_id=skill_version.id,
        payload={"skill_id": str(skill_id), "skill_name": skill.name, "version": version},
    )
    await db.commit()
    await db.refresh(skill_version)
    return skill_version


async def get_skill_version_lifecycle(db: AsyncSession, skill_version_id: uuid.UUID) -> SkillVersionLifecycle:
    lifecycle = (
        await db.execute(
            select(SkillVersionLifecycle).where(SkillVersionLifecycle.skill_version_id == skill_version_id)
        )
    ).scalar_one_or_none()
    if lifecycle is None:
        raise NotFoundError(f"no lifecycle row for skill version {skill_version_id}")
    return lifecycle


async def get_skill_catalog_overview(db: AsyncSession) -> dict[uuid.UUID, dict]:
    """Phase 9: same aggregation shape as agents.py::get_catalog_overview -
    "which version is recommended" and consumer/version counts per Skill,
    without an N+1 query per catalog row."""
    rows = await db.execute(
        select(SkillVersionLifecycle, SkillVersion).join(
            SkillVersion, SkillVersion.id == SkillVersionLifecycle.skill_version_id
        )
    )
    overview: dict[uuid.UUID, dict] = {}
    for lifecycle, version in rows.all():
        entry = overview.setdefault(
            lifecycle.skill_id,
            {"recommended_version_id": None, "recommended_version_label": None, "version_count": 0},
        )
        entry["version_count"] += 1
        if lifecycle.stage == SkillStage.RECOMMENDED:
            entry["recommended_version_id"] = str(version.id)
            entry["recommended_version_label"] = version.version

    consumer_rows = await db.execute(
        select(SkillVersion.skill_id, AgentVersionSkill.agent_version_id).join(
            AgentVersionSkill, AgentVersionSkill.skill_version_id == SkillVersion.id
        )
    )
    consumers_by_skill: dict[uuid.UUID, set[uuid.UUID]] = {}
    for skill_id, agent_version_id in consumer_rows.all():
        consumers_by_skill.setdefault(skill_id, set()).add(agent_version_id)
    for skill_id, consuming_versions in consumers_by_skill.items():
        overview.setdefault(
            skill_id, {"recommended_version_id": None, "recommended_version_label": None, "version_count": 0}
        )["consuming_agent_version_count"] = len(consuming_versions)
    for entry in overview.values():
        entry.setdefault("consuming_agent_version_count", 0)
    return overview


async def get_skill_consumers(db: AsyncSession, skill_id: uuid.UUID) -> dict[uuid.UUID, list[dict]]:
    """Phase 9: per SkillVersion, which (Agent, AgentVersion) pairs pin it -
    the real relationship behind the old "Pinned by <version_label>" badge,
    now with the agent's own name attached (docs/phase-notes/phase-9.md)."""
    await get_skill(db, skill_id)
    rows = await db.execute(
        select(SkillVersion.id, AgentVersion, Agent)
        .join(AgentVersionSkill, AgentVersionSkill.skill_version_id == SkillVersion.id)
        .join(AgentVersion, AgentVersion.id == AgentVersionSkill.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(SkillVersion.skill_id == skill_id)
        .order_by(AgentVersion.created_at)
    )
    consumers: dict[uuid.UUID, list[dict]] = {}
    for skill_version_id, agent_version, agent in rows.all():
        consumers.setdefault(skill_version_id, []).append(
            {
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "agent_version_id": str(agent_version.id),
                "version_label": agent_version.version_label,
            }
        )
    return consumers


async def get_skill_impact(db: AsyncSession, skill_id: uuid.UUID) -> dict:
    """Phase 9: "if a newer SkillVersion is published, who's still on an
    older one" - the dependency/impact view your brief calls for. Two
    deliberately separate views, per your refinement:

    - `current_impact`: each Agent's single MOST RECENT AgentVersion (any
      stage except deprecated - a deprecated version has already been
      superseded and showing it here would be noise), if it pins an older
      SkillVersion than the latest one published for this skill. One row
      per Agent, matching your own example's format.
    - `historical_consumers`: every AgentVersion that has EVER pinned an
      older SkillVersion, unfiltered - the full archaeological record,
      deliberately kept separate so it doesn't drown out current_impact.

    No new tables - purely a read aggregation over SkillVersion,
    AgentVersionSkill, AgentVersion, AgentVersionLifecycle, Agent, all of
    which already exist.
    """
    skill = await get_skill(db, skill_id)
    versions = await list_skill_versions(db, skill_id)
    if not versions:
        return {"skill_id": str(skill_id), "latest_version": None, "current_impact": [], "historical_consumers": []}
    latest = versions[-1]

    older_version_ids = [v.id for v in versions if v.id != latest.id]
    if not older_version_ids:
        return {
            "skill_id": str(skill_id),
            "latest_version": {"id": str(latest.id), "version": latest.version},
            "current_impact": [],
            "historical_consumers": [],
        }

    historical_rows = await db.execute(
        select(SkillVersion.id, SkillVersion.version, AgentVersion, Agent)
        .join(AgentVersionSkill, AgentVersionSkill.skill_version_id == SkillVersion.id)
        .join(AgentVersion, AgentVersion.id == AgentVersionSkill.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(SkillVersion.id.in_(older_version_ids))
        .order_by(AgentVersion.created_at.desc())
    )
    historical_consumers = [
        {
            "skill_version_id": str(sv_id),
            "skill_version": sv_version,
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "agent_version_id": str(av.id),
            "version_label": av.version_label,
        }
        for sv_id, sv_version, av, agent in historical_rows.all()
    ]

    # Each Agent's single most recent, non-deprecated AgentVersion - matched
    # against whether it pins an older SkillVersion of this skill.
    latest_per_agent_rows = await db.execute(
        select(AgentVersion, Agent, AgentVersionLifecycle.stage)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .join(AgentVersionLifecycle, AgentVersionLifecycle.agent_version_id == AgentVersion.id)
        .where(AgentVersionLifecycle.stage != Stage.DEPRECATED)
        .order_by(AgentVersion.agent_id, AgentVersion.created_at.desc())
    )
    latest_by_agent: dict[uuid.UUID, tuple[AgentVersion, Agent]] = {}
    for av, agent, _stage in latest_per_agent_rows.all():
        if agent.id not in latest_by_agent:
            latest_by_agent[agent.id] = (av, agent)

    latest_agent_version_ids = {av.id for av, _agent in latest_by_agent.values()}
    current_impact = [
        c for c in historical_consumers if uuid.UUID(c["agent_version_id"]) in latest_agent_version_ids
    ]

    return {
        "skill_id": str(skill_id),
        "skill_name": skill.name,
        "latest_version": {"id": str(latest.id), "version": latest.version},
        "current_impact": current_impact,
        "historical_consumers": historical_consumers,
    }


async def list_skill_versions(db: AsyncSession, skill_id: uuid.UUID) -> list[SkillVersion]:
    await get_skill(db, skill_id)
    result = await db.execute(
        select(SkillVersion).where(SkillVersion.skill_id == skill_id).order_by(SkillVersion.created_at)
    )
    return list(result.scalars().all())


async def get_skill_version(db: AsyncSession, skill_version_id: uuid.UUID) -> SkillVersion:
    skill_version = (
        await db.execute(select(SkillVersion).where(SkillVersion.id == skill_version_id))
    ).scalar_one_or_none()
    if skill_version is None:
        raise NotFoundError(f"no skill version with id {skill_version_id}")
    return skill_version


async def list_agent_versions_using_skill_version(
    db: AsyncSession, skill_version_id: uuid.UUID
) -> list[tuple[AgentVersion, Agent]]:
    """docs/skills-and-capabilities.md: "inspect which agent versions use a
    given SkillVersion" - a reverse lookup through the immutable
    AgentVersionSkill pin, never through anything mutable. Phase 9: returns
    the owning Agent alongside each AgentVersion - a raw version_label with
    no Agent name told a developer nothing (docs/phase-notes/phase-9.md).
    """
    await get_skill_version(db, skill_version_id)
    result = await db.execute(
        select(AgentVersion, Agent)
        .join(AgentVersionSkill, AgentVersionSkill.agent_version_id == AgentVersion.id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(AgentVersionSkill.skill_version_id == skill_version_id)
        .order_by(AgentVersion.created_at)
    )
    return list(result.all())
