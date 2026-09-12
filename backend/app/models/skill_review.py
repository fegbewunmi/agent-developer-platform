import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.types import UTCDateTime
from app.models.enums import SkillReviewDecisionType, SkillReviewRequestStatus, pg_enum

_skill_review_status_enum = pg_enum(SkillReviewRequestStatus, "skill_review_request_status")
_skill_review_decision_enum = pg_enum(SkillReviewDecisionType, "skill_review_decision_type")


class SkillReviewRequest(Base):
    """Phase 9: structurally parallel to PromotionRequest, deliberately
    smaller - no evaluation_run_reference_id/evaluation_policy_id/freshness
    snapshot, because a SkillVersion has no automated evaluation/gate step
    at all (no agent-eval integration for skills). Forcing this through
    PromotionRequest would mean either fabricating fake evaluation rows or
    loosening that table's currently-hard, immutability-critical
    constraints - see docs/phase-notes/phase-9.md and
    docs/adrs/0025-skill-review-as-a-separate-model.md.

    Immutable at the DB level except `status`, same pattern as
    PromotionRequest - migrations/versions/0019_skill_review.py.
    """

    __tablename__ = "skill_review_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill_versions.id"), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    status: Mapped[SkillReviewRequestStatus] = mapped_column(
        _skill_review_status_enum, nullable=False, default=SkillReviewRequestStatus.PENDING
    )
    reason: Mapped[str | None] = mapped_column(String, nullable=True)


class SkillReviewDecision(Base):
    """Fully immutable once created (no UPDATE/DELETE grant at all - same as
    PromotionDecision). decided_by != requested_by enforced by a DB trigger
    (fn_reject_self_approval_skill_review), the same no-self-approval
    guarantee as PromotionDecision, not merely application logic -
    docs/adrs/0009-no-self-approval.md's pattern, reused for a distinct
    table rather than generalized into one shared trigger, since the two
    entities' columns differ.
    """

    __tablename__ = "skill_review_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_review_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_review_requests.id"), unique=True, nullable=False
    )
    decision: Mapped[SkillReviewDecisionType] = mapped_column(_skill_review_decision_enum, nullable=False)
    decided_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    comment: Mapped[str | None] = mapped_column(String, nullable=True)
