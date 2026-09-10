# 0014. Capability grant reproducibility: manifest vs. authorization, and deferring an evaluation-time grant snapshot

Status: Accepted

## Context

ADR-0004 already decided that `AgentCapabilityGrant` is mutable and revocable, deliberately separate from the immutable manifest. Phase 2 implementation forced a sharper question ADR-0004 left implicit: once a grant *can* be revoked independently of the version it was granted to, what exactly does "reproduce this version" mean, and does anything downstream (specifically, a future evaluation run) need to know what was actually authorized at the moment it ran? This ADR answers that precisely rather than letting it stay implicit.

## The three questions, answered

**1. If an `AgentVersion` was evaluated with a capability that is later revoked, what does its historical manifest show?**

Exactly what it always showed: `manifest.mcp.tools[]` is a frozen declaration of intent, written once at version creation, and revocation never touches it (`AgentVersion` has no `UPDATE` grant at all - ADR-0002). A manifest read a year after a grant was revoked looks byte-identical to one read the day the version was created. The manifest was never a live authorization record and revocation doesn't change that.

**2. What does "reproduce this version" mean when current authorization differs from historical authorization?**

Two different, both legitimate, meanings - and this platform answers only one of them directly:

- *Reproduce the build*: model, prompt reference, skill pins, declared tool list. Fully answered by `AgentVersion.manifest` alone, unconditionally, forever. This is what "immutable version" has always meant in this platform's design (`docs/agent-versioning.md`).
- *Reproduce the authorized runtime behavior at a specific past moment*: what the version was actually allowed to call at time T. **Not** answered by the manifest. Answered by querying `AgentCapabilityGrant` rows where `granted_at <= T AND (revoked_at IS NULL OR revoked_at > T)` - a point-in-time reconstruction that's possible today because `granted_at`/`revoked_at` are real, permanent columns, never overwritten (see the API's `include_revoked=true` history view, `app/services/capability_grants.py::list_grants`).

These are not the same question, and a system that only exposes the first while implying it answers the second would be misleading. This platform exposes both, separately, and never conflates them.

**3. Should evaluations record a capability-grant snapshot/hash?**

**Yes, in Phase 3 - not built now, and not silently skipped either.** `EvaluationRunReference` already has an established pattern for exactly this problem: `dataset_snapshot_hash` and `evaluator_versions` exist specifically because "what was true when this ran" needs to survive the underlying thing changing later (`docs/evaluation-and-promotion.md`). The same reasoning applies to capability grants: point-in-time reconstruction via `granted_at`/`revoked_at` timestamps *works*, but it's indirect - it requires trusting audit/grant timestamps weren't tampered with (they can't be, per the immutability guarantees, but proving that requires a join and an argument, not a single stored field) and it requires knowing *when* to ask. A `capability_grant_snapshot_hash` field on `EvaluationRunReference` (a hash over the sorted set of active grant IDs for the `AgentVersion` at evaluation-request time), mirroring `dataset_snapshot_hash` exactly, would make "what was this evaluated with" a single stored fact instead of a derived query - consistent with why the other two snapshot fields exist.

## Decision

1. The manifest/authorization split from ADR-0004 stands, unchanged.
2. This platform explicitly supports both reproducibility questions above, through two different mechanisms (`AgentVersion.manifest` for the build; `AgentCapabilityGrant` timestamp history for point-in-time authorization), and documentation (this ADR, `docs/mcp-governance.md`) states which question each mechanism answers, so neither is mistaken for the other.
3. `EvaluationRunReference.capability_grant_snapshot_hash` is recommended for Phase 3, following the `dataset_snapshot_hash` pattern, and is tracked as a named Phase 3 requirement (`docs/roadmap.md`, `docs/open-questions.md`) rather than assumed or silently deferred without a trace.

## Alternatives considered

- **Make `AgentCapabilityGrant` immutable too** (revoking creates a new `AgentVersion`). Rejected - this was already rejected in ADR-0004 for good reason: it would force a full rebuild for a pure access change, conflating "what this version is" with "what it's currently allowed to do."
- **Duplicate grant state onto the manifest at evaluation time** (write the current grant set into a mutable field on the run reference without hashing it). Rejected as exactly the "silently solve it with duplicated mutable state" the brief warns against - a hash is a commitment to a specific set at a specific time; an unhashed copy invites silent drift and doesn't prove anything wasn't edited after the fact.
- **Do nothing until Phase 3 needs it, with no ADR.** Rejected - the reproducibility tradeoff is real today, the moment grants became revocable in Phase 2, whether or not `EvaluationRunReference` exists yet. Writing this down now means Phase 3 inherits a decision, not a blank slate.

## Consequences

Anyone asking "was this AgentVersion evaluated with capability X" today must run the point-in-time query described in answer 2 - there is no shortcut yet. Phase 3's evaluation integration work should budget for `capability_grant_snapshot_hash` as a small, already-justified addition, not a new design question.
