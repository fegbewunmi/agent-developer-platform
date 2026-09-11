# 0018. PromotionRequest captures full decision context; immutable except status

Status: Accepted

## Context

Phase 1 gave `PromotionRequest` only `agent_version_id`, `from_stage`, `to_stage`, `requested_by`, an optional `evaluation_run_reference_id`, and `status` - enough to satisfy the no-self-approval trigger's foreign keys, but not enough to answer "why was this exact version in production right now?" without re-deriving intent from tables that keep changing underneath it (`EvaluationPolicy` gets superseded, `AgentCapabilityGrant`s get revoked, `AgentVersionLifecycle.stage` moves on). The Phase 4 brief is explicit that a `PromotionRequest` must not "merely store `agent_version_id` and assume the rest can always be reconstructed later."

Two closely related questions came up building the approval flow:

1. Should evidence freshness be checked once, at request time, and trusted from then on?
2. Should a request that goes stale between filing and review silently rerun evaluation, silently get invalidated, or just sit there?

## Decision

`PromotionRequest` is a frozen snapshot of everything needed to answer "was this a legitimate promotion, and what did the reviewer actually see" without re-querying mutable state: `evaluation_run_reference_id` and `evaluation_policy_id` (both now `NOT NULL` - migration `0014_promotion_request_snapshot.py`), `capability_grant_snapshot_hash`/`capability_grant_snapshot` (ADR-0014's fingerprint, taken fresh at request time, independent of whatever hash the cited evaluation run itself recorded), `production_version_id_at_request` (historical context only, never re-read as "current"), and `freshness_snapshot` (the full `check_freshness()` result at request time). `PromotionDecision` gets the analogous `freshness_snapshot_at_decision` - the *same* check, recomputed live immediately before the decision.

This makes freshness a two-times-recorded fact, not a one-time gate: **"eligible when requested"** (frozen on `PromotionRequest`, matches ADR-0006's existing request-time freshness check) and **"eligible when reviewed"** (frozen on `PromotionDecision`, a new, independent live recomputation - `app/services/promotions.py::approve_promotion`/`reject_promotion` never reuse the request's own snapshot as a shortcut). Approval is blocked outright if evidence is no longer eligible at decision time (`ConflictError`, `promotion.approval_blocked_stale` audit event, no lifecycle mutation) - answering question 2: **nothing is silently rerun or auto-invalidated**. A stale pending request just stays `pending` until a Reviewer explicitly rejects it or the evidence becomes eligible again (rare in practice, since capability-grant/policy changes that caused the drift are themselves deliberate actions, not usually reverted).

`PromotionRequest` is immutable at the DB level except `status` (column-level `GRANT UPDATE (status)`, migration `0015_promotion_immutability.py`, the same shape as `AgentVersion`/`SkillVersion`/`EvaluationPolicy`'s write-once pattern but adapted for the one column that genuinely must transition `pending -> approved/rejected`). `PromotionDecision` is fully immutable, like `AuditEvent` - a decision, once made, is never edited.

`PromotionRequestStatus` stays exactly the three values Phase 1 already needed for the trigger (`pending`, `approved`, `rejected`) plus the pre-existing, currently-unused `withdrawn` - no new status is added for "stale" or "invalidated." Staleness is intentionally *not* a stored status: it is a live-computed property (`currently_eligible`, same as `docs/evaluation-and-promotion.md`'s existing candidate-eligibility model), re-derived from current data every time it matters, never a field that itself needs to be kept in sync.

## Alternatives considered

- **Store only `agent_version_id` + `status`, re-derive everything else at read/decision time.** Rejected - exactly the case the brief calls out; "current policy for this agent" and "current capability grants" are moving targets, so a request reviewed a week after filing would silently be evaluated against evidence the requester never saw request-time approval for.
- **Add an `invalidated`/`stale` `PromotionRequestStatus`, set automatically when freshness drifts.** Rejected - would require either a background job re-checking every pending request (a new operational dependency for a control-plane platform that otherwise does nothing on a schedule) or a check-on-every-read pattern that duplicates `currently_eligible`'s live-computation with a persisted, eventually-inconsistent copy. Blocking *approval* live, without mutating `status`, gets the same safety guarantee with none of that machinery.
- **Auto-rerun evaluation when a pending request goes stale.** Rejected explicitly by the brief ("do not silently refresh or rerun evaluation as part of approval") - re-running is a `request_evaluation` action with its own authorization and audit trail; folding it into approval would hide a real, consequential side effect inside what looks like a review action.

## Consequences

A `PromotionRequest` row is larger and more redundant with other tables than a pure normalized foreign-key model would be - deliberate, since the whole point is that this redundancy is what makes the audit trail self-contained. Rejecting a request that went stale mid-review requires a human action; there is no automatic cleanup of stuck pending requests, which is acceptable because the partial unique index (`0014`) only blocks a *second* pending request for the same version, not indefinite pendency of the first.
