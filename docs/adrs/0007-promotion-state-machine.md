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
