import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.types import UTCDateTime


class OutboxEvent(Base):
    """docs/adrs/0020-promotion-lifecycle-event-outbox.md - the transactional
    outbox for lifecycle events fanned out beyond this platform's own DB
    (Pub/Sub), as distinct from AuditEvent (this platform's own permanent
    history, always readable by direct query regardless of whether anything
    downstream ever consumes it).

    Written in the SAME transaction as the domain change it describes (e.g.
    app/services/promotions.py's recommendation change) - never published to
    Pub/Sub before that transaction commits. Publishing itself happens as a
    separate, best-effort step after commit (app/services/event_publisher.py),
    the same "commit first, dispatch after" shape as
    app/services/job_dispatch.py's evaluation-job dispatch.

    Immutable except `published_at` (column-level GRANT, migration 0016) -
    the same pattern as PromotionRequest.status.
    """

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    publish_error: Mapped[str | None] = mapped_column(String, nullable=True)
