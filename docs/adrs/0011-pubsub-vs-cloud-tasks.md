# 0011. Pub/Sub for event fan-out, Cloud Tasks for durable one-shot execution

Status: Accepted

## Context

The brief specifically warns against confusing these two services. Two genuinely different needs exist in this design: (1) notify interested parties that a domain event happened (`promotion.approved`, `capability.revoked`) without knowing or caring who's listening, and (2) durably execute one specific operation - invoking `agent-eval`'s synchronous, multi-minute `POST /runs` - with retry semantics, independent of the request that triggered it (ADR-0005).

## Decision

Pub/Sub (`agent-platform-events` topic) is used exclusively for post-commit, best-effort fan-out of audit/domain events (`docs/audit-model.md`) - at-least-once delivery, no expectation any particular consumer exists yet, never load-bearing for the platform's own consistency. Cloud Tasks is used exclusively for the evaluation-invocation queue - a single owned operation per task with a single owned outcome, needing the retry/backoff/deadline semantics Cloud Tasks provides. Cloud Scheduler handles the one recurring (not event-triggered) job, MCP health checks, which fits neither bucket.

## Alternatives considered

- **Use Cloud Tasks for domain-event fan-out too** (enqueue a task per consumer). Rejected - Cloud Tasks tasks have a specific target and owner; modeling "broadcast to N unknown future consumers" as N Cloud Tasks entries is the wrong shape and would require knowing consumers in advance.
- **Use Pub/Sub for the evaluation-invocation trigger**, with a subscriber pulling and executing. Rejected - Pub/Sub doesn't give the same per-task retry/backoff/deadline control Cloud Tasks provides for a specific long-running HTTP call with a specific expected outcome, and would make "did this evaluation actually get triggered exactly once" harder to reason about than Cloud Tasks' task-dedup semantics.

## Consequences

Two message-passing systems in the stack instead of one - more to operate, but each is used for the thing it's actually good at, avoiding the ambiguity the brief flags as a common mistake. Any future feature needing "notify someone eventually" reaches for Pub/Sub by default; anything needing "this specific operation must complete, with retries" reaches for Cloud Tasks.
