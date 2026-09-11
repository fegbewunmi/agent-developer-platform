"""The actual evaluation work - called either by LocalSyncDispatcher (in-process,
fire-and-forget) or by POST /internal/tasks/evaluations/{id} (a real Cloud Tasks
push target). One function, two callers - "one code path for triggering a run,"
matching agent-eval's own stated design philosophy for its runner.

Runs with its own DB session (SessionLocal directly, not FastAPI's Depends(get_db)),
since it executes outside any request's dependency-injection scope.
"""
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.integrations.agent_eval_client import (
    AgentEvalClient,
    AgentEvalMalformedResponseError,
    AgentEvalTimeoutError,
    AgentEvalUnavailableError,
    ComparisonResult,
)
from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import EvaluationRunStatus, Stage
from app.models.evaluation import EvaluationRunReference
from app.services import gates as gates_service
from app.services.audit import record_audit_event
from app.services.evidence_snapshot import take_capability_grant_snapshot
from app.services.freshness import dataset_case_set_fingerprint
from app.services.system_actor import get_system_actor_id as _get_system_actor_id

logger = logging.getLogger(__name__)


async def process_evaluation_job(evaluation_run_reference_id: uuid.UUID, agent_eval_client: AgentEvalClient) -> None:
    async with SessionLocal() as db:
        # Atomic claim: only one worker (of possibly several concurrent deliveries -
        # Cloud Tasks is at-least-once) actually proceeds. Zero rows updated means
        # this reference was already claimed/completed/failed - a duplicate delivery,
        # handled as a silent no-op rather than reprocessing. See
        # docs/failure-modes.md's "evaluation task retried" / "duplicate callback".
        claim = await db.execute(
            update(EvaluationRunReference)
            .where(
                EvaluationRunReference.id == evaluation_run_reference_id,
                EvaluationRunReference.status == EvaluationRunStatus.REQUESTED,
            )
            .values(status=EvaluationRunStatus.DISPATCHED)
            .returning(EvaluationRunReference.id)
        )
        claimed = claim.scalar_one_or_none()
        await db.commit()
        if claimed is None:
            logger.info(
                "evaluation job already claimed or terminal - skipping duplicate delivery",
                extra={"evaluation_run_reference_id": str(evaluation_run_reference_id)},
            )
            return

    async with SessionLocal() as db:
        reference = (
            await db.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == evaluation_run_reference_id))
        ).scalar_one()
        version = (await db.execute(select(AgentVersion).where(AgentVersion.id == reference.agent_version_id))).scalar_one()
        agent = (await db.execute(select(Agent).where(Agent.id == version.agent_id))).scalar_one()
        system_actor_id = await _get_system_actor_id(db)
        logger.info(
            "evaluation job dispatched, calling agent-eval",
            extra={
                "evaluation_run_reference_id": str(evaluation_run_reference_id),
                "agent_version_id": str(version.id),
                "agent_id": str(agent.id),
                "external_agent_version_id": reference.external_agent_version_id,
            },
        )

        submitted = reference.external_evaluator_ids or {}
        evaluator_ids = submitted.get("ids", [])
        submitted_versions = submitted.get("versions", {})

        _started = time.monotonic()
        try:
            run = await agent_eval_client.trigger_run(
                agent_version_id=reference.external_agent_version_id,
                dataset_id=reference.external_dataset_id,
                evaluator_ids=evaluator_ids,
                triggered_by=f"agent-dev-platform:{reference.id}",
                timeout_seconds=240.0,
            )
        except AgentEvalTimeoutError as exc:
            await _mark_failed(db, reference, agent, system_actor_id, f"timeout waiting for agent-eval: {exc}")
            return
        except AgentEvalUnavailableError as exc:
            await _mark_failed(db, reference, agent, system_actor_id, f"agent-eval unavailable: {exc}")
            return
        except AgentEvalMalformedResponseError as exc:
            await _mark_failed(db, reference, agent, system_actor_id, f"malformed agent-eval response: {exc}")
            return
        agent_eval_latency_ms = (time.monotonic() - _started) * 1000
        logger.info(
            "agent-eval call completed",
            extra={
                "evaluation_run_reference_id": str(evaluation_run_reference_id),
                "agent_eval_latency_ms": round(agent_eval_latency_ms, 1),
                "external_run_id": run.id,
            },
        )

        # From here on, the external run genuinely succeeded - any failure below is
        # the "DB write failure after external run completion" distributed-failure
        # boundary (docs/failure-modes.md), handled in the outer except block.
        try:
            await _persist_success(db, reference, agent, version, run, submitted_versions, agent_eval_client, system_actor_id)
        except Exception as exc:  # noqa: BLE001 - must not lose the external_run_id breadcrumb
            logger.exception("local persistence failed after agent-eval run %s completed successfully", run.id)
            await db.rollback()
            async with SessionLocal() as recovery_db:
                ref = (
                    await recovery_db.execute(
                        select(EvaluationRunReference).where(EvaluationRunReference.id == evaluation_run_reference_id)
                    )
                ).scalar_one()
                ref.status = EvaluationRunStatus.FAILED
                ref.external_run_id = run.id
                ref.error_message = (
                    f"external evaluation run {run.id} completed successfully in agent-eval, but local "
                    f"persistence failed ({exc}). The external result is NOT lost - re-fetch via "
                    f"GET /runs/{run.id} on agent-eval using external_run_id, or retry this evaluation "
                    f"request; do not assume the external run needs to be re-triggered."
                )
                recovery_actor_id = await _get_system_actor_id(recovery_db)
                record_audit_event(
                    recovery_db,
                    actor_id=recovery_actor_id,
                    event_type="evaluation.failed",
                    entity_type="evaluation_run_reference",
                    entity_id=ref.id,
                    payload={"reason": "local_persistence_failure_after_external_success", "external_run_id": run.id},
                )
                await recovery_db.commit()


