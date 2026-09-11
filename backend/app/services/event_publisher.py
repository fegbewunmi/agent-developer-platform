"""The Pub/Sub outbox publish step - docs/adrs/0020-promotion-lifecycle-event-outbox.md.
Two real implementations of the same interface, same shape as
app/services/job_dispatch.py's JobDispatcher:

- LocalNoopPublisher: dev/test fallback. Marks the outbox row published
  in-process, no real transport - every automated test uses this path.
- PubSubPublisher: the real production path. Publishes the outbox row's
  payload to a real Pub/Sub topic, then marks it published. Live-verified
  this phase as far as "publish a real message to a real topic and confirm
  it is pullable" (docs/phase-notes/phase-4.md) - NOT verified as far as "a
  real subscriber service consumes it," because no such consumer exists yet
  (same honesty bar as CloudTasksDispatcher's still-open gap, both tracked
  under Phase 6 in docs/roadmap.md).

Either way, publishing is a strictly post-commit, best-effort step: the
OutboxEvent row itself is written inside the same DB transaction as the
domain change it describes (app/services/promotions.py), so even if
publish() is never called or fails outright, the row - and the fact the
domain event happened - is never lost, only unpublished. Nothing reads
OutboxEvent as a source of truth; audit_events (read directly) already answers
"what happened and why," per docs/audit-model.md - the outbox exists purely
to fan the same fact out to external subscribers, if any exist.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.outbox import OutboxEvent

logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    async def publish(self, outbox_event_id: uuid.UUID) -> None: ...


class LocalNoopPublisher:
    """Marks the row published without any real transport - see module docstring."""

    async def publish(self, outbox_event_id: uuid.UUID) -> None:
        async with SessionLocal() as db:
            event = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == outbox_event_id))).scalar_one()
            event.published_at = datetime.now(timezone.utc)
            await db.commit()


async def sweep_unpublished_outbox_events(publisher: "EventPublisher", *, limit: int = 50) -> dict:
    """Phase 6: the durable-retry half of the outbox pattern. Phase 4/5 only
    ever attempted publish once, immediately after commit
    (app/services/promotions.py::approve_promotion) - real, but incomplete:
    "DB commit succeeds -> Pub/Sub temporarily fails" left that row stuck
    unpublished forever with nothing to notice and retry it. This closes
    that gap with the smallest viable mechanism: re-attempt every row where
    `published_at IS NULL` (the existing `ix_outbox_events_unpublished`
    partial index, added in migration 0016 specifically for this), reusing
    the exact same `publish()` each row's original attempt used - no new
    publish logic, just calling it again.

    Intentionally NOT a generic event-platform retry queue: no backoff
    schedule, no max-attempt tracking, no dead-letter table. A periodic
    sweep (Cloud Scheduler, minutes-scale cadence) calling this is
    sufficient for the actual failure mode in play (a transient Pub/Sub
    hiccup), matching the brief's explicit "do not overbuild" instruction -
    see docs/adrs/0020-promotion-lifecycle-event-outbox.md's Phase 6
    addendum.

    Publish is safe to attempt more than once per row: `publisher.publish`
    is idempotent from this function's point of view (it only ever
    transitions a row from unpublished to published, never the reverse),
    and Pub/Sub itself is already an at-least-once system - real subscribers
    must already tolerate a duplicate delivery, so a duplicate *publish* of
    the same still-unpublished row (the rare case where the previous attempt
    actually succeeded on Pub/Sub's side but crashed before this service
    recorded `published_at`) is within the same guarantee, not a new one.
    """
    async with SessionLocal() as db:
        pending_ids = list(
            (
                await db.execute(
                    select(OutboxEvent.id)
                    .where(OutboxEvent.published_at.is_(None))
                    .order_by(OutboxEvent.created_at)
                    .limit(limit)
                )
            ).scalars().all()
        )

    attempted = len(pending_ids)
    succeeded = 0
    for event_id in pending_ids:
        await publisher.publish(event_id)
        async with SessionLocal() as db:
            row = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))).scalar_one()
            if row.published_at is not None:
                succeeded += 1
            else:
                logger.warning("outbox event %s still unpublished after sweep retry: %s", event_id, row.publish_error)

    return {"attempted": attempted, "succeeded": succeeded, "still_pending": attempted - succeeded}


class PubSubPublisher:
    """Real google-cloud-pubsub client. Requires the topic to already exist
    (created once via `gcloud pubsub topics create`, not created implicitly
    here - same convention as CloudTasksDispatcher's queue)."""

    def __init__(self, project: str, topic: str):
        self._project = project
        self._topic = topic

    async def publish(self, outbox_event_id: uuid.UUID) -> None:
        import asyncio
        import json

        from google.cloud import pubsub_v1

        async with SessionLocal() as db:
            event = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == outbox_event_id))).scalar_one()
            body = {
                "id": str(event.id),
                "event_type": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": str(event.entity_id),
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }

            client = pubsub_v1.PublisherClient()
            topic_path = client.topic_path(self._project, self._topic)

            try:
                future = client.publish(topic_path, json.dumps(body).encode("utf-8"), event_type=event.event_type)
                await asyncio.wrap_future(future)
            except Exception as exc:  # noqa: BLE001 - publish failure must not lose the outbox row
                event.publish_error = str(exc)[:1000]
                await db.commit()
                return

            event.published_at = datetime.now(timezone.utc)
            await db.commit()
