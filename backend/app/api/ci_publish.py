"""Real CI publishing endpoint (Phase 8, ADR-0023, ADR-0024) - the only way
an AgentVersion is ever created for an Agent with `requires_ci_provenance`.
Not gated by get_current_user (no human is calling this) - protected by
real application-level OIDC verification of the CI publisher's Google-signed
token (app/auth/ci_publisher.py), the same mechanism app/auth/cloud_tasks.py
already proved out for Cloud Tasks/Scheduler pushes.
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.ci_publisher import CIPublisherAuth
from app.db.session import get_db
from app.models.identity import User
from app.services import agents as agents_service
from app.services.system_actor import get_system_actor_id

router = APIRouter(prefix="/internal/ci", tags=["internal"])


class Provenance(BaseModel):
    git_repo: str
    git_commit_sha: str
    git_ref: str | None = None
    image_digest: str | None = None


class PublishAgentVersionRequest(BaseModel):
    manifest: dict
    provenance: Provenance


@router.post("/agents/{agent_id}/versions", status_code=201, dependencies=[CIPublisherAuth])
async def publish_agent_version(
    agent_id: uuid.UUID, body: PublishAgentVersionRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    """Called by an integrated agent's own CI (e.g. `ai-operations`' GitHub
    Actions workflow) after it builds a real, immutable artifact from a real
    commit - never by a human. Idempotent per commit SHA: a retried publish
    for the same commit returns the existing AgentVersion rather than
    creating a duplicate (app/services/agents.py::create_agent_version).
    """
    system_actor_id = await get_system_actor_id(db)
    system_actor = (await db.execute(select(User).where(User.id == system_actor_id))).scalar_one()

    version = await agents_service.create_agent_version(
        db,
        actor=system_actor,
        agent_id=agent_id,
        manifest=body.manifest,
        via_ci=True,
        provenance=body.provenance.model_dump(),
    )

    return {
        "id": str(version.id),
        "agent_id": str(version.agent_id),
        "version_label": version.version_label,
        "content_hash": version.content_hash,
        "provenance": version.provenance,
        "created_at": version.created_at.isoformat(),
    }
