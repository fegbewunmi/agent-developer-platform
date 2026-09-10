# 0015. EvaluationPolicy is fully immutable, matching AgentVersion and SkillVersion

Status: Accepted

## Context

Phase 3's brief asked explicitly: "Decide during implementation whether policies themselves need immutable versions or whether every policy edit creates a new policy record. Favor reproducibility." Phase 0's original schema already gave `EvaluationPolicy` a `UNIQUE (name, version)` constraint suggesting versioning was intended, but never enforced immutability at the database level the way `AgentVersion` and `SkillVersion` do (ADR-0002).

The reproducibility stakes are concrete: `EvaluationGateResult` rows reference `evaluation_policy_id`, and a `PromotionRequest` (Phase 4) will cite an `EvaluationGateResult` as its evidence. If a policy's `thresholds`/`required_evaluator_keys` could be edited in place after gates were computed against it, the historical gate results would silently describe criteria that no longer exist - "why did this pass" would become unanswerable from stored data alone, exactly the failure mode ADR-0002 already ruled out for `AgentVersion`.

## Decision

`EvaluationPolicy` is fully immutable at the database level - `UPDATE`/`DELETE` revoked for `agent_platform_app` (migration `0011_evaluation_policy_immutability.py`), identical in mechanism to `AgentVersion` and `SkillVersion`. "Editing" a policy means publishing a new `(name, version)` row (`app/services/evaluation_policies.py::create_evaluation_policy`); there is no `PATCH` endpoint. `app/services/evaluation_policies.py::get_current_policy_for_agent` resolves "the current policy for this agent" as the newest `(name, version)` row where `name` matches the agent's name - a live-resolved pointer, not a fixed reference, so gates computed at any given moment are always graded against whichever policy is current *then*, while the exact policy actually used for a specific evaluation is permanently recorded via `EvaluationGateResult.evaluation_policy_id`.

## Alternatives considered

- **Mutable policy with a separate audit log of changes.** Rejected - this is the same "mutable object plus a change log" pattern ADR-0002 already rejected for `AgentVersion`, for the same reason: it makes "what did this gate actually require" a derived, reconstructable fact instead of a directly stored one.
- **Policy versioning without DB-level enforcement** (API just doesn't expose an edit endpoint). Rejected for the same reason ADR-0002 rejected it for `AgentVersion`: a future migration script or admin tool could still mutate a policy in place, silently invalidating every gate result that cited it.

## Consequences

Live-verified during Phase 3: `incident-investigator`'s first real evaluation policy (`v1`) required `final_output_contains_keywords`, which turned out to produce no applicable score for the real dataset's case shape - a genuine, evidence-based finding, not a bug. Because the policy was immutable, "fixing" it meant publishing `v2` with a corrected `required_evaluator_keys`/`thresholds` set, not editing `v1` in place - and `v1`'s now-superseded gate results remain exactly as they were computed, a permanent, honest record of what actually happened on that first attempt. This is the immutability guarantee working as intended, observed in a real run, not just reasoned about abstractly.
