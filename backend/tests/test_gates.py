"""Unit tests for app/services/gates.py's pure _evaluate_gates - no DB, no mocks
beyond hand-built dataclasses. Proves each gate type is individually inspectable
(never a blended score) and computes correctly in isolation.
"""
import uuid
from decimal import Decimal

from app.integrations.agent_eval_client import (
    CaseComparisonEntry,
    CaseRunSummary,
    ComparisonResult,
    DimensionStat,
    RunSummary,
)
from app.models.evaluation import EvaluationPolicy
from app.services.gates import GateComputationInput, compute_gates


def _policy(**overrides) -> EvaluationPolicy:
    defaults = dict(
        id=uuid.uuid4(),
        name="incident-investigator",
        version="v1",
        thresholds={},
        required_evaluator_keys={},
        max_new_regressions=0,
        zero_failure_tags=[],
        min_completion_rate=Decimal("1.0"),
        dataset_key="incident-investigator-smoke-v1",
        created_by=uuid.uuid4(),
    )
    defaults.update(overrides)
    return EvaluationPolicy(**defaults)


def _run(dimension_stats=None, case_statuses=("success", "success")) -> RunSummary:
    return RunSummary(
        id=str(uuid.uuid4()),
        agent_version_id="ext-v1",
        dataset_id="ext-ds",
        dataset_snapshot_hash="hash1",
        status="completed",
        started_at=None,
        completed_at=None,
        triggered_by=None,
        dimension_stats=dimension_stats or [],
        case_runs=[
            CaseRunSummary(case_run_id=str(uuid.uuid4()), case_key=f"c{i}", status=s, latency_ms=1.0)
            for i, s in enumerate(case_statuses)
        ],
    )


def _base_input(**overrides) -> GateComputationInput:
    defaults = dict(
        run=_run(),
        policy=_policy(),
        submitted_evaluator_versions={},
        capability_snapshot_hash_at_request="hashA",
        capability_snapshot_hash_at_completion="hashA",
        baseline_comparison=None,
        tag_case_failure_counts={},
    )
    defaults.update(overrides)
    return GateComputationInput(**defaults)


def test_min_dimension_score_passes():
    policy = _policy(thresholds={"grounding": {"min_mean": 0.8}})
    run = _run(dimension_stats=[DimensionStat(dimension="grounding", mean_score=0.9, n=3, n_not_applicable=0)])
    gates = compute_gates(_base_input(run=run, policy=policy))
    gate = next(g for g in gates if g.gate_type == "min_dimension_score")
    assert gate.passed is True
    assert gate.criterion == "grounding >= 0.8"
    assert gate.actual == "0.9"


def test_min_dimension_score_fails_below_threshold():
    policy = _policy(thresholds={"grounding": {"min_mean": 0.95}})
    run = _run(dimension_stats=[DimensionStat(dimension="grounding", mean_score=0.9, n=3, n_not_applicable=0)])
    gates = compute_gates(_base_input(run=run, policy=policy))
    gate = next(g for g in gates if g.gate_type == "min_dimension_score")
    assert gate.passed is False
    assert "below the required" in gate.reason


def test_min_dimension_score_fails_when_no_applicable_score():
    policy = _policy(thresholds={"grounding": {"min_mean": 0.8}})
    run = _run(dimension_stats=[DimensionStat(dimension="grounding", mean_score=None, n=0, n_not_applicable=3)])
    gates = compute_gates(_base_input(run=run, policy=policy))
    gate = next(g for g in gates if g.gate_type == "min_dimension_score")
    assert gate.passed is False
    assert gate.actual == "n/a"


def test_multiple_dimensions_produce_independent_gates_no_blended_score():
    policy = _policy(thresholds={"grounding": {"min_mean": 0.5}, "latency": {"min_mean": 0.9}})
    run = _run(
        dimension_stats=[
            DimensionStat(dimension="grounding", mean_score=0.9, n=3, n_not_applicable=0),
            DimensionStat(dimension="latency", mean_score=0.3, n=3, n_not_applicable=0),
        ]
    )
    gates = compute_gates(_base_input(run=run, policy=policy))
    dim_gates = [g for g in gates if g.gate_type == "min_dimension_score"]
    assert len(dim_gates) == 2
    by_dim = {g.evidence_ref["dimension"]: g.passed for g in dim_gates}
    assert by_dim == {"grounding": True, "latency": False}


def test_required_evaluator_version_passes_when_submitted_matches():
    policy = _policy(required_evaluator_keys={"grounding_judge": "v2"})
    gates = compute_gates(_base_input(policy=policy, submitted_evaluator_versions={"grounding_judge": "v2"}))
    gate = next(g for g in gates if g.gate_type == "required_evaluator_version")
    assert gate.passed is True


def test_required_evaluator_version_fails_on_mismatch():
    policy = _policy(required_evaluator_keys={"grounding_judge": "v2"})
    gates = compute_gates(_base_input(policy=policy, submitted_evaluator_versions={"grounding_judge": "v1"}))
    gate = next(g for g in gates if g.gate_type == "required_evaluator_version")
    assert gate.passed is False
    assert "v1" in gate.actual


