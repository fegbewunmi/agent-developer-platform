"""Evaluation request flow - docs/evaluation-and-promotion.md's integration contract.
Everything here is fast, local, and synchronous by design; the slow part (actually
calling agent-eval's blocking POST /runs) happens in the dispatched job
(app/services/evaluation_worker.py), never in this request path - "the Developer
Platform should not hold a user request open for the full synchronous Agent Eval run."
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.agent_eval_client import AgentEvalClient
from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import EvaluationRunStatus, Stage
from app.models.evaluation import EvaluationRunReference
from app.models.identity import User
from app.services import evaluation_policies as policies_service
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.services.evidence_snapshot import take_capability_grant_snapshot
from app.services.job_dispatch import JobDispatcher

# Only these stages may accept a new evaluation request - see
# docs/evaluation-and-promotion.md's lifecycle diagram. draft/evaluating both allow
# it (evaluating -> evaluating covers re-runs after a transient failure sent the
# version back to draft and it was re-requested, or a still-in-flight duplicate
# request - see the idempotency handling below for why that's still safe).
_REQUESTABLE_STAGES = {Stage.DRAFT, Stage.EVALUATING}


async def _get_agent_version_and_agent(db: AsyncSession, agent_version_id: uuid.UUID) -> tuple[AgentVersion, Agent]:
    version = (
        await db.execute(select(AgentVersion).where(AgentVersion.id == agent_version_id))
    ).scalar_one_or_none()
    if version is None:
        raise NotFoundError(f"no agent version with id {agent_version_id}")
    agent = (await db.execute(select(Agent).where(Agent.id == version.agent_id))).scalar_one()
    return version, agent


async def _enforce_demo_evaluation_guardrails(
    db: AsyncSession, *, actor: User, external_agent_version_id: str
) -> None:
    """Phase 7 public demo: real safeguards against an expensive/abusive
    external call, not just a role check. See docs/phase-notes/phase-7.md.

    - Fixed target: demo evaluations may only invoke the one known-safe,
      free-to-run agent-eval stub target - never an arbitrary or expensive
      external_agent_version_id a visitor could type in.
    - Per-actor cooldown: one request per demo_eval_cooldown_seconds per
      actor, defeating rapid double-submission.
    - Global concurrency cap: at most demo_eval_concurrency_cap evaluations
      may be in flight (requested/dispatched) across ALL demo activity at
      once, bounding real load on agent-eval-api/Cloud Tasks regardless of
      how many visitors are trying it simultaneously.
    """
    if settings.demo_external_agent_version_id and external_agent_version_id != settings.demo_external_agent_version_id:
        raise ValidationError(
            "the public demo may only evaluate against its designated safe target - "
            "a custom external_agent_version_id is not permitted here"
        )

    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.demo_eval_cooldown_seconds)
    recent = (
        await db.execute(
            select(func.count())
            .select_from(EvaluationRunReference)
            .where(
                EvaluationRunReference.requested_by == actor.id,
                EvaluationRunReference.requested_at >= cooldown_cutoff,
            )
        )
    ).scalar_one()
    if recent > 0:
        raise ConflictError(
            f"the public demo allows one evaluation request every {settings.demo_eval_cooldown_seconds}s per user - "
            f"please wait before requesting another"
        )

    in_flight = (
        await db.execute(
            select(func.count())
            .select_from(EvaluationRunReference)
            .join(AgentVersion, AgentVersion.id == EvaluationRunReference.agent_version_id)
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(
                Agent.team_id == actor.team_id,
                EvaluationRunReference.status.in_([EvaluationRunStatus.REQUESTED, EvaluationRunStatus.DISPATCHED]),
            )
        )
    ).scalar_one()
    if in_flight >= settings.demo_eval_concurrency_cap:
        raise ConflictError(
            "the public demo has reached its concurrent-evaluation limit - please try again shortly"
        )


async def request_evaluation(
    db: AsyncSession,
    agent_eval_client: AgentEvalClient,
    dispatcher: JobDispatcher,
    *,
    actor: User,
    agent_version_id: uuid.UUID,
    external_agent_version_id: str,
    idempotency_key: str | None = None,
) -> EvaluationRunReference:
    version, agent = await _get_agent_version_and_agent(db, agent_version_id)

    if not permissions.can_request_evaluation(actor, agent.team_id) or not permissions.demo_containment_ok(
        actor, agent.team_id
    ):
        raise PermissionDeniedError("not authorized to request an evaluation for this agent")

    if permissions.is_demo_actor(actor):
        await _enforce_demo_evaluation_guardrails(db, actor=actor, external_agent_version_id=external_agent_version_id)

    if idempotency_key:
        existing = (
            await db.execute(
                select(EvaluationRunReference).where(EvaluationRunReference.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    lifecycle = (
        await db.execute(
            select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == agent_version_id)
        )
    ).scalar_one()
    if lifecycle.stage not in _REQUESTABLE_STAGES:
        raise ConflictError(
            f"agent version {agent_version_id} is in stage {lifecycle.stage.value!r}; "
            f"evaluation may only be requested from draft or evaluating"
        )

    policy = await policies_service.get_current_policy_for_agent(db, agent.name)

    datasets = await agent_eval_client.list_datasets()
    dataset = next((d for d in datasets if d.name == policy.dataset_key), None)
    if dataset is None:
        raise ValidationError(
            f"policy {policy.name}@{policy.version} requires dataset {policy.dataset_key!r}, "
            f"which does not currently exist in agent-eval"
        )

    live_evaluators = await agent_eval_client.list_evaluators()
    live_by_key = {e.key: e for e in live_evaluators}
    resolved_evaluator_ids: list[str] = []
    submitted_evaluator_versions: dict[str, str] = {}
    for key, required_version in policy.required_evaluator_keys.items():
        evaluator = live_by_key.get(key)
        if evaluator is None or evaluator.version != required_version:
            found = f"version {evaluator.version!r}" if evaluator else "not found"
            raise ValidationError(
                f"policy {policy.name}@{policy.version} requires evaluator {key}@{required_version}, "
                f"but agent-eval currently has {found}"
            )
        resolved_evaluator_ids.append(evaluator.id)
        submitted_evaluator_versions[key] = evaluator.version

    snapshot = await take_capability_grant_snapshot(db, agent_version_id)

    reference = EvaluationRunReference(
        id=uuid.uuid4(),
        agent_version_id=agent_version_id,
        evaluation_policy_id=policy.id,
        external_agent_version_id=external_agent_version_id,
        external_dataset_id=dataset.id,
        external_evaluator_ids={"ids": resolved_evaluator_ids, "versions": submitted_evaluator_versions},
        requested_by=actor.id,
        status=EvaluationRunStatus.REQUESTED,
        capability_grant_snapshot_hash=snapshot.hash,
        capability_grant_snapshot=snapshot.snapshot,
        idempotency_key=idempotency_key,
    )
    db.add(reference)
    await db.flush()

    if lifecycle.stage != Stage.EVALUATING:
        lifecycle.stage = Stage.EVALUATING
        lifecycle.entered_by = actor.id

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="evaluation.requested",
        entity_type="evaluation_run_reference",
        entity_id=reference.id,
        payload={
            "agent_version_id": str(agent_version_id),
            "evaluation_policy_id": str(policy.id),
            "external_agent_version_id": external_agent_version_id,
            "external_dataset_id": dataset.id,
        },
    )
    await db.commit()
    await db.refresh(reference)

    await dispatcher.dispatch_evaluation_job(reference.id)

    return reference


async def get_evaluation_run_reference(db: AsyncSession, reference_id: uuid.UUID) -> EvaluationRunReference:
    ref = (
        await db.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one_or_none()
    if ref is None:
        raise NotFoundError(f"no evaluation run reference with id {reference_id}")
    return ref


async def list_evaluation_run_references(db: AsyncSession, agent_version_id: uuid.UUID) -> list[EvaluationRunReference]:
    result = await db.execute(
        select(EvaluationRunReference)
        .where(EvaluationRunReference.agent_version_id == agent_version_id)
        .order_by(EvaluationRunReference.requested_at.desc())
    )
    return list(result.scalars().all())
