"""Gate computation - entirely this platform's responsibility
(docs/evaluation-and-promotion.md). Each policy criterion produces exactly one
EvaluationGateResult row; there is no blended score anywhere in this module.

_evaluate_gates is a pure function (no DB, no I/O) so gate logic is fully unit-testable
against hand-built inputs without mocking a database - see tests/test_gates.py.
compute_and_persist_gate_results is the thin DB-touching wrapper the worker calls.
"""
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.agent_eval_client import ComparisonResult, Evaluator, RunSummary
from app.models.evaluation import EvaluationGateResult, EvaluationPolicy


@dataclass(frozen=True)
class GateComputationInput:
    run: RunSummary
    policy: EvaluationPolicy
    submitted_evaluator_versions: dict[str, str]  # {evaluator_key: version} actually submitted
    capability_snapshot_hash_at_request: str
    capability_snapshot_hash_at_completion: str
    baseline_comparison: ComparisonResult | None  # None if no recommended baseline exists yet
    tag_case_failure_counts: dict[str, int] = field(default_factory=dict)  # {tag: n_failed_cases}


@dataclass(frozen=True)
class ComputedGate:
    gate_type: str
    criterion: str
    expected: str
    actual: str
    passed: bool
    reason: str
    evidence_ref: dict


def _dimension_stat(run: RunSummary, dimension: str):
    for stat in run.dimension_stats:
        if stat.dimension == dimension:
            return stat
    return None