async def _mark_failed(db, reference: EvaluationRunReference, agent: Agent, actor_id: uuid.UUID, message: str) -> None:
    reference.status = EvaluationRunStatus.FAILED
    reference.error_message = message
    reference.completed_at = datetime.now(timezone.utc)

    lifecycle = (
        await db.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == reference.agent_version_id))
    ).scalar_one()
    lifecycle.stage = Stage.DRAFT
    lifecycle.entered_by = actor_id
    lifecycle.entered_at = datetime.now(timezone.utc)

    record_audit_event(
        db,
        actor_id=actor_id,
        event_type="evaluation.failed",
        entity_type="evaluation_run_reference",
        entity_id=reference.id,
        payload={"reason": message},
    )
    await db.commit()
    logger.warning(
        "evaluation job failed",
        extra={"evaluation_run_reference_id": str(reference.id), "agent_id": str(agent.id), "reason": message},
    )


async def _persist_success(
    db, reference, agent, version, run, submitted_versions, agent_eval_client: AgentEvalClient, actor_id: uuid.UUID
) -> None:
    n_success = sum(1 for c in run.case_runs if c.status == "success")
    n_error = sum(1 for c in run.case_runs if c.status != "success")

    completion_snapshot = await take_capability_grant_snapshot(db, reference.agent_version_id)

    dataset = await agent_eval_client.get_dataset(run.dataset_id)
    fingerprint = dataset_case_set_fingerprint([{"key": c.key, "tags": c.tags} for c in (dataset.cases or [])])

    baseline_comparison: ComparisonResult | None = await _resolve_baseline_comparison(db, agent, run, agent_eval_client)

    tag_case_failure_counts: dict[str, int] = {}
    from app.services.evaluation_policies import get_evaluation_policy

    policy = await get_evaluation_policy(db, reference.evaluation_policy_id)
    for tag in policy.zero_failure_tags:
        tagged_run = await agent_eval_client.get_run(run.id, tag=tag)
        tag_case_failure_counts[tag] = sum(1 for c in tagged_run.case_runs if c.status != "success")

    computed = gates_service.compute_gates(
        gates_service.GateComputationInput(
            run=run,
            policy=policy,
            submitted_evaluator_versions=submitted_versions,
            capability_snapshot_hash_at_request=reference.capability_grant_snapshot_hash,
            capability_snapshot_hash_at_completion=completion_snapshot.hash,
            baseline_comparison=baseline_comparison,
            tag_case_failure_counts=tag_case_failure_counts,
        )
    )
    await gates_service.persist_gate_results(
        db, evaluation_run_reference_id=reference.id, evaluation_policy_id=policy.id, computed=computed
    )
    all_passed = all(g.passed for g in computed)

    reference.status = EvaluationRunStatus.COMPLETED
    reference.external_run_id = run.id
    reference.dataset_snapshot_hash = run.dataset_snapshot_hash
    reference.dataset_case_set_fingerprint = fingerprint
    reference.evaluator_versions = submitted_versions
    reference.dimension_stats = [
        {"dimension": s.dimension, "mean_score": s.mean_score, "n": s.n, "n_not_applicable": s.n_not_applicable}
        for s in run.dimension_stats
    ]
    reference.n_cases_total = len(run.case_runs)
    reference.n_cases_success = n_success
    reference.n_cases_error = n_error
    reference.completed_at = datetime.now(timezone.utc)
    reference.fetched_at = datetime.now(timezone.utc)

    lifecycle = (
        await db.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == reference.agent_version_id))
    ).scalar_one()
    lifecycle.stage = Stage.CANDIDATE if all_passed else Stage.DRAFT
    lifecycle.entered_by = actor_id
    lifecycle.entered_at = datetime.now(timezone.utc)

    record_audit_event(
        db,
        actor_id=actor_id,
        event_type="evaluation.completed",
        entity_type="evaluation_run_reference",
        entity_id=reference.id,
        payload={"external_run_id": run.id, "all_gates_passed": all_passed, "n_gates": len(computed)},
    )
    if all_passed:
        record_audit_event(
            db,
            actor_id=actor_id,
            event_type="agent_version.became_candidate",
            entity_type="agent_version",
            entity_id=reference.agent_version_id,
            payload={"evaluation_run_reference_id": str(reference.id)},
        )

    await db.commit()
    logger.info(
        "evaluation job completed",
        extra={
            "evaluation_run_reference_id": str(reference.id),
            "agent_id": str(agent.id),
            "agent_version_id": str(reference.agent_version_id),
            "external_run_id": run.id,
            "all_gates_passed": all_passed,
            "n_gates": len(computed),
            "n_cases_success": n_success,
            "n_cases_error": n_error,
        },
    )


async def _resolve_baseline_comparison(db, agent: Agent, run, agent_eval_client: AgentEvalClient):
    """The current production version's most recent completed evaluation on the
    same dataset, if one exists - see app/services/gates.py's max_new_regressions
    gate. None means "nothing to regress against," which is a trivial pass, not an
    error.
    """
    prod_lifecycle = (
        await db.execute(
            select(AgentVersionLifecycle)
            .join(AgentVersion, AgentVersion.id == AgentVersionLifecycle.agent_version_id)
            .where(AgentVersion.agent_id == agent.id, AgentVersionLifecycle.stage == Stage.PRODUCTION)
        )
    ).scalar_one_or_none()
    if prod_lifecycle is None:
        return None

    baseline_ref = (
        await db.execute(
            select(EvaluationRunReference)
            .where(
                EvaluationRunReference.agent_version_id == prod_lifecycle.agent_version_id,
                EvaluationRunReference.status == EvaluationRunStatus.COMPLETED,
                EvaluationRunReference.external_dataset_id == run.dataset_id,
            )
            .order_by(EvaluationRunReference.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if baseline_ref is None or not baseline_ref.external_run_id:
        return None

    return await agent_eval_client.compare_runs(baseline_ref.external_run_id, run.id)
