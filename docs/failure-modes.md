# Failure Modes

Designed behavior under partial failure, decided before implementation so the consistency guarantees aren't improvised under pressure later. **As of Phase 3, most of the evaluation-related modes below are implemented and test/live-verified, not just designed** - each section says which.

## Agent Evaluation Platform is unavailable

**Implemented and test-verified** (`tests/test_evaluation_worker.py::test_agent_eval_unavailable_marks_failed_and_reverts_to_draft`), and **live-verified against the real deployed system in Phase 6**: an evaluation targeting a nonexistent `external_agent_version_id` produced a real `400` from the deployed `agent-eval-api`; the worker correctly recorded `status='failed'` with the real upstream error message, reverted the version's stage `evaluating → draft`, and an `evaluation.failed` audit event fired. A Builder can immediately request a fresh evaluation (draft is a requestable stage). Retry is not automatic at the application level (`LocalSyncDispatcher` has no retry logic, and the worker itself doesn't re-attempt a failed `agent-eval` call) - but the real `CloudTasksDispatcher`'s delivery layer does retry on a transport-level failure (5xx from the receiver), per Cloud Tasks' own queue retry policy (`evaluation-jobs`: up to 100 attempts, exponential backoff). Critically, a legitimate application-level evaluation failure like this one does **not** trigger that retry - the push endpoint still returns `204` on a handled failure, so Cloud Tasks correctly treats the task as delivered, not as needing another attempt. See `docs/phase-notes/phase-6.md`'s "Cloud Tasks" section for the full live-verification detail.

## An evaluation run times out

**Implemented and test-verified** (`test_agent_eval_timeout_marks_failed_distinctly`). `HttpAgentEvalClient` wraps `httpx.TimeoutException` as a distinct `AgentEvalTimeoutError`, handled identically to unavailability (`status='failed'`, stage reverts to `draft`, audit event fires) but with a distinguishable error message ("timeout" appears in `error_message`) so an operator can tell "agent-eval never responded" apart from "agent-eval responded with a real error." Because `agent-eval`'s `POST /runs` has no cancellation, a timed-out call may still complete server-side after this platform gives up waiting - the worker never revisits a `'failed'` reference on a late response; a fresh evaluation request creates a new, authoritative reference.

## A malformed Agent Eval response

**Implemented and test-verified** (`test_malformed_agent_eval_response_marks_failed`). `HttpAgentEvalClient` validates every response against the exact real schema (`app/integrations/agent_eval_client.py`'s dataclasses, built from live inspection of `agent-eval`'s `/openapi.json`) and raises `AgentEvalMalformedResponseError` on any mismatch - a missing key, wrong type, or non-2xx/non-JSON body. Handled identically to unavailability/timeout: `status='failed'`, stage reverts, audited.

## An evaluation finishes after its policy changed

**Implemented and test-verified** (`test_policy_change_mid_run_does_not_affect_the_in_flight_evaluation`). Gates for a given run are always computed against the `EvaluationPolicy` **pinned on the `EvaluationRunReference` at request time** (`evaluation_policy_id`), never re-resolved mid-flight - a new policy version published while a run is executing has zero effect on that run's gate computation. Live-verified with real data during Phase 3: `incident-investigator`'s `v1` policy required an evaluator that produced no applicable score; `v2` (published afterward) corrected this, and a *new* evaluation request against `v2` graded cleanly - `v1`'s already-computed gate results were never touched. `policy_changed` becomes relevant only later, as a **freshness** finding (see [`evaluation-and-promotion.md`](evaluation-and-promotion.md#evidence-freshness)) checked live whenever candidacy is queried, not at gate-computation time.

## A dataset changed after the evaluation

