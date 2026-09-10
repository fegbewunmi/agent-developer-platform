"""Cross-cutting FastAPI dependency providers for Phase 3's external integrations -
kept separate from app/auth/dependencies.py since these aren't auth-specific.
"""
from functools import lru_cache

from app.config import settings
from app.integrations.agent_eval_client import HttpAgentEvalClient, default_id_token_provider
from app.services.job_dispatch import CloudTasksDispatcher, JobDispatcher, LocalSyncDispatcher


@lru_cache
def get_agent_eval_client() -> HttpAgentEvalClient:
    id_token_provider = (
        default_id_token_provider(settings.agent_eval_audience, settings.agent_eval_impersonate_service_account)
        if settings.agent_eval_audience
        else None
    )
    return HttpAgentEvalClient(base_url=settings.agent_eval_base_url, id_token_provider=id_token_provider)


@lru_cache
def get_job_dispatcher() -> JobDispatcher:
    if settings.job_dispatch_mode == "cloud_tasks":
        assert settings.cloud_tasks_project, "cloud_tasks_project is required when job_dispatch_mode=cloud_tasks"
        return CloudTasksDispatcher(
            project=settings.cloud_tasks_project,
            location=settings.cloud_tasks_location,
            queue=settings.cloud_tasks_queue,
            target_base_url=settings.cloud_tasks_target_base_url,
            target_service_account_email=settings.cloud_tasks_target_service_account_email,
        )

    from app.services.evaluation_worker import process_evaluation_job

    client = get_agent_eval_client()

    async def _worker(reference_id):
        await process_evaluation_job(reference_id, client)

    return LocalSyncDispatcher(worker_fn=_worker)
