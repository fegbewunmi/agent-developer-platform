"""Real CI publishing endpoint (Phase 8, ADR-0023, ADR-0024) - the only way
an AgentVersion is ever created for an Agent with `requires_ci_provenance`.
Not gated by get_current_user (no human is calling this) - protected by
real application-level OIDC verification of the CI publisher's Google-signed
token (app/auth/ci_publisher.py), the same mechanism app/auth/cloud_tasks.py
already proved out for Cloud Tasks/Scheduler pushes.
"""
import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.ci_publisher import CIPublisherAuth
from app.config import settings
from app.db.session import get_db
from app.dependencies import get_agent_eval_client
from app.integrations.agent_eval_client import AgentEvalClient, AgentEvalError
from app.models.identity import User
from app.services import agents as agents_service
from app.services.system_actor import get_system_actor_id

logger = logging.getLogger(__name__)

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
    agent_id: uuid.UUID,
    body: PublishAgentVersionRequest,
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
) -> dict:
    """Called by an integrated agent's own CI (e.g. `ai-operations`' GitHub
    Actions workflow) after it builds a real, immutable artifact from a real
    commit - never by a human. Idempotent per commit SHA: a retried publish
    for the same commit returns the existing AgentVersion rather than
    creating a duplicate (app/services/agents.py::create_agent_version).

    Also registers a live, callable evaluation target for this exact publish
    in agent-eval (docs/adrs/0024-ci-publishing-machine-identity.md's closing
    piece) - best-effort: if agent-eval is unreachable or no target is
    configured for this Agent (settings.ci_publish_agent_eval_agent_id), the
    real provenance publish still succeeds; only the eval-registration field
    comes back empty. Publishing a real fact about source provenance must
    never fail because of an unrelated system.
    """
    provenance = body.provenance.model_dump()

    if settings.ci_publish_agent_eval_agent_id and settings.ci_publish_target_base_url:
        version_label = body.manifest.get("agent", {}).get("version")
        try:
            agent_eval_version_id = await agent_eval_client.register_agent_version(
                external_agent_id=settings.ci_publish_agent_eval_agent_id,
                version_label=version_label,
                config={"base_url": settings.ci_publish_target_base_url},
                description=f"Published by Orion from {provenance['git_repo']}@{provenance['git_commit_sha']}",
            )
            provenance["agent_eval_agent_version_id"] = agent_eval_version_id
        except AgentEvalError as exc:
            logger.warning(
                "could not register a live agent-eval target for this publish - "
                "provenance was still recorded",
                extra={"agent_id": str(agent_id), "error": str(exc)},
            )

    system_actor_id = await get_system_actor_id(db)
    system_actor = (await db.execute(select(User).where(User.id == system_actor_id))).scalar_one()

    version = await agents_service.create_agent_version(
        db,
        actor=system_actor,
        agent_id=agent_id,
        manifest=body.manifest,
        via_ci=True,
        provenance=provenance,
    )

    return {
        "id": str(version.id),
        "agent_id": str(version.agent_id),
        "version_label": version.version_label,
        "content_hash": version.content_hash,
        "provenance": version.provenance,
        "created_at": version.created_at.isoformat(),
    }
