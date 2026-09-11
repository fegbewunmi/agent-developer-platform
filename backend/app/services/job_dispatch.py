"""The Cloud Tasks abstraction - docs/gcp-architecture.md, ADR-0011. Two real
implementations of the same interface, not one implementation pretending to be
the other:

- CloudTasksDispatcher: the real production path. Creates a real Cloud Tasks HTTP
  task, targeting this platform's own POST /internal/tasks/evaluations/{id} endpoint
  (app/api/tasks.py), authenticated via Cloud Tasks' native OIDC-token-to-Cloud-Run
  support. Genuinely exercised this phase as far as "create a real queue, enqueue a
  real task" (docs/phase-notes/phase-3.md's live verification) - NOT exercised as
  far as "a real queue delivers to a real running receiver," because that receiver
  is this platform's own API, which isn't deployed to Cloud Run yet (Phase 6 per
  docs/roadmap.md). This is a real, named gap, not something pretended away.
- LocalSyncDispatcher: the dev/test fallback. Fires the same worker function
  in-process via asyncio.create_task - non-blocking (satisfies "should not hold a
  user request open"), but explicitly NOT durable: no retry on failure, no
  persistence across a process restart, no at-least-once delivery guarantee. Every
  automated test and every live demo this phase actually ran against uses this
  path - documented precisely, never described as "the same as Cloud Tasks."
"""
import asyncio
import logging
import uuid
from typing import Protocol

logger = logging.getLogger(__name__)


class JobDispatcher(Protocol):
    async def dispatch_evaluation_job(self, evaluation_run_reference_id: uuid.UUID) -> None: ...


class LocalSyncDispatcher:
    """Non-blocking (asyncio.create_task, not awaited by the caller) but not durable.
    See module docstring. worker_fn is injected so this module has no dependency on
    app.services.evaluation_worker, avoiding a circular import.
    """

    def __init__(self, worker_fn):
        self._worker_fn = worker_fn

    async def dispatch_evaluation_job(self, evaluation_run_reference_id: uuid.UUID) -> None:
        asyncio.create_task(self._worker_fn(evaluation_run_reference_id))


class CloudTasksDispatcher:
    """Real google-cloud-tasks client. Requires the queue to already exist
    (see docs/gcp-architecture.md's deployment commands - created once via
    `gcloud tasks queues create`, not created implicitly here) and a deployed
    target_base_url that will actually receive the push.
    """

    def __init__(
        self,
        project: str,
        location: str,
        queue: str,
        target_base_url: str,
        target_service_account_email: str,
    ):
        self._project = project
        self._location = location
        self._queue = queue
        self._target_base_url = target_base_url.rstrip("/")
        self._target_service_account_email = target_service_account_email

    async def dispatch_evaluation_job(self, evaluation_run_reference_id: uuid.UUID) -> None:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksAsyncClient()
        parent = client.queue_path(self._project, self._location, self._queue)
        url = f"{self._target_base_url}/internal/tasks/evaluations/{evaluation_run_reference_id}"

        task = tasks_v2.Task(
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=url,
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._target_service_account_email,
                    audience=self._target_base_url,
                ),
            )
        )
        created = await client.create_task(parent=parent, task=task)
        logger.info(
            "cloud task created",
            extra={"evaluation_run_reference_id": str(evaluation_run_reference_id), "cloud_task_name": created.name},
        )