def test_required_evaluator_version_fails_when_not_submitted():
    policy = _policy(required_evaluator_keys={"grounding_judge": "v2"})
    gates = compute_gates(_base_input(policy=policy, submitted_evaluator_versions={}))
    gate = next(g for g in gates if g.gate_type == "required_evaluator_version")
    assert gate.passed is False
    assert gate.actual == "not submitted"


def test_min_completion_rate_passes_all_success():
    gates = compute_gates(_base_input(run=_run(case_statuses=("success", "success"))))
    gate = next(g for g in gates if g.gate_type == "min_completion_rate")
    assert gate.passed is True
    assert gate.actual == "1"


def test_min_completion_rate_fails_with_errors():
    policy = _policy(min_completion_rate=Decimal("1.0"))
    gates = compute_gates(_base_input(run=_run(case_statuses=("success", "error")), policy=policy))
    gate = next(g for g in gates if g.gate_type == "min_completion_rate")
    assert gate.passed is False


def test_min_completion_rate_relaxed_threshold_tolerates_one_failure():
    policy = _policy(min_completion_rate=Decimal("0.5"))
    gates = compute_gates(_base_input(run=_run(case_statuses=("success", "error")), policy=policy))
    gate = next(g for g in gates if g.gate_type == "min_completion_rate")
    assert gate.passed is True


def test_max_new_regressions_trivially_passes_with_no_baseline():
    gates = compute_gates(_base_input(baseline_comparison=None))
    gate = next(g for g in gates if g.gate_type == "max_new_regressions")
    assert gate.passed is True
    assert "no production baseline" in gate.reason


def test_max_new_regressions_passes_within_tolerance():
    policy = _policy(max_new_regressions=1)
    comparison = ComparisonResult(
        run_a_id="baseline", run_b_id="current", dataset_id="ds", dataset_drift_detected=False,
        evaluator_version_mismatches=[],
        dimension_stats=[],
        regressions=[
            CaseComparisonEntry(
                case_key="c1", dimension="task_correctness", run_a_score=1.0, run_a_passed=True,
                run_b_score=0.0, run_b_passed=False,
            )
        ],
        improvements=[],
    )
    gates = compute_gates(_base_input(policy=policy, baseline_comparison=comparison))
    gate = next(g for g in gates if g.gate_type == "max_new_regressions")
    assert gate.passed is True
    assert gate.actual == "1"


def test_max_new_regressions_fails_beyond_tolerance():
    policy = _policy(max_new_regressions=0)
    comparison = ComparisonResult(
        run_a_id="baseline", run_b_id="current", dataset_id="ds", dataset_drift_detected=False,
        evaluator_version_mismatches=[],
        dimension_stats=[],
        regressions=[
            CaseComparisonEntry(
                case_key="c1", dimension="task_correctness", run_a_score=1.0, run_a_passed=True,
                run_b_score=0.0, run_b_passed=False,
            )
        ],
        improvements=[],
    )
    gates = compute_gates(_base_input(policy=policy, baseline_comparison=comparison))
    gate = next(g for g in gates if g.gate_type == "max_new_regressions")
    assert gate.passed is False


def test_zero_failure_tags_no_configured_tags_means_no_gate_rows():
    gates = compute_gates(_base_input(policy=_policy(zero_failure_tags=[])))
    assert not any(g.gate_type == "zero_failures_for_tag" for g in gates)


def test_zero_failure_tags_passes_when_zero_failures():
    policy = _policy(zero_failure_tags=["critical"])
    gates = compute_gates(_base_input(policy=policy, tag_case_failure_counts={"critical": 0}))
    gate = next(g for g in gates if g.gate_type == "zero_failures_for_tag")
    assert gate.passed is True


def test_zero_failure_tags_fails_on_any_failure():
    policy = _policy(zero_failure_tags=["critical"])
    gates = compute_gates(_base_input(policy=policy, tag_case_failure_counts={"critical": 2}))
    gate = next(g for g in gates if g.gate_type == "zero_failures_for_tag")
    assert gate.passed is False
    assert gate.actual == "2"


def test_capability_snapshot_consistency_passes_when_unchanged():
    gates = compute_gates(
        _base_input(capability_snapshot_hash_at_request="X", capability_snapshot_hash_at_completion="X")
    )
    gate = next(g for g in gates if g.gate_type == "capability_snapshot_consistency")
    assert gate.passed is True


def test_capability_snapshot_consistency_fails_when_grants_changed_mid_run():
    gates = compute_gates(
        _base_input(capability_snapshot_hash_at_request="X", capability_snapshot_hash_at_completion="Y")
    )
    gate = next(g for g in gates if g.gate_type == "capability_snapshot_consistency")
    assert gate.passed is False
    assert "changed" in gate.reason


def test_all_gates_pass_is_computable_from_the_list_without_a_blended_score():
    """The 'is this a candidate' decision is `all(g.passed for g in gates)` at the
    call site (app/services/evaluation_worker.py) - never a stored/averaged score."""
    policy = _policy(thresholds={"grounding": {"min_mean": 0.5}})
    run = _run(dimension_stats=[DimensionStat(dimension="grounding", mean_score=0.9, n=1, n_not_applicable=0)])
    gates = compute_gates(_base_input(run=run, policy=policy))
    assert all(g.passed for g in gates)