**Implemented, with a real, named precision limit** (`app/services/freshness.py::check_freshness`, the `dataset_changed` finding). Re-fetches `agent-eval`'s current dataset case set (`GET /datasets/{id}`) and compares a locally-computed structural fingerprint (case `key`/`tags` only) against the one recorded at evaluation time. Catches cases added/removed/renamed/re-tagged; **cannot** detect a case's `input`/`expected` content changing while its key stays the same, because `agent-eval`'s real API never exposes that content outside of `RunSummaryResponse` - reconstructing it client-side would mean reimplementing agent-eval's own dataset-hashing logic, explicitly out of scope. See [`evaluation-and-promotion.md`](evaluation-and-promotion.md#the-dataset-fingerprint-limitation) for the full, honest accounting of this gap.

## Evaluator versions changed

**Implemented and test-verified** (`test_evaluator_version_change_makes_it_stale`, `test_missing_required_evaluator_makes_it_stale`). `check_freshness` re-fetches `GET /evaluators` live and compares each policy-required evaluator's current version against what was recorded on the passing run. A version bump or an evaluator's outright removal from the catalog both surface as distinct, explicit stale reasons (`evaluator_version_changed` / `missing_required_evaluator`) - never a generic "stale" boolean.

## MCP server is unhealthy

`MCPServer.health_status` reflects the last Cloud Scheduler check; an unhealthy server does not retroactively invalidate existing `AgentCapabilityGrant`s or block new ones (a deliberate MVP choice - availability and authorization are different questions, see [`mcp-governance.md`](mcp-governance.md)). It is surfaced prominently in the UI (dashboard "unhealthy MCP integrations" widget) so humans can act. Revisit whether unhealthy servers should block *new* grants in [`open-questions.md`](open-questions.md).

## A capability is revoked after an AgentVersion was created

Expected and designed for, not an edge case - see [`mcp-governance.md`](mcp-governance.md) and [ADR-0004](adrs/0004-mcp-capability-grant-model.md). The `AgentVersion.manifest`'s `mcp.tools[]` stays unchanged (frozen declaration of intent, for reproducibility/audit); the `AgentCapabilityGrant` row gets `revoked_by`/`revoked_at` set. A `capability.revoked` audit event fires. Any execution plane calling into this platform's data is expected to check live grants, not the manifest, before allowing a call - documented explicitly as a integration requirement for execution planes.

## Capability grants changed while evaluation was running

**Implemented and live-verified with real data** (`test_capability_grants_changed_mid_run_fails_the_snapshot_consistency_gate`, and Phase 3's live stale/blocked demo - see `docs/phase-notes/phase-3.md`). Two distinct mechanisms cover two distinct timings:

- **Mid-run** (a grant changes between evaluation request and completion): the worker takes a fresh capability-grant snapshot right after `agent-eval` responds and compares its hash to the one taken at request time. A mismatch fails the `capability_snapshot_consistency` gate outright - the version reverts to `draft` even though the evaluation itself may have otherwise passed cleanly.
- **After a passing evaluation** (a grant changes later, once the version is already `candidate`): live-verified for real - revoking a real `AgentCapabilityGrant` on a version that had just become `candidate` left the historical evaluation and its gate results completely unchanged (`historically_passed: true`), while `GET .../candidacy` immediately reported `currently_eligible: false` with an explicit `capability_grants_changed` stale finding naming the before/after hash. This is the exact "evaluation passed at the time vs. evidence is still valid now" distinction the platform exists to make legible.

## Evaluation task retried / duplicate callback or result processing

**Implemented and test-verified** (`test_duplicate_dispatch_is_a_safe_no_op`). `process_evaluation_job` atomically claims its `EvaluationRunReference` via a conditional `UPDATE ... WHERE status = 'requested' RETURNING id` before doing any work; a second delivery of the same job (Cloud Tasks is at-least-once by design, and `LocalSyncDispatcher`'s fire-and-forget path has no delivery guarantee either) finds zero rows to claim and returns immediately as a no-op - no second submission to `agent-eval`, no double lifecycle transition. On the request side, `EvaluationRunReference.idempotency_key` (unique when set) lets a client-retried "request evaluation" HTTP call return the already-created reference instead of creating a duplicate and triggering a second run.

## Policy changed while evaluation was running

See "An evaluation finishes after its policy changed" above - the gate-computation policy is pinned at request time, so a mid-run policy change has no effect on that run.

## Dataset/evaluator mismatch

Caught at **request time**, before any call to `agent-eval` - `app/services/evaluations.py::request_evaluation` resolves the policy's `dataset_key` and `required_evaluator_keys` against `agent-eval`'s live catalog and returns `422` if the required dataset doesn't exist or a required evaluator's live version doesn't match the policy's pinned requirement. Test-verified (`test_request_evaluation_with_missing_dataset_is_422`, `test_request_evaluation_with_wrong_evaluator_version_is_422`) - no wasted multi-minute `agent-eval` call is ever made for a request that can't possibly gate cleanly.

## Partial gate-computation failure

Gate computation is **atomic, not partial** - `app/services/gates.py::compute_gates` is a single pure function; if it (or anything else in `_persist_success`) raises for any reason, the entire evaluation is treated as failed via the same distributed-failure-boundary handling described next, never as a half-computed set of gate rows. There is no code path that persists some gates and silently drops others.

## DB write failure after external run completion

**Implemented and test-verified** (`test_db_write_failure_after_external_success_preserves_external_run_id`) - the sharpest distributed-failure boundary in this system: `agent-eval` genuinely ran and returned a result, but something fails while persisting it locally (a DB error, a bug in gate computation, anything inside `_persist_success`). The worker catches this specifically, rolls back the partial local transaction, and in a **separate** transaction marks the reference `'failed'` while explicitly preserving `external_run_id` and writing an `error_message` that names the exact reconciliation path: re-fetch the result from `agent-eval` via `GET /runs/{external_run_id}`, or simply retry the evaluation request - never silently treating the external run as if it never happened. An `evaluation.failed` audit event is still recorded. This is the one failure mode in this system where "the external call succeeded" and "the local record shows failure" are both simultaneously true by design, and the reference row itself carries the breadcrumb needed to reconcile that gap - not just documentation asserting it's handled.

## Two reviewers attempt conflicting promotion decisions

**Implemented and test-verified** (`app/services/promotions.py::approve_promotion`/`reject_promotion`, `tests/test_promotions.py::test_approve_promotion_already_decided_is_conflict`). Rather than a bare conditional `UPDATE` (the Phase 3-era design intent this section originally described), the actual mechanism is a `pg_advisory_xact_lock(hashtext(agent_id))` taken before re-reading `PromotionRequest.status` - see [`evaluation-and-promotion.md`](evaluation-and-promotion.md#concurrency-an-advisory-lock-not-serializable) for why an agent-scoped advisory lock, not a row-level conditional update, is the actual primitive (one decision can touch two `AgentVersionLifecycle` rows). Whichever decision acquires the lock first proceeds; the second re-reads `status` under the lock, sees it's no longer `pending`, and the API returns a `409` conflict ("already been decided") rather than silently overwriting or double-applying the production transition.

## Two versions attempt to become production concurrently

**Implemented and live-verified against the real DB constraint** (`tests/test_promotions.py::test_concurrent_approvals_for_same_agent_only_one_ends_in_production` - two genuinely concurrent `approve_promotion` calls, separate sessions/connections, for two different candidates of the same `Agent`). `UNIQUE (agent_id) WHERE stage = 'production'` partial index on `AgentVersionLifecycle` remains the final DB-level backstop; the advisory lock above is the primary serialization mechanism, not `SERIALIZABLE` isolation (see [ADR-0007](adrs/0007-promotion-state-machine.md)'s Phase 4 update for why). Building this surfaced a real bug: retiring the previous production row and promoting the new one must be two separately-flushed statements, in that order, inside the one transaction - batching or reordering them can transiently violate the partial unique index even though the final state is valid, because Postgres checks it immediately per row, not deferred to transaction end.

## Evidence goes stale between promotion request and decision

**Implemented and live-verified against a real deployed target** (`tests/test_promotions.py::test_approve_promotion_blocked_by_stale_evidence_no_production_mutation`; `docs/phase-notes/phase-4.md`'s live demo 6 - a real capability granted on a real candidate version after a real `PromotionRequest` was filed against the real `ai-ops-center-eb26` dev DB). `check_freshness` is recomputed live a second time, immediately before the decision (`docs/adrs/0018-promotion-request-immutability.md`) - if it's no longer `currently_eligible`, approval is blocked (`409`, `promotion.approval_blocked_stale` audit event) with **zero** lifecycle mutation: the `AgentVersionLifecycle` row is never touched, `PromotionRequest.status` stays `pending`. Rejection is never blocked this way - a Reviewer may reject a still-pending request for any reason, staleness or otherwise.

## A rejected or superseded promotion request needs a do-over

**Implemented and test-verified** (`tests/test_promotions.py::test_reject_promotion_leaves_candidate_in_candidate`). A rejected `PromotionRequest`'s `AgentVersion` stays `candidate` - no `candidate -> draft` edge exists in the state machine ([ADR-0007](adrs/0007-promotion-state-machine.md)). A Builder may file a fresh `PromotionRequest` against the same version once the rejected one is no longer `pending` - the partial unique index (`UNIQUE (agent_version_id) WHERE status='pending'`, migration `0014`) only blocks a *second concurrently-pending* request, not a resubmission.

## An audit event cannot be persisted

Cannot happen independently of the state change it describes - `AuditEvent` rows are written in the **same transaction** as the change (see [`audit-model.md`](audit-model.md)). If the audit insert fails, the whole transaction (including the state change) rolls back. **Proven for Phase 3 writes specifically**, not just asserted by analogy to Phase 1/2: `tests/test_phase3_audit.py::test_evaluation_policy_creation_rolls_back_if_audit_fails` monkeypatches audit recording to raise mid-transaction and confirms the `EvaluationPolicy` row does not exist afterward - the same technique Phase 2 used to prove this for `Agent` creation. The one deliberate exception to "no separate audit write path" is the worker's DB-write-failure-after-external-success recovery path (above), which necessarily uses a **second** transaction (the first already rolled back) specifically to record that a distinct failure occurred - documented there, not a silent violation of this guarantee.

## Consistency guarantees summary

| Guarantee | Mechanism | Status |
|---|---|---|
| At most one production version per Agent | DB partial unique index (on `AgentVersionLifecycle`) + `pg_advisory_xact_lock` per Agent | Implemented and live-verified (real two-session concurrency proof), Phase 4 |
| Audit record always exists for a persisted state change | Same-transaction write, no separate audit write path | Implemented and proven for Phase 1-3 writes |
| No lost/overwritten promotion decisions | `pg_advisory_xact_lock` per Agent, re-check `status='pending'` under the lock | Implemented and test-verified, Phase 4 |
| Manifest never silently diverges from what was recorded | `AgentVersion` has no `UPDATE` grant at all - unconditional, not column-scoped | Implemented since Phase 1 |
| Stage transitions never touch version content | `stage` lives on a separate table (`AgentVersionLifecycle`), never on `AgentVersion` | Implemented since Phase 1 |
| Policy never silently diverges from what gated a run | `EvaluationPolicy` has no `UPDATE`/`DELETE` grant at all | Implemented since Phase 3, [ADR-0015](adrs/0015-evaluation-policy-immutability.md) |
| A completed run is never double-processed | Atomic conditional claim (`status='requested' → 'dispatched'`) before any work begins | Implemented and test-verified, Phase 3 |
| An external agent-eval success is never silently lost | `external_run_id` preserved even when local persistence fails afterward | Implemented and test-verified, Phase 3 |
| "Passed at the time" and "valid for promotion now" are never conflated | `EvaluationGateResult.passed` is permanent; `check_freshness` recomputes eligibility live, every call | Implemented and live-verified against real data, Phase 3 |
| "Eligible when requested" and "eligible when reviewed" are never conflated | Independent, frozen `freshness_snapshot` (request) and `freshness_snapshot_at_decision` (decision) | Implemented and live-verified against real data, Phase 4 |
| A promotion is never partially applied | Retire-then-promote as two flushes in one transaction; commit is all-or-nothing | Implemented, and the specific ordering was proven necessary by a real constraint violation caught in testing, Phase 4 |
| A promotion-lifecycle event is never published before its transaction commits | Transactional outbox (`OutboxEvent`), publish strictly after `commit()` | Implemented and live-verified (real Pub/Sub publish + real delivery), Phase 4, [ADR-0020](adrs/0020-promotion-lifecycle-event-outbox.md) |
