import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import EvaluationRunStatus, pg_enum

_run_status_enum = pg_enum(EvaluationRunStatus, "evaluation_run_status")


class EvaluationPolicy(Base):
    """docs/domain-model.md#evaluationpolicy - versioned, immutable per (name, version)."""

    __tablename__ = "evaluation_policies"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_evaluation_policy_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    required_evaluator_keys: Mapped[dict] = mapped_column(JSONB, nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    zero_new_regressions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    dataset_key: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class EvaluationRunReference(Base):
    """docs/domain-model.md#evaluationrunreference - a local pointer to an agent-eval run."""

    __tablename__ = "evaluation_run_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), nullable=False)
    evaluation_policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_policies.id"), nullable=False
    )
    external_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_agent_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    status: Mapped[EvaluationRunStatus] = mapped_column(
        _run_status_enum, nullable=False, default=EvaluationRunStatus.REQUESTED
    )
    dataset_snapshot_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    evaluator_versions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(nullable=True)


class EvaluationGateResult(Base):
    """docs/domain-model.md#evaluationgateresult - one named criterion, never one opaque score."""

    __tablename__ = "evaluation_gate_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evaluation_run_reference_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_run_references.id"), nullable=False
    )
    evaluation_policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_policies.id"), nullable=False
    )
    criterion: Mapped[str] = mapped_column(String, nullable=False)
    expected: Mapped[str] = mapped_column(String, nullable=False)
    actual: Mapped[str] = mapped_column(String, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
