import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.enums import MCPClassification, MCPHealthStatus, pg_enum
from app.models.types import UTCDateTime

_classification_enum = pg_enum(MCPClassification, "mcp_classification")
_health_enum = pg_enum(MCPHealthStatus, "mcp_health_status")


class MCPServer(Base):
    """docs/domain-model.md#mcpserver"""

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    owner_team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    connection_ref: Mapped[str] = mapped_column(String, nullable=False)
    health_status: Mapped[MCPHealthStatus] = mapped_column(
        _health_enum, nullable=False, default=MCPHealthStatus.UNKNOWN
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)


class MCPTool(Base):
    """docs/domain-model.md#mcptool - seeded from the real Incident Operations MCP tools."""

    __tablename__ = "mcp_tools"
    __table_args__ = (UniqueConstraint("mcp_server_id", "name", name="uq_mcp_tool_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mcp_server_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mcp_servers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    io_schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    classification: Mapped[MCPClassification] = mapped_column(_classification_enum, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)


class AgentCapabilityGrant(Base):
    """docs/domain-model.md#agentcapabilitygrant - mutable, revocable. See ADR-0004."""

    __tablename__ = "agent_capability_grants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_versions.id"), nullable=False)
    mcp_tool_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("mcp_tools.id"), nullable=False)
    granted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
