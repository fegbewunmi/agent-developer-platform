"""Real Cloud Tasks push target - docs/gcp-architecture.md,
app/services/job_dispatch.py, app/auth/cloud_tasks.py.

Not gated by get_current_user (no human is calling this). As of Phase 6,
the real deployed protection is application-level OIDC verification
(app/auth/cloud_tasks.py::verify_cloud_tasks_push), not Cloud Run ingress
IAM - see that module's docstring for why (the service is also the API the
frontend's Server Components call with the platform's own user JWTs in the
same Authorization header an IAM-enforced service would consume for its own
check, so the two schemes can't share one Cloud Run service safely).
"""
import logging
import uuid

from fastapi import APIRouter, Depends, Request

from app.auth.cloud_tasks import CloudTasksAuth
from app.dependencies import get_agent_eval_client, get_event_publisher
from app.services.event_publisher import EventPublisher, sweep_unpublished_outbox_events
from app.services.evaluation_worker import process_evaluation_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/tasks", tags=["internal"])


@router.post("/evaluations/{reference_id}", status_code=204, dependencies=[CloudTasksAuth])
async def receive_evaluation_task(reference_id: uuid.UUID, request: Request) -> None:
    logger.info(
        "cloud task push received",
        extra={
            "evaluation_run_reference_id": str(reference_id),
            "cloud_task_name": request.headers.get("x-cloudtasks-taskname"),
            "cloud_task_retry_count": request.headers.get("x-cloudtasks-taskretrycount"),
        },
    )
    await process_evaluation_job(reference_id, get_agent_eval_client())


@router.post("/outbox/sweep", dependencies=[CloudTasksAuth])
async def sweep_outbox(event_publisher: EventPublisher = Depends(get_event_publisher)) -> dict:
    """Cloud Scheduler HTTP target (docs/gcp-architecture.md) - periodically
    retries any OutboxEvent still unpublished after its original attempt.
    See app/services/event_publisher.py::sweep_unpublished_outbox_events.
    """
    return await sweep_unpublished_outbox_events(event_publisher)
