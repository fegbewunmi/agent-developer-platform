# 0008. Automated gates are hard blockers; no override in MVP

Status: Accepted

## Context

The brief asks explicitly which transitions require automated evidence vs. human approval, and the platform's core value proposition is answering "did this reach production safely" with confidence. If a failed gate could be silently overridden, that guarantee becomes conditional and hard to trust — anyone auditing a production version would have to also check whether an override happened, defeating the purpose of having explicit gates at all.

## Decision

Automated evaluation gates (`EvaluationGateResult`) are hard blockers with **no override path** in this design. A `PromotionRequest` cannot be created at all if any gate fails (`docs/failure-modes.md`) — not created-and-pending, simply rejected at the API level with the specific failing criteria. Human approval (`PromotionDecision`) is a separate, later step that only ever operates on requests that already cleared every automated gate — reviewers approve *given* passing evidence, they don't have the power to promote *despite* failing evidence.

## Alternatives considered

- **Admin override with justification text.** Considered and deliberately deferred, not rejected outright — see `docs/open-questions.md` #3. Building it speculatively, before a real incident demonstrates it's needed, risks creating a bypass that gets used as a convenience rather than an emergency measure. If a genuine operational need emerges, the design calls for the override to be loud (its own audit event type, prominent in every view of the version) rather than a quiet checkbox.
- **Let Reviewers see failing gates but promote anyway with a warning.** Rejected — this is the override path above without any of the friction that would keep it rare, and without a durable and different audit signature for "this specific version reached production without passing gates."

## Consequences

There is currently no way to promote a version in an emergency if evaluation evidence is unavailable, stale, or failing — including the case where `agent-eval` itself is down (`docs/failure-modes.md`). This is an accepted, deliberate tradeoff of safety over flexibility for the MVP, explicitly flagged as revisitable if it proves too rigid in practice.
