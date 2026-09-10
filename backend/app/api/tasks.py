"""Real Cloud Tasks push target - docs/gcp-architecture.md, app/services/job_dispatch.py.
Not gated by get_current_user (no human is calling this) - in production, Cloud
Run's own IAM authenticates the push request's OIDC token before it ever reaches
this handler (mirrors how agent-eval-api itself is protected - see
docs/phase-notes/phase-3.md). This endpoint is unauthenticated at the application
layer by design, the same way it would be inappropriate for a Cloud Run health
check to require a JWT the platform issues to its own human users.
"""
import uuid

from fastapi import APIRouter

from app.dependencies import get_agent_eval_client
from app.services.evaluation_worker import process_evaluation_job

router = APIRouter(prefix="/internal/tasks", tags=["internal"])


@router.post("/evaluations/{reference_id}", status_code=204)
async def receive_evaluation_task(reference_id: uuid.UUID) -> None:
    await process_evaluation_job(reference_id, get_agent_eval_client())
