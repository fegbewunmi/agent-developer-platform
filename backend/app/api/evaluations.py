import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.dependencies import get_agent_eval_client, get_job_dispatcher
from app.integrations.agent_eval_client import AgentEvalClient
from app.models.agent import Agent, AgentVersion
from app.models.evaluation import EvaluationGateResult
from app.models.identity import User
from app.services import evaluations as evaluations_service
from app.services import freshness as freshness_service
from app.services.errors import NotFoundError
from app.services.job_dispatch import JobDispatcher

router = APIRouter(tags=["evaluations"])


class RequestEvaluationRequest(BaseModel):
    external_agent_version_id: str
    idempotency_key: str | None = None


def _reference_to_dict(ref) -> dict:
    return {
        "id": str(ref.id),
        "agent_version_id": str(ref.agent_version_id),
        "evaluation_policy_id": str(ref.evaluation_policy_id),
        "external_run_id": ref.external_run_id,
        "external_agent_version_id": ref.external_agent_version_id,
        "external_dataset_id": ref.external_dataset_id,
        "requested_by": str(ref.requested_by),
        "requested_at": ref.requested_at.isoformat(),
        "status": ref.status.value,
        "dataset_snapshot_hash": ref.dataset_snapshot_hash,
        "dimension_stats": ref.dimension_stats,
        "n_cases_total": ref.n_cases_total,
        "n_cases_success": ref.n_cases_success,
        "n_cases_error": ref.n_cases_error,
        "error_message": ref.error_message,
        "capability_grant_snapshot_hash": ref.capability_grant_snapshot_hash,
        "completed_at": ref.completed_at.isoformat() if ref.completed_at else None,
    }


def _gate_to_dict(g: EvaluationGateResult) -> dict:
    return {
        "id": str(g.id),
        "evaluation_run_reference_id": str(g.evaluation_run_reference_id),
        "gate_type": g.gate_type,
        "criterion": g.criterion,
        "expected": g.expected,
        "actual": g.actual,
        "passed": g.passed,
        "reason": g.reason,
        "evidence_ref": g.evidence_ref,
        "evaluated_at": g.evaluated_at.isoformat(),
    }


@router.post("/v1/agent-versions/{agent_version_id}/evaluations", status_code=202)
async def request_evaluation(
    agent_version_id: uuid.UUID,
    body: RequestEvaluationRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
    dispatcher: JobDispatcher = Depends(get_job_dispatcher),
) -> dict:
    """202, not 201/200: the returned reference is 'requested', not completed - the
    actual agent-eval run happens asynchronously (docs/evaluation-and-promotion.md).
    Poll GET .../evaluations/{id} for status.
    """
    reference = await evaluations_service.request_evaluation(
        db,
        agent_eval_client,
        dispatcher,
        actor=user,
        agent_version_id=agent_version_id,
        external_agent_version_id=body.external_agent_version_id,
        idempotency_key=body.idempotency_key,
    )
    return _reference_to_dict(reference)


@router.get("/v1/agent-versions/{agent_version_id}/evaluations")
async def list_evaluations(
    agent_version_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    refs = await evaluations_service.list_evaluation_run_references(db, agent_version_id)
    return [_reference_to_dict(r) for r in refs]


@router.get("/v1/evaluations/{reference_id}")
async def get_evaluation(
    reference_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return _reference_to_dict(await evaluations_service.get_evaluation_run_reference(db, reference_id))


@router.get("/v1/evaluations/{reference_id}/gates")
async def get_gate_results(
    reference_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    await evaluations_service.get_evaluation_run_reference(db, reference_id)  # 404 if missing
    result = await db.execute(
        select(EvaluationGateResult)
        .where(EvaluationGateResult.evaluation_run_reference_id == reference_id)
        .order_by(EvaluationGateResult.gate_type)
    )
    return [_gate_to_dict(g) for g in result.scalars().all()]


@router.get("/v1/agent-versions/{agent_version_id}/candidacy")
async def get_candidacy(
    agent_version_id: uuid.UUID,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
) -> dict:
    """docs/evaluation-and-promotion.md's core distinction: 'evaluation passed at
    the time' vs 'evidence is still valid for review now'. Always computed live,
    never cached - a version can be stage=evaluated while this reports
    currently_eligible=false with explicit stale_findings.
    """
    version = (await db.execute(select(AgentVersion).where(AgentVersion.id == agent_version_id))).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"no agent version with id {agent_version_id}")
    agent = (await db.execute(select(Agent).where(Agent.id == version.agent_id))).scalar_one()

    result = await freshness_service.check_freshness(db, agent_eval_client, agent_version_id, agent.name)
    return {
        "agent_version_id": result.agent_version_id,
        "current_stage": result.current_stage,
        "evaluation_run_reference_id": result.evaluation_run_reference_id,
        "historically_passed": result.historically_passed,
        "currently_eligible": result.currently_eligible,
        "stale_findings": [{"reason": f.reason, "detail": f.detail} for f in result.stale_findings],
    }
