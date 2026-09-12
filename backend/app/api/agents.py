import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.identity import User
from app.services import agents as agents_service

router = APIRouter(prefix="/v1/agents", tags=["agents"])
versions_router = APIRouter(prefix="/v1/agent-versions", tags=["agent-versions"])


class CreateAgentRequest(BaseModel):
    name: str
    team_id: uuid.UUID
    description: str | None = None
    requires_ci_provenance: bool = False


class CreateAgentVersionRequest(BaseModel):
    manifest: dict


def _agent_to_dict(agent) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "team_id": str(agent.team_id),
        "description": agent.description,
        "is_representative_data": agent.is_representative_data,
        "requires_ci_provenance": agent.requires_ci_provenance,
    }


def _version_to_dict(version) -> dict:
    return {
        "id": str(version.id),
        "agent_id": str(version.agent_id),
        "version_label": version.version_label,
        "content_hash": version.content_hash,
        "source_ref": version.source_ref,
        "provenance": version.provenance,
        "created_by": str(version.created_by),
        "created_at": version.created_at.isoformat(),
    }


@router.get("")
async def list_agents(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    overview = await agents_service.get_catalog_overview(db)
    result = []
    for a in await agents_service.list_agents(db):
        entry = _agent_to_dict(a)
        entry.update(overview.get(a.id, {"recommended_version_id": None, "recommended_version_label": None, "stage_counts": {}}))
        result.append(entry)
    return result


@router.post("", status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await agents_service.create_agent(
        db,
        actor=user,
        name=body.name,
        team_id=body.team_id,
        description=body.description,
        requires_ci_provenance=body.requires_ci_provenance,
    )
    return _agent_to_dict(agent)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await agents_service.get_agent(db, agent_id)
    entry = _agent_to_dict(agent)
    overview = await agents_service.get_catalog_overview(db)
    entry.update(overview.get(agent.id, {"recommended_version_id": None, "recommended_version_label": None, "stage_counts": {}}))
    return entry


@router.get("/{agent_id}/versions")
async def list_agent_versions(
    agent_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return [_version_to_dict(v) for v in await agents_service.list_agent_versions(db, agent_id)]


@router.post("/{agent_id}/versions", status_code=201)
async def create_agent_version(
    agent_id: uuid.UUID,
    body: CreateAgentVersionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """No PATCH/PUT endpoint exists for an AgentVersion, deliberately - once
    created it cannot be mutated (docs/adrs/0002-immutable-versioned-artifacts.md).
    A new configuration means a new version, created here again with a new
    version_label.
    """
    version = await agents_service.create_agent_version(db, actor=user, agent_id=agent_id, manifest=body.manifest)
    return _version_to_dict(version)


async def _version_detail(version_id: uuid.UUID, db: AsyncSession) -> dict:
    version = await agents_service.get_agent_version(db, version_id)
    lifecycle = await agents_service.get_agent_version_lifecycle(db, version_id)
    skill_version_ids = await agents_service.list_pinned_skill_versions(db, version_id)
    body = _version_to_dict(version)
    body["stage"] = lifecycle.stage.value
    body["pinned_skill_version_ids"] = [str(i) for i in skill_version_ids]
    return body


@versions_router.get("/{version_id}")
async def get_agent_version(
    version_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _version_detail(version_id, db)


@versions_router.get("/{version_id}/manifest")
async def get_agent_version_manifest(
    version_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    version = await agents_service.get_agent_version(db, version_id)
    return {
        "agent_version_id": str(version.id),
        "content_hash": version.content_hash,
        "manifest": version.manifest,
    }
