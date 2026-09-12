# 0025. SkillVersion review is a separate model, not a reuse of PromotionRequest/PromotionDecision

Status: Accepted

## Context

Phase 9's brief identified a real product gap: a `SkillVersion` had no "recommended" concept at all - no way for a developer to ask "which version of this skill should I actually use," and no review step gating that answer. The obvious first instinct was to reuse the already-proven `PromotionRequest`/`PromotionDecision` machinery (no-self-approval DB trigger, immutable decisions, one-recommended-per-parent partial unique index) rather than build something new.

Direct reuse doesn't work. `PromotionRequest` (`backend/app/models/promotion.py`) has hard, `NOT NULL` foreign keys into the AgentVersion evaluation-gate pipeline: `evaluation_run_reference_id` and `evaluation_policy_id`, both pointing at rows that only exist because an `AgentVersion` went through a real `agent-eval` run. A `SkillVersion` has no automated evaluator, no `agent-eval` integration, and no gate concept at all - there is no real evaluation run to reference. Forcing a `SkillReviewRequest` through `PromotionRequest` would require either:

1. Fabricating fake `EvaluationRunReference`/`EvaluationGateResult` rows with no real evaluation behind them, corrupting a system that's specifically designed so every gate result is a real, immutable fact about a real `agent-eval` run - the opposite of this project's "real, not simulated" discipline throughout every phase; or
2. Loosening `PromotionRequest`'s `NOT NULL` constraints to make evaluation evidence optional, weakening a guarantee that's currently hard and proven for every real Agent promotion in this system, for the sake of an unrelated entity.

Both are worse than building a second, smaller table.

## Decision

Two new tables, structurally parallel to `AgentVersionLifecycle`/`PromotionRequest`/`PromotionDecision` but independent of them:

- **`SkillVersionLifecycle`** (`skill_version_id`, `skill_id`, `stage`, `entered_at`, `entered_by`) - the same "stage vs. content split" `AgentVersion` already uses (`docs/agent-versioning.md#the-stage-vs-content-split`). `stage` is a new, narrower enum - `published` / `recommended` / `deprecated` - deliberately not a reuse of `Stage` (`draft`/`evaluating`/`evaluated` describe an automated-evaluation lifecycle a `SkillVersion` doesn't have). One `recommended` `SkillVersion` per `Skill`, enforced by the same kind of partial unique index (`UNIQUE (skill_id) WHERE stage='recommended'`).
- **`SkillReviewRequest`** / **`SkillReviewDecision`** - the same shape as `PromotionRequest`/`PromotionDecision` *minus* every evaluation-specific field: no `evaluation_run_reference_id`, no `evaluation_policy_id`, no freshness snapshots (there is no evidence to go stale). Just `skill_version_id`, `requested_by`/`requested_at`/`status`/`reason`, and `decision`/`decided_by`/`decided_at`/`comment`. The exact same no-self-approval guarantee is reused as a *second*, independent DB trigger (`fn_reject_self_approval_skill_review`, migration `0019_skill_review.py`) rather than generalizing one trigger across both tables - the two entities' columns genuinely differ, and a shared trigger would need to branch on which table fired it for no real benefit.

A `SkillVersion` is `published` immediately at creation (unchanged behavior). Becoming `recommended` requires an approved `SkillReviewRequest` from an independent Reviewer/Admin - never automatic, never something the publishing Builder can grant themselves.

## Alternatives considered

- **Reuse `PromotionRequest`/`PromotionDecision` directly**, making the evaluation-evidence columns nullable. Rejected - see Context above; this would weaken a hard, currently-proven guarantee on the Agent promotion path for the sake of an unrelated entity, and blur what a `PromotionRequest` *means* ("this cites real, passing evaluation evidence") for every future reader of that table, including every already-written historical row.
- **A single generic "ReviewRequest" polymorphic table** covering both AgentVersions and SkillVersions (a nullable `agent_version_id` and a nullable `skill_version_id`, exactly one populated). Rejected - this is the classic polymorphic-association anti-pattern: neither FK could be `NOT NULL`, the self-approval trigger would need to branch on which one is set, and every query needs an extra "which kind is this" check. Two small, single-purpose tables are simpler to read, migrate, and reason about than one table pretending to be both.
- **No review gate at all - any Builder-published SkillVersion becomes eligible for `recommended` automatically once some other condition is met** (e.g., first agent that pins it). Rejected - this contradicts the explicit product requirement ("a Builder can publish a skill version, but another authorized reviewer should recommend it for organizational reuse") and would make "recommended" mean nothing more than "somebody used it once."

## Consequences

Two independent review/lifecycle subsystems now exist side by side - one for Agents (evaluation-evidence-gated), one for Skills (human-review-only, no automated gate). This is intentional, not incidental duplication: the two entities have genuinely different evidence models, and conflating them would either weaken the Agent side or fabricate evidence on the Skill side. A reader encountering `SkillReviewRequest` should not expect it to behave exactly like `PromotionRequest` - notably, there is no freshness/staleness concept for skill reviews, because there is no evaluation evidence that could go stale. If Skills ever gain a real automated verification step (a "does this skill's implementation still match its contract" check, for example), revisit whether the two models should converge - they deliberately do not today.
