import uuid
from datetime import datetime

from sqlalchemy import ARRAY, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.types import UTCDateTime
from app.models.enums import SkillStage, pg_enum

_skill_stage_enum = pg_enum(SkillStage, "skill_stage")


class Skill(Base):
    """docs/domain-model.md#skill"""

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    owner_team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)


class SkillVersion(Base):
    """docs/domain-model.md#skillversion

    Immutable once published, same DB-level enforcement as AgentVersion -
    see migrations/versions/0008_immutability_roles.py.
    """

    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    input_contract: Mapped[str | None] = mapped_column(String, nullable=True)
    output_contract: Mapped[str | None] = mapped_column(String, nullable=True)
    implementation_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    compatible_frameworks: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)


class AgentVersionSkill(Base):
    """docs/domain-model.md#agentversionskill - immutable pin, set once."""

    __tablename__ = "agent_version_skills"

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_versions.id"), primary_key=True
    )
    skill_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_versions.id"), primary_key=True
    )


class SkillVersionLifecycle(Base):
    """Phase 9: SkillVersion's own "stage vs. content split," mirroring
    AgentVersionLifecycle exactly - docs/agent-versioning.md#the-stage-vs-
    content-split, applied to skills. Separate, mutable control-plane
    metadata about a SkillVersion's current stage, deliberately not a column
    on SkillVersion itself.

    skill_id is denormalized from SkillVersion.skill_id for the same reason
    as AgentVersionLifecycle.agent_id - the single-recommended-version-per-
    skill partial unique index lives on this table.
    """

    __tablename__ = "skill_version_lifecycle"

    skill_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("skill_versions.id"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id"), nullable=False)
    stage: Mapped[SkillStage] = mapped_column(_skill_stage_enum, nullable=False, default=SkillStage.PUBLISHED)
    entered_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    entered_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    # UNIQUE (skill_id) WHERE stage = 'recommended' is created as a partial
    # index in migrations/versions/0019_skill_review.py, mirroring
    # agent_version_lifecycle's uq_one_production_version_per_agent.
