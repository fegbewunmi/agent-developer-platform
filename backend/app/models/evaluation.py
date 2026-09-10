import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ARRAY, Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.types import UTCDateTime
from app.models.enums import EvaluationRunStatus, pg_enum

_run_status_enum = pg_enum(EvaluationRunStatus, "evaluation_run_status")


class EvaluationPolicy(Base):
    """docs/domain-model.md#evaluationpolicy - versioned, immutable per (name, version).

    Fully immutable at the DB level as of Phase 3 (migration 0011), matching
    AgentVersion/SkillVersion - see docs/adrs/0015-evaluation-policy-immutability.md.
    "Editing" a policy means publishing a new (name, version) row.
    """

    __tablename__ = "evaluation_policies"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_evaluation_policy_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    # {"grounding": {"min_mean": 0.85}, "latency": {"min_mean": 0.9}, ...} - per-dimension
    # minimum-score gates. Each key produces its own EvaluationGateResult row; there is no
    # blended score anywhere in this platform.
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {"grounding_judge": "v1", "completion_check": "v1", ...} - required evaluator KEY,
    # pinned to a required VERSION (not just presence) - "required evaluator/version" gate.
    required_evaluator_keys: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Max regressions tolerated vs. the current production version's most recent
    # evaluation on the same dataset (0 = zero tolerance, the Phase 0 default behavior,
    # generalized to a count per the Phase 3 brief's "maximum allowed regressions").
    max_new_regressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # "zero new failures for selected cases/tags" - case tags that must have zero
    # case-run failures for this run to pass, regardless of overall regression count.
    zero_failure_tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    # "required completion status" - minimum fraction of cases that must complete
    # (case_run.status == "success") for the run itself to count as usable evidence.
    min_completion_rate: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("1.0"))
    dataset_key: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)


class EvaluationRunReference(Base):
    """docs/domain-model.md#evaluationrunreference - a local pointer to an agent-eval run.

    Stores only summary evidence (dimension_stats, case-completion counts) needed for
    gating - never full case-level results, which stay in agent-eval
    (docs/control-plane-boundaries.md). external_run_id is the link out for deeper
    inspection.
    """

    __tablename__ = "evaluation_run_references"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), nullable=False)
    evaluation_policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_policies.id"), nullable=False
    )
    external_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_agent_version_id: Mapped[str] = mapped_column(String, nullable=False)
    external_dataset_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_evaluator_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    status: Mapped[EvaluationRunStatus] = mapped_column(
        _run_status_enum, nullable=False, default=EvaluationRunStatus.REQUESTED
    )
    dataset_snapshot_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # A distinctly weaker platform-computed proxy - see app/services/freshness.py's
    # module docstring for exactly what it can and cannot detect vs. the hash above.
    dataset_case_set_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    evaluator_versions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dimension_stats: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    n_cases_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_cases_success: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_cases_error: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    # ADR-0014: a fingerprint of active AgentCapabilityGrants at request time, not a
    # duplicated row dump. capability_grant_snapshot is the small JSON body that hashes
    # to capability_grant_snapshot_hash - see app/services/evidence_snapshot.py.
    capability_grant_snapshot_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    capability_grant_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # docs/failure-modes.md: lets a retried "request evaluation" call be recognized as
    # the same logical request rather than creating a second reference/submitting a
    # second run to agent-eval.
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


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
    gate_type: Mapped[str] = mapped_column(String, nullable=False)
    criterion: Mapped[str] = mapped_column(String, nullable=False)
    expected: Mapped[str] = mapped_column(String, nullable=False)
    actual: Mapped[str] = mapped_column(String, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
