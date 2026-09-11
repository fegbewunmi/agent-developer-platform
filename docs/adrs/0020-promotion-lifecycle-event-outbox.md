# 0020. Transactional outbox for the promotion-lifecycle Pub/Sub event

Status: Accepted

## Context

ADR-0011 already decided *which* message bus to use for domain-event fan-out (Pub/Sub, topic `agent-platform-events`) versus durable one-shot execution (Cloud Tasks, the evaluation-invocation queue). It did not decide *how* a domain event gets from "just committed to Postgres" to "published to Pub/Sub" without a window where the DB says one thing and a downstream subscriber never hears about it (or hears about something that then gets rolled back). `docs/roadmap.md`'s Phase 4 scope note flags this directly: Phase 1-3 `AuditEvent`s are transactionally correct but only ever readable by direct query, never fanned out.

The Phase 4 brief is explicit: "do not publish a domain event before the database transaction commits." A naive "commit, then publish" without anything in between has a real failure window - if the process crashes between the two, the promotion is real but no event was ever published, silently.

## Decision

A **transactional outbox**: `OutboxEvent` (migration `0016_outbox_events.py`) is written in the exact same DB transaction as the production transition it describes - inside `approve_promotion`'s single `db.commit()`, alongside the `PromotionDecision`, the `AgentVersionLifecycle` updates, and the `AuditEvent`s. If anything in that transaction fails, the outbox row never exists either - no dangling proof-of-intent-to-publish for an event that didn't actually happen. Publishing itself (`app/services/event_publisher.py::EventPublisher`) is a separate, best-effort step called *after* `commit()` returns, the same "commit first, dispatch after" shape `app/services/job_dispatch.py` already uses for evaluation-job dispatch.

Scope for this phase: only the actual production transition (`agent_version.promoted`) is fanned out to the outbox - not every `AuditEvent` type. `promotion.requested`/`promotion.rejected`/etc. remain queryable via `audit_events` (per `docs/audit-model.md`'s existing guarantee) but are not published. Fanning out the full audit-event stream is a bigger, separate decision (which event types, what schema stability promise to external consumers) left for whenever a real consumer needs more than the promotion signal - not built speculatively here.

Two `EventPublisher` implementations, the same shape as `JobDispatcher`: `LocalNoopPublisher` (dev/test - marks the row published in-process, no real transport) and `PubSubPublisher` (the real path). `OutboxEvent` is immutable except `published_at`/`publish_error` (column-level `GRANT`, same pattern as `PromotionRequest.status`) - a publish attempt updates those two columns and nothing else.

**Live-verified**, not just reasoned about: a real `agent-platform-events` Pub/Sub topic exists in `ai-ops-center-eb26` (Pub/Sub topics are global, not regional - no region config needed, unlike the Cloud Run/Cloud Tasks resources in `docs/gcp-architecture.md`); `PubSubPublisher.publish()` was run against it for a real `OutboxEvent` row, and a real subscription (`gcloud pubsub subscriptions pull`, deleted after verification - a temporary check, not a permanent consumer) confirmed the message actually arrived, not just that the publish API call returned success. This is a stronger proof than ADR-0011 anticipated needing for Cloud Tasks (which only proved task creation, not delivery-to-a-live-receiver, since no receiver was deployed yet) - Pub/Sub's pull-based verification doesn't require a running consumer service to prove delivery, so this gap doesn't apply here the way it does for Cloud Tasks. No real subscriber *service* exists yet (Phase 6, same as the Cloud Tasks receiver) - that remains a named, open gap.

## Alternatives considered

- **Publish directly inside the request handler, before commit.** Rejected outright by the brief - a request that later fails/rolls back would have already told the world it happened.
- **Publish directly after commit, no outbox table.** Rejected - if the process dies between `commit()` and the publish call, the event is silently lost forever with no record that it should have gone out. The outbox row is small, durable proof of intent that survives a crash, even if it takes a manual/future reconciliation pass to notice `published_at IS NULL` rows and retry them (that reconciliation sweep is not built this phase - `ix_outbox_events_unpublished` exists specifically so it can be, later, without a schema change).
- **CDC (change-data-capture) off the `audit_events` table instead of an application-level outbox.** Rejected - adds a real new piece of infrastructure (Debezium or Cloud SQL's own CDC tooling) for a single event type with no real consumer yet; an application-level outbox is the smallest thing that actually closes the "don't publish before commit" gap the brief asks about.

## Consequences

Every promotion approval now does one extra local INSERT (cheap) and one extra network call after commit (Pub/Sub publish, best-effort - a failure there is recorded on the row, never raised back to the caller, since the promotion itself already succeeded and must not appear to fail because of an unrelated fan-out problem). Unpublished rows (`published_at IS NULL`) are not currently retried automatically; a Phase 6 sweep job is the natural next step once a real consumer exists to make retrying worthwhile.
