"""Phase 9 (ADR-0025): SkillVersion review request/decision flow - the same
no-self-approval, immutable-decision shape as app/services/promotions.py,
deliberately NOT built on PromotionRequest/PromotionDecision because those
are structurally tied to AgentVersion evaluation evidence (evaluation_run_
reference_id/evaluation_policy_id, both NOT NULL) that a SkillVersion simply
doesn't have - see docs/phase-notes/phase-9.md and
docs/adrs/0025-skill-review-as-a-separate-model.md.

A SkillVersion becomes RECOMMENDED only via an approved SkillReviewRequest -
never automatically on publish (app/services/skills.py::create_skill_version
always starts a new version at PUBLISHED).
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import SkillReviewDecisionType, SkillReviewRequestStatus, SkillStage
from app.models.identity import User
from app.models.skill import Skill, SkillVersion, SkillVersionLifecycle
from app.models.skill_review import SkillReviewDecision, SkillReviewRequest
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError

logger = logging.getLogger(__name__)

# Rollback works the same way it does for AgentVersions: a request may be
# filed from PUBLISHED (ordinary review) or DEPRECATED (re-recommend an old
# version) - not from RECOMMENDED itself.
_REVIEWABLE_SOURCE_STAGES = frozenset({SkillStage.PUBLISHED, SkillStage.DEPRECATED})


async def _get_skill_version_and_skill(db: AsyncSession, skill_version_id: uuid.UUID) -> tuple[SkillVersion, Skill]:
    version = (
        await db.execute(select(SkillVersion).where(SkillVersion.id == skill_version_id))
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"no skill version with id {skill_version_id}")
    skill = (await db.execute(select(Skill).where(Skill.id == version.skill_id))).scalar_one()
    return version, skill


async def _get_lifecycle(db: AsyncSession, skill_version_id: uuid.UUID) -> SkillVersionLifecycle:
    lifecycle = (
        await db.execute(
            select(SkillVersionLifecycle).where(SkillVersionLifecycle.skill_version_id == skill_version_id)
        )
    ).scalar_one_or_none()
    if lifecycle is None:
        raise NotFoundError(f"no lifecycle row for skill version {skill_version_id}")
    return lifecycle


async def _get_current_recommended_lifecycle(db: AsyncSession, skill_id: uuid.UUID) -> SkillVersionLifecycle | None:
    return (
        await db.execute(
            select(SkillVersionLifecycle).where(
                SkillVersionLifecycle.skill_id == skill_id, SkillVersionLifecycle.stage == SkillStage.RECOMMENDED
            )
        )
    ).scalar_one_or_none()


async def request_skill_review(
    db: AsyncSession, *, actor: User, skill_version_id: uuid.UUID, reason: str | None = None
) -> SkillReviewRequest:
    version, skill = await _get_skill_version_and_skill(db, skill_version_id)

    if not permissions.can_request_skill_review(actor, skill.owner_team_id):
        raise PermissionDeniedError("not authorized to request review for this skill")

    lifecycle = await _get_lifecycle(db, skill_version_id)
    if lifecycle.stage not in _REVIEWABLE_SOURCE_STAGES:
        raise ConflictError(
            f"skill version {skill_version_id} is in stage {lifecycle.stage.value!r}; review may only be "
            f"requested from published (ordinary) or deprecated (rollback)"
        )

    existing_pending = (
        await db.execute(
            select(SkillReviewRequest).where(
                SkillReviewRequest.skill_version_id == skill_version_id,
                SkillReviewRequest.status == SkillReviewRequestStatus.PENDING,
            )
        )
    ).scalar_one_or_none()
    if existing_pending is not None:
        raise ConflictError(
            f"skill version {skill_version_id} already has a pending review request ({existing_pending.id})"
        )

    request = SkillReviewRequest(
        id=uuid.uuid4(),
        skill_version_id=skill_version_id,
        requested_by=actor.id,
        status=SkillReviewRequestStatus.PENDING,
        reason=reason,
    )
    db.add(request)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            f"skill version {skill_version_id} already has a pending review request (created concurrently)"
        ) from None

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="skill_review.requested",
        entity_type="skill_review_request",
        entity_id=request.id,
        payload={"skill_version_id": str(skill_version_id), "skill_id": str(skill.id), "skill_name": skill.name},
    )
    await db.commit()
    await db.refresh(request)
    return request


async def approve_skill_review(
    db: AsyncSession, *, actor: User, skill_review_request_id: uuid.UUID, comment: str | None = None
) -> SkillReviewDecision:
    request = (
        await db.execute(select(SkillReviewRequest).where(SkillReviewRequest.id == skill_review_request_id))
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"no skill review request with id {skill_review_request_id}")

    if not permissions.can_decide_skill_review(actor, request.requested_by):
        raise PermissionDeniedError("not authorized to decide this skill review request")

    version, skill = await _get_skill_version_and_skill(db, request.skill_version_id)

    # Serialize every decision touching this Skill's recommended slot - same
    # advisory-lock shape as approve_promotion, same reason: the partial
    # unique index (skill_id) WHERE stage='recommended' is the DB-level
    # backstop, this lock prevents two concurrent approvals from both
    # observing "no current recommended version" and racing to set it.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:skill_id))"), {"skill_id": str(skill.id)})

    await db.refresh(request)
    if request.status != SkillReviewRequestStatus.PENDING:
        raise ConflictError(
            f"skill review request {skill_review_request_id} has already been decided ({request.status.value})"
        )

    lifecycle = await _get_lifecycle(db, request.skill_version_id)
    if lifecycle.stage not in _REVIEWABLE_SOURCE_STAGES:
        raise ConflictError(
            f"skill version {request.skill_version_id} is now in stage {lifecycle.stage.value!r}; "
            f"no longer eligible to be recommended"
        )

    current_recommended = await _get_current_recommended_lifecycle(db, skill.id)
    now = datetime.now(timezone.utc)
    is_rollback = lifecycle.stage == SkillStage.DEPRECATED
    supersedes_existing = current_recommended is not None and current_recommended.skill_version_id != lifecycle.skill_version_id

    # Same ordering requirement as approve_promotion: deprecate the old
    # recommended row as its own flushed statement BEFORE recommending the
    # new one, since the partial unique index is checked per-row, not
    # deferred to transaction end.
    if supersedes_existing:
        current_recommended.stage = SkillStage.DEPRECATED
        current_recommended.entered_by = actor.id
        current_recommended.entered_at = now
        await db.flush()

    lifecycle.stage = SkillStage.RECOMMENDED
    lifecycle.entered_by = actor.id
    lifecycle.entered_at = now

    decision = SkillReviewDecision(
        id=uuid.uuid4(),
        skill_review_request_id=request.id,
        decision=SkillReviewDecisionType.APPROVE,
        decided_by=actor.id,
        comment=comment,
    )
    db.add(decision)
    request.status = SkillReviewRequestStatus.APPROVED
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="skill_review.approved",
        entity_type="skill_review_request",
        entity_id=request.id,
        payload={"skill_version_id": str(request.skill_version_id), "skill_id": str(skill.id), "comment": comment},
    )
    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="skill_version.recommended",
        entity_type="skill_version",
        entity_id=request.skill_version_id,
        payload={
            "skill_id": str(skill.id),
            "skill_review_request_id": str(request.id),
            "is_rollback": is_rollback,
            "previous_recommended_skill_version_id": str(current_recommended.skill_version_id) if supersedes_existing else None,
        },
    )
    if supersedes_existing:
        record_audit_event(
            db,
            actor_id=actor.id,
            event_type="skill_version.deprecated",
            entity_type="skill_version",
            entity_id=current_recommended.skill_version_id,
            payload={"skill_id": str(skill.id), "reason": "superseded", "superseded_by": str(request.skill_version_id)},
        )

    await db.commit()
    await db.refresh(decision)
    logger.info(
        "skill review approved - recommendation change committed",
        extra={
            "skill_review_request_id": str(request.id),
            "skill_id": str(skill.id),
            "skill_version_id": str(request.skill_version_id),
        },
    )
    return decision


async def reject_skill_review(
    db: AsyncSession, *, actor: User, skill_review_request_id: uuid.UUID, comment: str | None = None
) -> SkillReviewDecision:
    request = (
        await db.execute(select(SkillReviewRequest).where(SkillReviewRequest.id == skill_review_request_id))
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"no skill review request with id {skill_review_request_id}")

    if not permissions.can_decide_skill_review(actor, request.requested_by):
        raise PermissionDeniedError("not authorized to decide this skill review request")

    version, skill = await _get_skill_version_and_skill(db, request.skill_version_id)

    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:skill_id))"), {"skill_id": str(skill.id)})
    await db.refresh(request)
    if request.status != SkillReviewRequestStatus.PENDING:
        raise ConflictError(
            f"skill review request {skill_review_request_id} has already been decided ({request.status.value})"
        )

    decision = SkillReviewDecision(
        id=uuid.uuid4(),
        skill_review_request_id=request.id,
        decision=SkillReviewDecisionType.REJECT,
        decided_by=actor.id,
        comment=comment,
    )
    db.add(decision)
    request.status = SkillReviewRequestStatus.REJECTED
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="skill_review.rejected",
        entity_type="skill_review_request",
        entity_id=request.id,
        payload={"skill_version_id": str(request.skill_version_id), "skill_id": str(skill.id), "comment": comment},
    )
    await db.commit()
    await db.refresh(decision)
    return decision


async def get_skill_review_request(db: AsyncSession, skill_review_request_id: uuid.UUID) -> SkillReviewRequest:
    request = (
        await db.execute(select(SkillReviewRequest).where(SkillReviewRequest.id == skill_review_request_id))
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"no skill review request with id {skill_review_request_id}")
    return request


async def get_skill_review_decision(db: AsyncSession, skill_review_request_id: uuid.UUID) -> SkillReviewDecision | None:
    return (
        await db.execute(
            select(SkillReviewDecision).where(SkillReviewDecision.skill_review_request_id == skill_review_request_id)
        )
    ).scalar_one_or_none()


async def list_skill_review_requests(
    db: AsyncSession, *, status: SkillReviewRequestStatus | None = None, limit: int = 100
) -> list[SkillReviewRequest]:
    """The reviewer queue - every pending (or all) skill review request
    across every Skill, mirroring promotions_service.list_promotion_requests.
    No demo-team bucketing here (unlike the Agent promotion queue) - the
    public demo sandbox has no skills of its own to review yet; revisit if
    that changes."""
    stmt = select(SkillReviewRequest)
    if status is not None:
        stmt = stmt.where(SkillReviewRequest.status == status)
    stmt = stmt.order_by(SkillReviewRequest.requested_at.desc()).limit(min(limit, 200))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_skill_review_requests_for_version(
    db: AsyncSession, skill_version_id: uuid.UUID
) -> list[SkillReviewRequest]:
    result = await db.execute(
        select(SkillReviewRequest)
        .where(SkillReviewRequest.skill_version_id == skill_version_id)
        .order_by(SkillReviewRequest.requested_at.desc())
    )
    return list(result.scalars().all())
