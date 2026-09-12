"""Phase 9 (ADR-0025): SkillVersion review requests - mirrors
app/api/promotions.py's shape, deliberately not sharing routes/models with
it (see app/services/skill_reviews.py's module docstring for why).
"""
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.enums import SkillReviewRequestStatus
from app.models.identity import User
from app.models.skill import Skill, SkillVersion
from app.services import skill_reviews as skill_reviews_service

router = APIRouter(tags=["skill-reviews"])


class RequestSkillReviewRequest(BaseModel):
    reason: str | None = None


class SkillReviewDecisionRequest(BaseModel):
    comment: str | None = None


def _request_to_dict(r) -> dict:
    return {
        "id": str(r.id),
        "skill_version_id": str(r.skill_version_id),
        "requested_by": str(r.requested_by),
        "requested_at": r.requested_at.isoformat(),
        "status": r.status.value,
        "reason": r.reason,
    }


def _decision_to_dict(d) -> dict:
    return {
        "id": str(d.id),
        "skill_review_request_id": str(d.skill_review_request_id),
        "decision": d.decision.value,
        "decided_by": str(d.decided_by),
        "decided_at": d.decided_at.isoformat(),
        "comment": d.comment,
    }


async def _enrich(db: AsyncSession, requests: list) -> list[dict]:
    version_ids = {r.skill_version_id for r in requests}
    context: dict[uuid.UUID, tuple[SkillVersion, Skill]] = {}
    if version_ids:
        rows = await db.execute(
            select(SkillVersion, Skill).join(Skill, Skill.id == SkillVersion.skill_id).where(SkillVersion.id.in_(version_ids))
        )
        context = {v.id: (v, s) for v, s in rows.all()}
    out = []
    for r in requests:
        entry = _request_to_dict(r)
        ctx = context.get(r.skill_version_id)
        entry["skill_id"] = str(ctx[1].id) if ctx else None
        entry["skill_name"] = ctx[1].name if ctx else None
        entry["skill_version_label"] = ctx[0].version if ctx else None
        out.append(entry)
    return out


@router.post("/v1/skill-versions/{skill_version_id}/review-requests", status_code=201)
async def create_skill_review_request(
    skill_version_id: uuid.UUID,
    body: RequestSkillReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    request = await skill_reviews_service.request_skill_review(
        db, actor=user, skill_version_id=skill_version_id, reason=body.reason
    )
    return _request_to_dict(request)


@router.get("/v1/skill-versions/{skill_version_id}/review-requests")
async def list_skill_review_requests_for_version(
    skill_version_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return [
        _request_to_dict(r)
        for r in await skill_reviews_service.list_skill_review_requests_for_version(db, skill_version_id)
    ]


@router.get("/v1/skill-review-requests")
async def list_skill_review_requests(
    status: SkillReviewRequestStatus | None = Query(None),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The skill-review queue, mirroring GET /v1/promotion-requests - every
    request across every Skill, enriched with skill/version display context
    (a display join, not new logic, same shape as app/api/promotions.py)."""
    requests = await skill_reviews_service.list_skill_review_requests(db, status=status)
    return await _enrich(db, requests)


@router.get("/v1/skill-review-requests/{skill_review_request_id}")
async def get_skill_review_request(
    skill_review_request_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    request = await skill_reviews_service.get_skill_review_request(db, skill_review_request_id)
    decision = await skill_reviews_service.get_skill_review_decision(db, skill_review_request_id)
    entry = (await _enrich(db, [request]))[0]
    entry["decision"] = _decision_to_dict(decision) if decision else None
    return entry


@router.post("/v1/skill-review-requests/{skill_review_request_id}/approve", status_code=201)
async def approve_skill_review_request(
    skill_review_request_id: uuid.UUID,
    body: SkillReviewDecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    decision = await skill_reviews_service.approve_skill_review(
        db, actor=user, skill_review_request_id=skill_review_request_id, comment=body.comment
    )
    return _decision_to_dict(decision)


@router.post("/v1/skill-review-requests/{skill_review_request_id}/reject", status_code=201)
async def reject_skill_review_request(
    skill_review_request_id: uuid.UUID,
    body: SkillReviewDecisionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    decision = await skill_reviews_service.reject_skill_review(
        db, actor=user, skill_review_request_id=skill_review_request_id, comment=body.comment
    )
    return _decision_to_dict(decision)
