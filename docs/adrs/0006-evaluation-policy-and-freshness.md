# 0006. Explicit evaluation policy/gate model with live freshness checks

Status: Accepted

## Context

Inspection of `agent-eval` confirmed it has **no policy or gate concept at all** - no `Policy`/`Gate`/`ThresholdSet` entity, thresholds exist only as opaque per-evaluator `config` JSONB, and `GET /runs/compare` is explicitly informational (its own docs describe the platform as producing "results instead of a pass/fail CI gate"). The brief explicitly requires promotion to operate on named, explicit criteria, not one opaque score. Freshness is a real problem, not hypothetical: `agent-eval`'s datasets are deliberately mutable (its ADR-0003) and evaluators are versioned but version-bumping is developer discipline, not enforced (its open question #7) - meaning a run's evidence can silently go stale relative to what a policy currently expects.

## Decision

`EvaluationPolicy` is a versioned, immutable-per-`(name, version)` entity (mirroring `agent-eval`'s own evaluator-versioning pattern) defining `required_evaluator_keys[]`, per-dimension `thresholds`, `zero_new_regressions`, and `dataset_key`. Gate evaluation produces one named `EvaluationGateResult` row per criterion - never a single pass/fail scalar. Freshness (dataset snapshot hash, evaluator versions) is re-checked **live against `agent-eval`'s current state at promotion-request time**, not frozen at evaluation-run time, and policy used is always the `Agent`'s *current* policy at request time, not whatever was current when the run executed.

## Alternatives considered

- **Freeze policy and freshness checks at evaluation-run time.** Rejected - a run could sit unused for days while its underlying dataset or evaluators drift; checking only at run time would let stale evidence justify a promotion requested much later.
- **A single computed "quality score."** Rejected outright by the brief; also loses the specific information ("which criterion failed") the UI needs to explain a blocked promotion.

## Consequences

Every promotion attempt does at least two extra live calls to `agent-eval` (current dataset hash, current evaluator catalog) before gates can be computed - an availability dependency documented in `docs/failure-modes.md`. In exchange, "why was this blocked" is always answerable with a specific criterion, not a guess.
