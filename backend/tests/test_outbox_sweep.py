"""app/services/event_publisher.py::sweep_unpublished_outbox_events - the
Phase 6 durable-retry half of the outbox pattern. Proves a row that failed
to publish immediately after commit is not lost - it gets picked up and
retried by the sweep, and only counted done once it genuinely succeeds.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.outbox import OutboxEvent
from app.services.event_publisher import sweep_unpublished_outbox_events


class _FlakyThenOkPublisher:
    """Fails the first N publish attempts for a given event, then succeeds -
    simulates a real transient Pub/Sub outage recovering, without touching
    real Pub/Sub in a unit test."""

    def __init__(self, fail_times: int):
        self._fail_times = fail_times
        self.calls: list[uuid.UUID] = []

    async def publish(self, outbox_event_id: uuid.UUID) -> None:
        self.calls.append(outbox_event_id)
        from app.db.session import SessionLocal

        if len(self.calls) <= self._fail_times:
            async with SessionLocal() as db:
                row = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == outbox_event_id))).scalar_one()
                row.publish_error = "simulated transient Pub/Sub failure"
                await db.commit()
            return
        async with SessionLocal() as db:
            row = (await db.execute(select(OutboxEvent).where(OutboxEvent.id == outbox_event_id))).scalar_one()
            row.published_at = datetime.now(timezone.utc)
            row.publish_error = None
            await db.commit()


async def _insert_unpublished_event(db_session) -> uuid.UUID:
    event_id = uuid.uuid4()
    db_session.add(
        OutboxEvent(
            id=event_id,
            event_type="agent_version.promoted",
            entity_type="agent_version",
            entity_id=uuid.uuid4(),
            payload={"note": "test"},
        )
    )
    await db_session.commit()
    return event_id


async def test_sweep_retries_a_row_that_failed_its_first_publish_attempt(db_session):
    event_id = await _insert_unpublished_event(db_session)

    # First attempt (simulating the original post-commit publish) fails.
    flaky = _FlakyThenOkPublisher(fail_times=1)
    await flaky.publish(event_id)
    row = (await db_session.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))).scalar_one()
    assert row.published_at is None
    assert row.publish_error is not None

    # The sweep picks it up and retries - this time it succeeds.
    db_session.expire(row)
    result = await sweep_unpublished_outbox_events(flaky)
    assert result == {"attempted": 1, "succeeded": 1, "still_pending": 0}

    row = (await db_session.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))).scalar_one()
    assert row.published_at is not None


async def test_sweep_leaves_a_still_failing_row_pending_not_lost(db_session):
    event_id = await _insert_unpublished_event(db_session)
    always_fails = _FlakyThenOkPublisher(fail_times=99)

    result = await sweep_unpublished_outbox_events(always_fails)
    assert result == {"attempted": 1, "succeeded": 0, "still_pending": 1}

    row = (await db_session.execute(select(OutboxEvent).where(OutboxEvent.id == event_id))).scalar_one()
    assert row.published_at is None  # not lost - still a real, findable row for the next sweep


async def test_sweep_ignores_already_published_rows(db_session):
    event_id = uuid.uuid4()
    db_session.add(
        OutboxEvent(
            id=event_id,
            event_type="agent_version.promoted",
            entity_type="agent_version",
            entity_id=uuid.uuid4(),
            payload={},
            published_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    publisher = _FlakyThenOkPublisher(fail_times=0)
    result = await sweep_unpublished_outbox_events(publisher)
    assert result == {"attempted": 0, "succeeded": 0, "still_pending": 0}
    assert publisher.calls == []


async def test_sweep_is_empty_when_nothing_pending(db_session):
    result = await sweep_unpublished_outbox_events(_FlakyThenOkPublisher(fail_times=0))
    assert result == {"attempted": 0, "succeeded": 0, "still_pending": 0}