def _evaluate_gates(inp: GateComputationInput) -> list[ComputedGate]:
    gates: list[ComputedGate] = []

    # 1. Per-dimension minimum score thresholds - never blended.
    for dimension, spec in inp.policy.thresholds.items():
        min_mean = spec.get("min_mean")
        if min_mean is None:
            continue
        stat = _dimension_stat(inp.run, dimension)
        if stat is None or stat.mean_score is None:
            gates.append(
                ComputedGate(
                    gate_type="min_dimension_score",
                    criterion=f"{dimension} >= {min_mean}",
                    expected=str(min_mean),
                    actual="n/a",
                    passed=False,
                    reason=f"dimension {dimension!r} produced no applicable score in this run "
                    f"(n_not_applicable={stat.n_not_applicable if stat else 'unknown'})",
                    evidence_ref={"dimension": dimension, "run_id": inp.run.id},
                )
            )
            continue
        passed = stat.mean_score >= min_mean
        gates.append(
            ComputedGate(
                gate_type="min_dimension_score",
                criterion=f"{dimension} >= {min_mean}",
                expected=str(min_mean),
                actual=str(stat.mean_score),
                passed=passed,
                reason="" if passed else f"mean score {stat.mean_score} is below the required {min_mean}",
                evidence_ref={"dimension": dimension, "run_id": inp.run.id, "n": stat.n},
            )
        )

    # 2. Required evaluator/version - confirms what was actually submitted matched
    # policy at submission time (a live drift check is freshness's job, not this gate's).
    for key, required_version in inp.policy.required_evaluator_keys.items():
        submitted_version = inp.submitted_evaluator_versions.get(key)
        if submitted_version is None:
            gates.append(
                ComputedGate(
                    gate_type="required_evaluator_version",
                    criterion=f"evaluator {key}@{required_version} used",
                    expected=required_version,
                    actual="not submitted",
                    passed=False,
                    reason=f"required evaluator {key!r} was not part of this run's submitted evaluator set",
                    evidence_ref={"evaluator_key": key},
                )
            )
            continue
        passed = submitted_version == required_version
        gates.append(
            ComputedGate(
                gate_type="required_evaluator_version",
                criterion=f"evaluator {key}@{required_version} used",
                expected=required_version,
                actual=submitted_version,
                passed=passed,
                reason="" if passed else f"submitted evaluator version {submitted_version} != required {required_version}",
                evidence_ref={"evaluator_key": key},
            )
        )

    # 3. Required completion status / minimum completion rate.
    total = len(inp.run.case_runs)
    n_success = sum(1 for c in inp.run.case_runs if c.status == "success")
    rate = Decimal(n_success) / Decimal(total) if total else Decimal("0")
    passed = rate >= inp.policy.min_completion_rate
    gates.append(
        ComputedGate(
            gate_type="min_completion_rate",
            criterion=f"completion rate >= {inp.policy.min_completion_rate}",
            expected=str(inp.policy.min_completion_rate),
            actual=str(rate),
            passed=passed,
            reason="" if passed else f"only {n_success}/{total} cases completed successfully",
            evidence_ref={"n_success": n_success, "n_total": total, "run_id": inp.run.id},
        )
    )

    # 4. Max new regressions vs. the current recommended baseline, if one exists.
    if inp.baseline_comparison is None:
        gates.append(
            ComputedGate(
                gate_type="max_new_regressions",
                criterion=f"new regressions <= {inp.policy.max_new_regressions}",
                expected=str(inp.policy.max_new_regressions),
                actual="n/a",
                passed=True,
                reason="no recommended baseline evaluation exists yet for this agent - "
                "nothing to regress against (docs/evaluation-and-promotion.md)",
                evidence_ref={},
            )
        )
    else:
        n_regressions = len(inp.baseline_comparison.regressions)
        passed = n_regressions <= inp.policy.max_new_regressions
        gates.append(
            ComputedGate(
                gate_type="max_new_regressions",
                criterion=f"new regressions <= {inp.policy.max_new_regressions}",
                expected=str(inp.policy.max_new_regressions),
                actual=str(n_regressions),
                passed=passed,
                reason="" if passed else f"{n_regressions} new regression(s) vs. the recommended baseline run",
                evidence_ref={
                    "baseline_run_id": inp.baseline_comparison.run_a_id,
                    "compared_run_id": inp.baseline_comparison.run_b_id,
                    "dataset_drift_detected": inp.baseline_comparison.dataset_drift_detected,
                },
            )
        )

    # 5. Zero failures for tagged cases.
    for tag in inp.policy.zero_failure_tags:
        n_failed = inp.tag_case_failure_counts.get(tag, 0)
        passed = n_failed == 0
        gates.append(
            ComputedGate(
                gate_type="zero_failures_for_tag",
                criterion=f"zero failures for tag {tag!r}",
                expected="0",
                actual=str(n_failed),
                passed=passed,
                reason="" if passed else f"{n_failed} case(s) tagged {tag!r} failed",
                evidence_ref={"tag": tag, "run_id": inp.run.id},
            )
        )

    # 6. Capability-grant snapshot consistency across the run's own duration - catches
    # "capability grants changed while evaluation was running" (docs/failure-modes.md).
    # This is NOT the ongoing freshness check (app/services/freshness.py handles that,
    # live, at any later point) - this only asks whether anything changed mid-flight.
    passed = inp.capability_snapshot_hash_at_request == inp.capability_snapshot_hash_at_completion
    gates.append(
        ComputedGate(
            gate_type="capability_snapshot_consistency",
            criterion="capability grants unchanged during the run",
            expected=inp.capability_snapshot_hash_at_request,
            actual=inp.capability_snapshot_hash_at_completion,
            passed=passed,
            reason="" if passed else "AgentCapabilityGrants changed between evaluation request and completion",
            evidence_ref={},
        )
    )

    return gates


def compute_gates(inp: GateComputationInput) -> list[ComputedGate]:
    return _evaluate_gates(inp)


async def persist_gate_results(
    db: AsyncSession,
    *,
    evaluation_run_reference_id: uuid.UUID,
    evaluation_policy_id: uuid.UUID,
    computed: list[ComputedGate],
) -> list[EvaluationGateResult]:
    rows = []
    for g in computed:
        row = EvaluationGateResult(
            id=uuid.uuid4(),
            evaluation_run_reference_id=evaluation_run_reference_id,
            evaluation_policy_id=evaluation_policy_id,
            gate_type=g.gate_type,
            criterion=g.criterion,
            expected=g.expected,
            actual=g.actual,
            passed=g.passed,
            reason=g.reason or None,
            evidence_ref=g.evidence_ref,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows
