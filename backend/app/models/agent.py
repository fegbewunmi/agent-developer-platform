import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.types import UTCDateTime
from app.models.enums import Stage, pg_enum

_stage_enum = pg_enum(Stage, "stage")


class Agent(Base):
    """docs/domain-model.md#agent

    is_representative_data was added during Phase 1 implementation, not
    specified in the Phase 0 domain model - see docs/domain-model.md's
    "Phase 1 addition" note and the Phase 1 report for why: the product
    requirement that seeded agents (Customer Support Agent, Release Risk
    Agent) be visibly labeled as representative, not live, has no field to
    hang off of without it.
    """

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    is_representative_data: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Phase 8 (ADR-0023, ADR-0024): when true, AgentVersions for this Agent
    # may only be created by the CI-publisher machine identity, with real,
    # verified source provenance - manual creation via the human API is
    # rejected outright (app/services/agents.py::create_agent_version).
    # False (default) for every representative/demo agent and every agent
    # not yet integrated with a real CI pipeline.
    requires_ci_provenance: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)

    versions: Mapped[list["AgentVersion"]] = relationship(back_populates="agent")


class AgentVersion(Base):
    """docs/domain-model.md#agentversion

    Fully immutable: every column is write-once. Enforced at the DB level in
    migrations/versions/0008_immutability_roles.py by revoking UPDATE for
    the agent_platform_app role - not just by omitting an edit endpoint.
    stage deliberately does NOT live here; see AgentVersionLifecycle and
    docs/agent-versioning.md#the-stage-vs-content-split.
    """

    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version_label", name="uq_agent_version_label"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    version_label: Mapped[str] = mapped_column(String, nullable=False)
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 8 (ADR-0023, ADR-0024): real source provenance for a
    # CI-published version - {git_repo, git_commit_sha, git_ref, publisher,
    # published_at, image_digest}. Null for every version created before
    # this phase, and for representative/demo agents that never require it
    # (Agent.requires_ci_provenance). Immutable like every other column here
    # - set once at creation, never updated (see the class docstring).
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)

    agent: Mapped["Agent"] = relationship(back_populates="versions")
    lifecycle: Mapped["AgentVersionLifecycle"] = relationship(
        back_populates="agent_version", uselist=False
    )


class AgentVersionLifecycle(Base):
    """docs/domain-model.md#agentversionlifecycle

    Separate, mutable control-plane metadata about an AgentVersion's current
    stage - deliberately not a column on AgentVersion. See
    docs/agent-versioning.md#the-stage-vs-content-split and ADR-0002's
    amendment.

    agent_id is denormalized from AgentVersion.agent_id solely so the
    single-recommended-version-per-agent constraint (the partial unique index
    below) can live on this table.
    """

    __tablename__ = "agent_version_lifecycle"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_versions.id"), primary_key=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), nullable=False)
    stage: Mapped[Stage] = mapped_column(_stage_enum, nullable=False, default=Stage.DRAFT)
    entered_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    entered_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    agent_version: Mapped["AgentVersion"] = relationship(back_populates="lifecycle")

    # UNIQUE (agent_id) WHERE stage = 'recommended' is created as a partial
    # index directly in migrations/versions/0002_agents_and_versions.py, then
    # its predicate renamed in migrations/versions/0017_stage_terminology_rename.py
    # alongside the enum's RENAME VALUE (Phase 8, ADR-0023) - SQLAlchemy's
    # declarative Index() doesn't need to model it here since no ORM-level
    # behavior depends on it, only the DB constraint does.
