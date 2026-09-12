import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.identity import User
from app.services import skills as skills_service

router = APIRouter(prefix="/v1/skills", tags=["skills"])
versions_router = APIRouter(prefix="/v1/skill-versions", tags=["skill-versions"])


class CreateSkillRequest(BaseModel):
    name: str
    owner_team_id: uuid.UUID
    description: str | None = None


class CreateSkillVersionRequest(BaseModel):
    version: str
    purpose: str
    input_contract: str | None = None
    output_contract: str | None = None
    implementation_ref: str | None = None
    compatible_frameworks: list[str] = []


def _skill_to_dict(skill, overview: dict | None = None) -> dict:
    entry = {
        "id": str(skill.id),
        "name": skill.name,
        "owner_team_id": str(skill.owner_team_id),
        "description": skill.description,
    }
    entry.update(overview or {"recommended_version_id": None, "recommended_version_label": None, "version_count": 0, "consuming_agent_version_count": 0})
    return entry


def _skill_version_to_dict(sv, stage: str | None = None) -> dict:
    return {
        "id": str(sv.id),
        "skill_id": str(sv.skill_id),
        "version": sv.version,
        "owner_user_id": str(sv.owner_user_id),
        "purpose": sv.purpose,
        "input_contract": sv.input_contract,
        "output_contract": sv.output_contract,
        "implementation_ref": sv.implementation_ref,
        "compatible_frameworks": sv.compatible_frameworks,
        "created_at": sv.created_at.isoformat(),
        "stage": stage,
    }


@router.get("")
async def list_skills(
    search: str | None = Query(None),
    owner_team_id: uuid.UUID | None = Query(None),
    framework: str | None = Query(None),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    skills = await skills_service.list_skills(db, search=search, owner_team_id=owner_team_id, framework=framework)
    overview = await skills_service.get_skill_catalog_overview(db)
    return [_skill_to_dict(s, overview.get(s.id)) for s in skills]


@router.post("", status_code=201)
async def create_skill(
    body: CreateSkillRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    skill = await skills_service.create_skill(
        db, actor=user, name=body.name, owner_team_id=body.owner_team_id, description=body.description
    )
    return _skill_to_dict(skill)


@router.get("/{skill_id}")
async def get_skill(
    skill_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    skill = await skills_service.get_skill(db, skill_id)
    overview = await skills_service.get_skill_catalog_overview(db)
    return _skill_to_dict(skill, overview.get(skill_id))


@router.get("/{skill_id}/versions")
async def list_skill_versions(
    skill_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    versions = await skills_service.list_skill_versions(db, skill_id)
    stages: dict[uuid.UUID, str] = {}
    for v in versions:
        lifecycle = await skills_service.get_skill_version_lifecycle(db, v.id)
        stages[v.id] = lifecycle.stage.value
    return [_skill_version_to_dict(v, stages.get(v.id)) for v in versions]


@router.get("/{skill_id}/impact")
async def get_skill_impact(
    skill_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """Phase 9: "if the latest SkillVersion isn't what most consumers are
    on, who's affected" - see app/services/skills.py::get_skill_impact for
    the current_impact/historical_consumers split."""
    return await skills_service.get_skill_impact(db, skill_id)


@router.post("/{skill_id}/versions", status_code=201)
async def create_skill_version(
    skill_id: uuid.UUID,
    body: CreateSkillVersionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """No PATCH endpoint, deliberately - a SkillVersion is immutable once
    published (docs/skills-and-capabilities.md); a change is a new version.
    """
    sv = await skills_service.create_skill_version(
        db,
        actor=user,
        skill_id=skill_id,
        version=body.version,
        purpose=body.purpose,
        input_contract=body.input_contract,
        output_contract=body.output_contract,
        implementation_ref=body.implementation_ref,
        compatible_frameworks=body.compatible_frameworks,
    )
    return _skill_version_to_dict(sv, "published")


@versions_router.get("/{skill_version_id}")
async def get_skill_version(
    skill_version_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    sv = await skills_service.get_skill_version(db, skill_version_id)
    lifecycle = await skills_service.get_skill_version_lifecycle(db, skill_version_id)
    return _skill_version_to_dict(sv, lifecycle.stage.value)


@versions_router.get("/{skill_version_id}/agent-versions")
async def list_agent_versions_using_skill_version(
    skill_version_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await skills_service.list_agent_versions_using_skill_version(db, skill_version_id)
    return [
        {"id": str(v.id), "agent_id": str(v.agent_id), "agent_name": a.name, "version_label": v.version_label}
        for v, a in rows
    ]
