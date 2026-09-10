import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentVersion
from app.models.identity import Team, User
from app.models.skill import AgentVersionSkill, Skill, SkillVersion
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


async def list_skills(db: AsyncSession) -> list[Skill]:
    result = await db.execute(select(Skill).order_by(Skill.name))
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
) -> list[AgentVersion]:
    """docs/skills-and-capabilities.md: "inspect which agent versions use a
    given SkillVersion" - a reverse lookup through the immutable
    AgentVersionSkill pin, never through anything mutable.
    """
    await get_skill_version(db, skill_version_id)
    result = await db.execute(
        select(AgentVersion)
        .join(AgentVersionSkill, AgentVersionSkill.agent_version_id == AgentVersion.id)
        .where(AgentVersionSkill.skill_version_id == skill_version_id)
        .order_by(AgentVersion.created_at)
    )
    return list(result.scalars().all())
