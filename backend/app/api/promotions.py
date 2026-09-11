import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.dependencies import get_agent_eval_client, get_event_publisher
from app.integrations.agent_eval_client import AgentEvalClient
from app.models.identity import User
from app.models.promotion import PromotionDecision, PromotionRequest
from app.services import promotions as promotions_service
from app.services.event_publisher import EventPublisher
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["promotions"])


class RequestPromotionRequest(BaseModel):
    reason: str | None = None


class DecidePromotionRequest(BaseModel):
    comment: str | None = None


def _request_to_dict(r: PromotionRequest) -> dict:
    return {
        "id": str(r.id),
        "agent_version_id": str(r.agent_version_id),
        "from_stage": r.from_stage.value,
        "to_stage": r.to_stage.value,
        "requested_by": str(r.requested_by),
        "requested_at": r.requested_at.isoformat(),
        "evaluation_run_reference_id": str(r.evaluation_run_reference_id),
        "evaluation_policy_id": str(r.evaluation_policy_id),
        "capability_grant_snapshot_hash": r.capability_grant_snapshot_hash,
        "production_version_id_at_request": str(r.production_version_id_at_request) if r.production_version_id_at_request else None,
        "freshness_snapshot": r.freshness_snapshot,
        "status": r.status.value,
        "reason": r.reason,
    }


def _decision_to_dict(d: PromotionDecision) -> dict:
    return {
        "id": str(d.id),
        "promotion_request_id": str(d.promotion_request_id),
        "decision": d.decision.value,
        "decided_by": str(d.decided_by),
        "decided_at": d.decided_at.isoformat(),
        "comment": d.comment,
        "freshness_snapshot_at_decision": d.freshness_snapshot_at_decision,
    }


@router.post("/v1/agent-versions/{agent_version_id}/promotion-requests", status_code=201)
async def request_promotion(
    agent_version_id: uuid.UUID,
    body: RequestPromotionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
) -> dict:
    request = await promotions_service.request_promotion(
        db, agent_eval_client, actor=user, agent_version_id=agent_version_id, reason=body.reason
    )
    return _request_to_dict(request)


@router.get("/v1/agent-versions/{agent_version_id}/promotion-requests")
async def list_promotion_requests(
    agent_version_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    requests = await promotions_service.list_promotion_requests_for_version(db, agent_version_id)
    return [_request_to_dict(r) for r in requests]


@router.get("/v1/promotion-requests/{promotion_request_id}")
async def get_promotion_request(
    promotion_request_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    request = await promotions_service.get_promotion_request(db, promotion_request_id)
    decision = await promotions_service.get_promotion_decision(db, promotion_request_id)
    result = _request_to_dict(request)
    result["decision"] = _decision_to_dict(decision) if decision else None
    return result


@router.post("/v1/promotion-requests/{promotion_request_id}/approve", status_code=201)
async def approve_promotion(
    promotion_request_id: uuid.UUID,
    body: DecidePromotionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
    event_publisher: EventPublisher = Depends(get_event_publisher),
) -> dict:
    decision = await promotions_service.approve_promotion(
        db, agent_eval_client, event_publisher, actor=user, promotion_request_id=promotion_request_id, comment=body.comment
    )
    return _decision_to_dict(decision)


@router.post("/v1/promotion-requests/{promotion_request_id}/reject", status_code=201)
async def reject_promotion(
    promotion_request_id: uuid.UUID,
    body: DecidePromotionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
) -> dict:
    decision = await promotions_service.reject_promotion(
        db, agent_eval_client, actor=user, promotion_request_id=promotion_request_id, comment=body.comment
    )
    return _decision_to_dict(decision)


@router.get("/v1/agents/{agent_id}/promotion-history")
async def get_promotion_history(
    agent_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    requests = await promotions_service.list_promotion_history_for_agent(db, agent_id)
    result = []
    for r in requests:
        entry = _request_to_dict(r)
        decision = await promotions_service.get_promotion_decision(db, r.id)
        entry["decision"] = _decision_to_dict(decision) if decision else None
        result.append(entry)
    return result
