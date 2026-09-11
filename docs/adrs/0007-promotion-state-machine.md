# 0007. Promotion state machine and single-production-version enforcement

Status: Accepted

## Context

The brief asks explicitly whether rollback is a promotion of an older immutable version or a special transition, and how "only one production version" is enforced. Neither `ai-operations` nor `agent-eval` has any lifecycle/stage concept to draw on - `ai-operations` has no environment promotion beyond a free-text `settings.environment` string, and `agent-eval` has no stage field on `AgentVersion` at all.

## Decision

Five stages: `draft → evaluating → candidate → production → retired`. `evaluating → candidate` is automatic (system-driven, all gates pass); `evaluating → draft` is automatic on gate failure. `candidate → production` requires a `PromotionRequest` + `PromotionDecision`. **Rollback is not a special transition** - it is an ordinary `PromotionRequest` targeting an old, already-`retired`, immutable `AgentVersion`, gated identically to any other promotion (see `docs/open-questions.md` #2 for whether freshness rules should relax here). Stage itself lives on a separate table, `AgentVersionLifecycle`, not on `AgentVersion` (see [ADR-0002](0002-immutable-versioned-artifacts.md)'s amendment) - single-production-version-per-`Agent` is enforced with a DB partial unique index on that table (`UNIQUE (agent_id) WHERE stage='production'`), with the promote-and-retire-previous operation executed inside one serializable transaction.

## Alternatives considered

- **Model rollback as a distinct `rollback` transition/entity.** Rejected - it would duplicate the entire approval/evidence/audit machinery `PromotionRequest` already provides, for no behavioral difference; a rollback target is already a real immutable `AgentVersion`, so promoting it is literally the same operation.
- **Enforce single-production-version in application code only (read-then-write check).** Rejected - vulnerable to the concurrent-promotion race explicitly listed as a failure mode to design for (`docs/failure-modes.md`); a DB constraint closes the race that application-level checking cannot.

## Consequences

Because rollback reuses the normal promotion path, an old version being promoted again goes through the same evidence-freshness gates as a new one - which is safer but may create real friction during an active incident (tracked as open question #2 rather than pre-resolved).

## Phase 4 update: what "one serializable transaction" turned out to mean, and rejection semantics

Built and live-verified in Phase 4 (`app/services/promotions.py`, `docs/phase-notes/phase-4.md`). Two things this ADR left implicit needed a real decision:

**Concurrency: an advisory lock, not Postgres `SERIALIZABLE` isolation.** The hazard here is a straightforward concurrent-UPDATE conflict (two decisions racing to set `AgentVersionLifecycle.stage='production'` for the same `Agent`), not a phantom-read/write-skew anomaly - so `SERIALIZABLE` (with its required client-side retry-on-serialization-failure handling) is more machinery than the actual risk needs. `approve_promotion`/`reject_promotion` instead take `pg_advisory_xact_lock(hashtext(agent_id))` at the start of the decision, before re-reading the request's status - a lock keyed on the *Agent*, not a row-level `SELECT ... FOR UPDATE` on any single `AgentVersionLifecycle` row, because one approval can touch **two** such rows (the newly-promoted version's and the previously-production version's, which may not exist yet when the lock must already be held). The partial unique index (`UNIQUE (agent_id) WHERE stage='production'`) remains the final DB-level backstop exactly as originally decided - proven live by a real two-session concurrency test (`tests/test_promotions.py::test_concurrent_approvals_for_same_agent_only_one_ends_in_production`) that runs two genuinely concurrent `approve_promotion` calls, in separate sessions/connections, for two different candidates of the same `Agent`.

That test caught a real bug during Phase 4: the "promote-and-retire-previous operation" is not safely expressible as one flush of both `UPDATE`s together. Postgres checks a partial unique index immediately per row, not deferred to statement/transaction end - so if the ORM batches "set the old production row to `retired`" and "set the new row to `production`" into one `executemany`, or applies them in the wrong order, the intermediate state (both rows `production` at once, even for a moment) violates the constraint even though the *final* state is valid. The fix: retire the old row and `flush()` that on its own, strictly before setting the new row to `production` and flushing that - two explicit statements in a fixed order, still inside the one transaction that commits (or rolls back) both together.

**Rejection: a rejected candidate stays `candidate`.** There is no `candidate -> draft` edge in this ADR's state diagram - the only ways out of `candidate` are `-> production` (approval) and `-> retired` (abandon, not built this phase - see `docs/phase-notes/phase-4.md`'s scope note). A `PromotionRequest.status` transitions to `rejected`; the cited `AgentVersion`'s lifecycle stage is untouched. A Builder may file a fresh `PromotionRequest` against the same still-`candidate` version once the rejected one is no longer `pending` (the partial unique index on `(agent_version_id) WHERE status='pending'`, migration `0014`, only blocks a *second concurrently-pending* request, not a resubmission after rejection).
