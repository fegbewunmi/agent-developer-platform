"""Review request/decision flow - docs/evaluation-and-promotion.md's review
lifecycle, docs/adrs/0018-promotion-request-immutability.md,
docs/adrs/0007-promotion-state-machine.md, docs/adrs/0023-registry-not-deployment-platform.md.

A PromotionRequest captures the full decision context at request time (not just
agent_version_id - see migrations/versions/0014_promotion_request_snapshot.py).
The class/table name is unchanged since Phase 8's terminology correction
(ADR-0023) - "promotion" doesn't itself imply deployment the way "production"
did, so only the Stage vocabulary and user-facing copy were renamed, not this
entity. Deciding it (approve/reject) re-checks freshness LIVE, right before the
decision, producing a second, independent snapshot - "eligible when requested"
vs "eligible when reviewed" are both permanent, stored facts (ADR-0018), never
silently recomputed or refreshed on the caller's behalf.

evaluated/deprecated are both legal source stages for a review request
(docs/evaluation-and-promotion.md's state diagram: `evaluated -> recommended`
and `deprecated -> recommended` (rollback) are the same transition, gated the
same way - ADR-0007's Phase 4 update resolves docs/open-questions.md item 2 in
favor of "gates stay hard even for rollback," no bypass).
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.agent_eval_client import AgentEvalClient
from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import PromotionDecisionType, PromotionRequestStatus, Stage
from app.models.evaluation import EvaluationGateResult, EvaluationRunReference
from app.models.identity import User
from app.models.outbox import OutboxEvent
from app.models.promotion import PromotionDecision, PromotionRequest
from app.services import freshness as freshness_service
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.services.event_publisher import EventPublisher
from app.services.evidence_snapshot import take_capability_grant_snapshot
from app.services.freshness import FreshnessResult

logger = logging.getLogger(__name__)

# Both legal source stages for `-> recommended`, per
# docs/evaluation-and-promotion.md's state diagram: an ordinary review
# (evaluated) and a rollback (deprecated) are gated identically - no separate,
# weaker rollback path. `draft`/`evaluating`/`recommended` cannot receive a
# PromotionRequest at all.
_PROMOTABLE_SOURCE_STAGES = frozenset({Stage.EVALUATED, Stage.DEPRECATED})


async def _get_agent_version_and_agent(db: AsyncSession, agent_version_id: uuid.UUID) -> tuple[AgentVersion, Agent]:
    version = (
        await db.execute(select(AgentVersion).where(AgentVersion.id == agent_version_id))
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"no agent version with id {agent_version_id}")
    agent = (await db.execute(select(Agent).where(Agent.id == version.agent_id))).scalar_one()
    return version, agent


async def _get_lifecycle(db: AsyncSession, agent_version_id: uuid.UUID) -> AgentVersionLifecycle:
    lifecycle = (
        await db.execute(
            select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == agent_version_id)
        )
    ).scalar_one_or_none()
    if lifecycle is None:
        raise NotFoundError(f"no lifecycle row for agent version {agent_version_id}")
    return lifecycle


async def _get_current_production_lifecycle(db: AsyncSession, agent_id: uuid.UUID) -> AgentVersionLifecycle | None:
    return (
        await db.execute(
            select(AgentVersionLifecycle).where(
                AgentVersionLifecycle.agent_id == agent_id, AgentVersionLifecycle.stage == Stage.RECOMMENDED
            )
        )
    ).scalar_one_or_none()


def _freshness_to_dict(result: FreshnessResult) -> dict:
    return {
        "historically_passed": result.historically_passed,
        "currently_eligible": result.currently_eligible,
        "current_stage": result.current_stage,
        "evaluation_run_reference_id": result.evaluation_run_reference_id,
        "stale_findings": [{"reason": f.reason, "detail": f.detail} for f in result.stale_findings],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


async def request_promotion(
    db: AsyncSession,
    agent_eval_client: AgentEvalClient,
    *,
    actor: User,
    agent_version_id: uuid.UUID,
    reason: str | None = None,
) -> PromotionRequest:
    version, agent = await _get_agent_version_and_agent(db, agent_version_id)

    if not permissions.can_request_promotion(actor, agent.team_id) or not permissions.demo_containment_ok(
        actor, agent.team_id
    ):
        raise PermissionDeniedError("not authorized to request a promotion for this agent")

    lifecycle = await _get_lifecycle(db, agent_version_id)
    if lifecycle.stage not in _PROMOTABLE_SOURCE_STAGES:
        raise ConflictError(
            f"agent version {agent_version_id} is in stage {lifecycle.stage.value!r}; review may only be "
            f"requested from evaluated (ordinary) or deprecated (rollback)"
        )

    existing_pending = (
        await db.execute(
            select(PromotionRequest).where(
                PromotionRequest.agent_version_id == agent_version_id,
                PromotionRequest.status == PromotionRequestStatus.PENDING,
            )
        )
    ).scalar_one_or_none()
    if existing_pending is not None:
        raise ConflictError(
            f"agent version {agent_version_id} already has a pending promotion request ({existing_pending.id})"
        )

    # A PromotionRequest is rejected outright if the evidence isn't currently
    # eligible - docs/roadmap.md's Phase 4 scope note. This is a real gate, not
    # just informational: freshness_snapshot below always reflects
    # currently_eligible=True at request time by construction. A request that
    # later becomes stale before it's decided is exactly what
    # freshness_snapshot_at_decision (PromotionDecision) exists to capture.
    freshness = await freshness_service.check_freshness(
        db, agent_eval_client, agent_version_id, agent.name, promotable_stages=_PROMOTABLE_SOURCE_STAGES
    )
    if not freshness.currently_eligible:
        reasons = ", ".join(f.reason for f in freshness.stale_findings) or "no passing evaluation evidence exists"
        raise ConflictError(f"agent version {agent_version_id} is not currently eligible for promotion: {reasons}")

    reference = (
        await db.execute(
            select(EvaluationRunReference).where(
                EvaluationRunReference.id == uuid.UUID(freshness.evaluation_run_reference_id)
            )
        )
    ).scalar_one()

    snapshot = await take_capability_grant_snapshot(db, agent_version_id)
    current_prod = await _get_current_production_lifecycle(db, agent.id)

    request = PromotionRequest(
        id=uuid.uuid4(),
        agent_version_id=agent_version_id,
        from_stage=lifecycle.stage,
        to_stage=Stage.RECOMMENDED,
        requested_by=actor.id,
        evaluation_run_reference_id=reference.id,
        evaluation_policy_id=reference.evaluation_policy_id,
        capability_grant_snapshot_hash=snapshot.hash,
        capability_grant_snapshot=snapshot.snapshot,
        production_version_id_at_request=current_prod.agent_version_id if current_prod else None,
        freshness_snapshot=_freshness_to_dict(freshness),
        status=PromotionRequestStatus.PENDING,
        reason=reason,
    )
    db.add(request)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            f"agent version {agent_version_id} already has a pending promotion request "
            f"(created concurrently by another request)"
        ) from None

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="promotion.requested",
        entity_type="promotion_request",
        entity_id=request.id,
        payload={
            "agent_version_id": str(agent_version_id),
            "agent_id": str(agent.id),
            "from_stage": lifecycle.stage.value,
            "to_stage": Stage.RECOMMENDED.value,
            "evaluation_run_reference_id": str(reference.id),
            "evaluation_policy_id": str(reference.evaluation_policy_id),
            "is_rollback": lifecycle.stage == Stage.DEPRECATED,
        },
    )
    await db.commit()
    await db.refresh(request)
    logger.info(
        "promotion requested",
        extra={
            "promotion_request_id": str(request.id),
            "agent_version_id": str(agent_version_id),
            "agent_id": str(agent.id),
            "from_stage": request.from_stage.value,
        },
    )
    return request


async def approve_promotion(
    db: AsyncSession,
    agent_eval_client: AgentEvalClient,
    event_publisher: EventPublisher,
    *,
    actor: User,
    promotion_request_id: uuid.UUID,
    comment: str | None = None,
) -> PromotionDecision:
    request = (
        await db.execute(select(PromotionRequest).where(PromotionRequest.id == promotion_request_id))
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"no promotion request with id {promotion_request_id}")

    if not permissions.can_decide_promotion(actor, request.requested_by):
        raise PermissionDeniedError("not authorized to decide this promotion request")

    version, agent = await _get_agent_version_and_agent(db, request.agent_version_id)

    if not permissions.demo_containment_ok(actor, agent.team_id):
        raise PermissionDeniedError("not authorized to decide this promotion request")

    # Serialize every decision touching this Agent's recommended slot. An
    # advisory lock keyed on the Agent (not a row-level FOR UPDATE on any
    # single AgentVersionLifecycle row) is the right primitive here: approval
    # can rewrite TWO lifecycle rows (the newly-approved version's and the
    # previously-recommended version's), and the previously-recommended row
    # may not exist at all - see docs/adrs/0007-promotion-state-machine.md.
    # The partial unique index on AgentVersionLifecycle (agent_id) WHERE
    # stage='recommended' remains the final DB-level backstop regardless.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:agent_id))"), {"agent_id": str(agent.id)})

    # Re-read after acquiring the lock: another decision on this same request
    # (or a concurrent one for a different evaluated version of the same
    # Agent) may have committed while this call was waiting.
    await db.refresh(request)
    if request.status != PromotionRequestStatus.PENDING:
        raise ConflictError(
            f"promotion request {promotion_request_id} has already been decided ({request.status.value})"
        )

    lifecycle = await _get_lifecycle(db, request.agent_version_id)
    if lifecycle.stage not in _PROMOTABLE_SOURCE_STAGES:
        raise ConflictError(
            f"agent version {request.agent_version_id} is now in stage {lifecycle.stage.value!r}; "
            f"no longer eligible to be promoted"
        )

    # Defense-in-depth re-check: EvaluationGateResult rows are immutable once
    # written (Phase 3), so this can only fail if the request's own
    # evaluation_run_reference_id is somehow wrong - genuinely expected to
    # always pass, kept explicit per docs/evaluation-and-promotion.md's
    # review/approval sequence.
    gate_rows = (
        await db.execute(
            select(EvaluationGateResult).where(
                EvaluationGateResult.evaluation_run_reference_id == request.evaluation_run_reference_id
            )
        )
    ).scalars().all()
    if not gate_rows or not all(g.passed for g in gate_rows):
        raise ConflictError(
            f"promotion request {promotion_request_id}'s cited evaluation run no longer has all gates passing"
        )

    # Decision-time freshness - the SAME check as request time, recomputed
    # live, never reused from the request's own snapshot ("do not silently
    # refresh or rerun evaluation as part of approval" - this recomputes
    # freshness, never the evaluation itself).
    freshness = await freshness_service.check_freshness(
        db, agent_eval_client, request.agent_version_id, agent.name, promotable_stages=_PROMOTABLE_SOURCE_STAGES
    )
    freshness_dict = _freshness_to_dict(freshness)
    if not freshness.currently_eligible:
        record_audit_event(
            db,
            actor_id=actor.id,
            event_type="promotion.approval_blocked_stale",
            entity_type="promotion_request",
            entity_id=request.id,
            payload={"agent_version_id": str(request.agent_version_id), "stale_findings": freshness_dict["stale_findings"]},
        )
        await db.commit()
        reasons = ", ".join(f.reason for f in freshness.stale_findings) or "evidence is no longer eligible"
        logger.warning(
            "promotion approval blocked - stale evidence",
            extra={"promotion_request_id": str(promotion_request_id), "agent_id": str(agent.id), "stale_reasons": reasons},
        )
        raise ConflictError(f"promotion request {promotion_request_id} is no longer eligible for approval: {reasons}")

    current_prod = await _get_current_production_lifecycle(db, agent.id)
    now = datetime.now(timezone.utc)
    is_rollback = request.from_stage == Stage.DEPRECATED
    supersedes_existing_production = current_prod is not None and current_prod.agent_version_id != lifecycle.agent_version_id

    # Deprecate the old recommended row BEFORE approving the new one, as two
    # separate statements (flush in between) - the partial unique index
    # `UNIQUE (agent_id) WHERE stage='recommended'` is checked immediately per
    # row, not deferred to transaction end, so batching both UPDATEs together
    # (or approving first) can transiently violate it even though the final
    # state is valid. Real bug, caught by tests/test_promotions.py's rollback
    # test against the real constraint - not merely reasoned about.
    if supersedes_existing_production:
        current_prod.stage = Stage.DEPRECATED
        current_prod.entered_by = actor.id
        current_prod.entered_at = now
        await db.flush()

    lifecycle.stage = Stage.RECOMMENDED
    lifecycle.entered_by = actor.id
    lifecycle.entered_at = now

    decision = PromotionDecision(
        id=uuid.uuid4(),
        promotion_request_id=request.id,
        decision=PromotionDecisionType.APPROVE,
        decided_by=actor.id,
        comment=comment,
        freshness_snapshot_at_decision=freshness_dict,
    )
    db.add(decision)
    request.status = PromotionRequestStatus.APPROVED
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="promotion.approved",
        entity_type="promotion_request",
        entity_id=request.id,
        payload={
            "agent_version_id": str(request.agent_version_id),
            "agent_id": str(agent.id),
            "comment": comment,
        },
    )
    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="agent_version.promoted",
        entity_type="agent_version",
        entity_id=request.agent_version_id,
        payload={
            "agent_id": str(agent.id),
            "promotion_request_id": str(request.id),
            "is_rollback": is_rollback,
            "previous_production_agent_version_id": str(current_prod.agent_version_id) if supersedes_existing_production else None,
        },
    )
    if supersedes_existing_production:
        record_audit_event(
            db,
            actor_id=actor.id,
            event_type="agent_version.retired",
            entity_type="agent_version",
            entity_id=current_prod.agent_version_id,
            payload={"agent_id": str(agent.id), "reason": "superseded", "superseded_by": str(request.agent_version_id)},
        )
    if is_rollback:
        record_audit_event(
            db,
            actor_id=actor.id,
            event_type="promotion.rollback",
            entity_type="agent_version",
            entity_id=request.agent_version_id,
            payload={"agent_id": str(agent.id), "promotion_request_id": str(request.id)},
        )

    # Outbox: written in the SAME transaction as the recommendation change
    # above - never published before this commits. See
    # docs/adrs/0020-promotion-lifecycle-event-outbox.md.
    outbox = OutboxEvent(
        id=uuid.uuid4(),
        event_type="agent_version.promoted",
        entity_type="agent_version",
        entity_id=request.agent_version_id,
        payload={
            "agent_id": str(agent.id),
            "agent_version_id": str(request.agent_version_id),
            "promotion_request_id": str(request.id),
            "is_rollback": is_rollback,
            "previous_production_agent_version_id": str(current_prod.agent_version_id) if supersedes_existing_production else None,
            "promoted_by": str(actor.id),
            "promoted_at": now.isoformat(),
        },
    )
    db.add(outbox)
    await db.flush()

    await db.commit()
    await db.refresh(decision)
    logger.info(
        "promotion approved - recommendation change committed",
        extra={
            "promotion_request_id": str(request.id),
            "agent_id": str(agent.id),
            "agent_version_id": str(request.agent_version_id),
            "is_rollback": is_rollback,
            "outbox_event_id": str(outbox.id),
        },
    )

    await event_publisher.publish(outbox.id)

    return decision


async def reject_promotion(
    db: AsyncSession,
    agent_eval_client: AgentEvalClient,
    *,
    actor: User,
    promotion_request_id: uuid.UUID,
    comment: str | None = None,
) -> PromotionDecision:
    request = (
        await db.execute(select(PromotionRequest).where(PromotionRequest.id == promotion_request_id))
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"no promotion request with id {promotion_request_id}")

    if not permissions.can_decide_promotion(actor, request.requested_by):
        raise PermissionDeniedError("not authorized to decide this promotion request")

    version, agent = await _get_agent_version_and_agent(db, request.agent_version_id)

    if not permissions.demo_containment_ok(actor, agent.team_id):
        raise PermissionDeniedError("not authorized to decide this promotion request")

    # Same lock as approve_promotion - a reject and an approve racing for the
    # same request must not both succeed.
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:agent_id))"), {"agent_id": str(agent.id)})
    await db.refresh(request)
    if request.status != PromotionRequestStatus.PENDING:
        raise ConflictError(
            f"promotion request {promotion_request_id} has already been decided ({request.status.value})"
        )

    # Rejection is never blocked by staleness - a Reviewer may reject for any
    # reason. freshness_snapshot_at_decision is still recorded (not used as a
    # gate here) so the rejection is auditable against exactly what evidence
    # state the reviewer saw - docs/adrs/0018-promotion-request-immutability.md.
    freshness = await freshness_service.check_freshness(
        db, agent_eval_client, request.agent_version_id, agent.name, promotable_stages=_PROMOTABLE_SOURCE_STAGES
    )
    freshness_dict = _freshness_to_dict(freshness)

    # No lifecycle transition - a rejected version stays `evaluated` (or
    # `deprecated`, for a rejected rollback attempt). docs/evaluation-and-
    # promotion.md's state diagram has no `evaluated -> draft` edge; the only
    # way out of evaluated other than recommended is the explicit, separate
    # `evaluated -> deprecated` abandon transition (not built this phase - see
    # docs/adrs/0007-promotion-state-machine.md). The version remains
    # eligible for a fresh PromotionRequest once the old one is no longer
    # pending.
    decision = PromotionDecision(
        id=uuid.uuid4(),
        promotion_request_id=request.id,
        decision=PromotionDecisionType.REJECT,
        decided_by=actor.id,
        comment=comment,
        freshness_snapshot_at_decision=freshness_dict,
    )
    db.add(decision)
    request.status = PromotionRequestStatus.REJECTED
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="promotion.rejected",
        entity_type="promotion_request",
        entity_id=request.id,
        payload={"agent_version_id": str(request.agent_version_id), "agent_id": str(agent.id), "comment": comment},
    )
    await db.commit()
    await db.refresh(decision)
    logger.info(
        "promotion rejected",
        extra={"promotion_request_id": str(request.id), "agent_id": str(agent.id), "agent_version_id": str(request.agent_version_id)},
    )
    return decision


async def get_promotion_request(db: AsyncSession, promotion_request_id: uuid.UUID) -> PromotionRequest:
    request = (
        await db.execute(select(PromotionRequest).where(PromotionRequest.id == promotion_request_id))
    ).scalar_one_or_none()
    if request is None:
        raise NotFoundError(f"no promotion request with id {promotion_request_id}")
    return request


async def get_promotion_decision(db: AsyncSession, promotion_request_id: uuid.UUID) -> PromotionDecision | None:
    return (
        await db.execute(select(PromotionDecision).where(PromotionDecision.promotion_request_id == promotion_request_id))
    ).scalar_one_or_none()


async def list_promotion_requests(
    db: AsyncSession, *, status: PromotionRequestStatus | None = None, limit: int = 100, actor: User | None = None
) -> list[PromotionRequest]:
    """Phase 5: the reviewer queue needs every pending request across every
    Agent, not scoped to one version (list_promotion_requests_for_version)
    or one Agent's history (list_promotion_history_for_agent) - neither
    existing function answers "what's waiting on any reviewer right now."
    Read access is universal, same as every other list endpoint; the
    frontend applies self-approval/role-based action visibility, backed by
    the real can_decide_promotion check at approve/reject time regardless.

    Phase 7: when `actor` is given, applies the same demo/non-demo bucket
    split as app/services/dashboard.py - a demo actor's queue shows only the
    demo agent's requests; a real Orion actor's queue never shows the demo
    agent's, preserving real cross-team reviewer visibility otherwise.
    `actor=None` (the two other callers below, scoped to one version/Agent
    already) keeps the old, unfiltered behavior.
    """
    stmt = select(PromotionRequest)
    if status is not None:
        stmt = stmt.where(PromotionRequest.status == status)
    if actor is not None:
        from app.services import permissions

        demo_team = permissions.demo_team_uuid()
        if demo_team is not None:
            stmt = stmt.join(AgentVersion, AgentVersion.id == PromotionRequest.agent_version_id).join(
                Agent, Agent.id == AgentVersion.agent_id
            )
            stmt = stmt.where(Agent.team_id == demo_team if actor.team_id == demo_team else Agent.team_id != demo_team)
    stmt = stmt.order_by(PromotionRequest.requested_at.desc()).limit(min(limit, 200))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_promotion_requests_for_version(db: AsyncSession, agent_version_id: uuid.UUID) -> list[PromotionRequest]:
    result = await db.execute(
        select(PromotionRequest)
        .where(PromotionRequest.agent_version_id == agent_version_id)
        .order_by(PromotionRequest.requested_at.desc())
    )
    return list(result.scalars().all())


async def list_promotion_history_for_agent(db: AsyncSession, agent_id: uuid.UUID) -> list[PromotionRequest]:
    """Every PromotionRequest across every AgentVersion this Agent has ever
    had - "why is this exact version recommended right now?" is answerable
    from this list plus each request's PromotionDecision, without
    reconstructing intent from mutable tables (docs/audit-model.md)."""
    result = await db.execute(
        select(PromotionRequest)
        .join(AgentVersion, AgentVersion.id == PromotionRequest.agent_version_id)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(PromotionRequest.requested_at.desc())
    )
    return list(result.scalars().all())
