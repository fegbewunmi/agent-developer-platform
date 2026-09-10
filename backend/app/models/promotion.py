import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.types import UTCDateTime
from app.models.enums import PromotionDecisionType, PromotionRequestStatus, Stage, pg_enum

_promotion_status_enum = pg_enum(PromotionRequestStatus, "promotion_request_status")
_promotion_decision_enum = pg_enum(PromotionDecisionType, "promotion_decision_type")
_stage_enum = pg_enum(Stage, "stage")


class PromotionRequest(Base):
    """docs/domain-model.md#promotionrequest"""

    __tablename__ = "promotion_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), nullable=False)
    from_stage: Mapped[Stage] = mapped_column(_stage_enum, nullable=False)
    to_stage: Mapped[Stage] = mapped_column(_stage_enum, nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    evaluation_run_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evaluation_run_references.id"), nullable=True
    )
    status: Mapped[PromotionRequestStatus] = mapped_column(
        _promotion_status_enum, nullable=False, default=PromotionRequestStatus.PENDING
    )
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class PromotionDecision(Base):
    """docs/domain-model.md#promotiondecision

    decided_by != requested_by is enforced by a DB trigger
    (fn_reject_self_approval in migrations/versions/0006_promotion.py), not
    just application logic - see docs/adrs/0009-no-self-approval.md.
    """

    __tablename__ = "promotion_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    promotion_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("promotion_requests.id"), unique=True, nullable=False
    )
    decision: Mapped[PromotionDecisionType] = mapped_column(_promotion_decision_enum, nullable=False)
    decided_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
