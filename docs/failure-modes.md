# Failure Modes

Designed behavior under partial failure, decided before implementation so the consistency guarantees aren't improvised under pressure later.

## Agent Evaluation Platform is unavailable

The Cloud Tasks worker's `POST /runs` call fails (connection error/5xx). `EvaluationRunReference` stays `status='requested'`; Cloud Tasks retries with exponential backoff (its built-in mechanism). UI shows "evaluation pending — Agent Evaluation Platform unreachable," not a false completion. No gate can pass without evidence, so any dependent `PromotionRequest` simply cannot be created yet — there's no separate "unavailable" state to design because absence of a completed reference already blocks promotion by construction.

## An evaluation run times out

The Cloud Tasks task has its own execution deadline. On timeout, `EvaluationRunReference.status = 'failed'` (reason: `timeout`), an `evaluation.completed` audit event is still recorded (with the failed status — the attempt itself is auditable), and the Builder can request a retry. Because `agent-eval`'s `POST /runs` has no built-in cancellation, a timed-out call may still complete server-side after the platform gives up waiting — the worker treats a late, unmatched response as informational only (logged, not applied), since a fresh `EvaluationRunReference` for a retry is the authoritative one going forward.

## An evaluation finishes after its policy changed

No special handling needed — gates are computed against whichever `EvaluationPolicy` is **current for the Agent at promotion-request time**, always, never at evaluation-run time (see [`evaluation-and-promotion.md`](evaluation-and-promotion.md)). A run that passed an old policy may fail against a new one; the request simply reports which criteria fail. The `EvaluationPolicy.id` actually used is recorded on the `PromotionRequest`, so this is always auditable after the fact even once the policy is superseded again.

## A dataset changed after the evaluation

Detected at promotion-request time by re-fetching `agent-eval`'s current dataset snapshot hash and comparing to the one recorded on `EvaluationRunReference.dataset_snapshot_hash`. Mismatch fails the `dataset_snapshot_current` gate explicitly — the UI names the exact criterion, not a generic "blocked" message. Builder must request a fresh run.

## Evaluator versions changed

Same mechanism: re-fetch `agent-eval`'s `GET /evaluators`, compare to `EvaluationRunReference.evaluator_versions`. Mismatch fails `evaluator_versions_match_policy`.

## MCP server is unhealthy

`MCPServer.health_status` reflects the last Cloud Scheduler check; an unhealthy server does not retroactively invalidate existing `AgentCapabilityGrant`s or block new ones (a deliberate MVP choice — availability and authorization are different questions, see [`mcp-governance.md`](mcp-governance.md)). It is surfaced prominently in the UI (dashboard "unhealthy MCP integrations" widget) so humans can act. Revisit whether unhealthy servers should block *new* grants in [`open-questions.md`](open-questions.md).

## A capability is revoked after an AgentVersion was created

Expected and designed for, not an edge case — see [`mcp-governance.md`](mcp-governance.md) and [ADR-0004](adrs/0004-mcp-capability-grant-model.md). The `AgentVersion.manifest`'s `mcp.tools[]` stays unchanged (frozen declaration of intent, for reproducibility/audit); the `AgentCapabilityGrant` row gets `revoked_by`/`revoked_at` set. A `capability.revoked` audit event fires. Any execution plane calling into this platform's data is expected to check live grants, not the manifest, before allowing a call — documented explicitly as a integration requirement for execution planes.

## A production promotion is requested using stale evidence

Blocked outright by the freshness checks above — `dataset_snapshot_current` and `evaluator_versions_match_policy` gates fail, and gates are hard blockers with no override in this MVP (see [ADR-0008](adrs/0008-automated-gates-vs-human-approval.md)). The `PromotionRequest` creation call itself returns `409` with the specific failed criteria; no pending/rejected request is even created for a gate failure caught at request time.

## Two reviewers attempt conflicting promotion decisions

`PromotionRequest.status` starts `pending`; a `PromotionDecision` write is a conditional update (`UPDATE promotion_requests SET status = ... WHERE id = ? AND status = 'pending'`). The second decision's conditional update affects zero rows; the API returns a conflict ("already decided by X at T") rather than silently overwriting. Both attempts are visible in the audit trail — the losing one recorded as a rejected write attempt, not silently dropped, so a reviewer can see there was contention.

## Two versions attempt to become production concurrently

Prevented at the database level: `UNIQUE (agent_id) WHERE stage = 'production'` partial index, and the promote-and-retire-previous operation runs inside one serializable transaction. The second concurrent transaction's insert/update violates the constraint or fails the serializable check and is rolled back and retried by the API layer against the now-current state — it will observe the first promotion already committed and correctly report "a version is already in production" rather than corrupting state.

## An audit event cannot be persisted

Cannot happen independently of the state change it describes — `AuditEvent` rows are written in the **same transaction** as the change (see [`audit-model.md`](audit-model.md)). If the audit insert fails, the whole transaction (including the state change) rolls back. There is no code path where a promotion succeeds but its audit record doesn't exist. Pub/Sub publication (best-effort, post-commit) can fail independently — that only affects downstream fan-out, never the source-of-truth audit table.

## Consistency guarantees summary

| Guarantee | Mechanism |
|---|---|
| At most one production version per Agent | DB partial unique index + serializable transaction |
| Audit record always exists for a persisted state change | Same-transaction write, no separate audit write path |
| No lost/overwritten promotion decisions | Conditional update on `status = 'pending'` |
| No promotion on stale evidence | Live re-check at request time, hard gate, no override |
| Manifest never silently diverges from what was recorded | DB-level immutability enforcement, no update path |
