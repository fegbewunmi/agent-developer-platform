import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.models.types import UTCDateTime
from app.models.enums import Role, pg_enum

_role_enum = pg_enum(Role, "role")


class Team(Base):
    """docs/domain-model.md#team"""

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    slack_channel: Mapped[str | None] = mapped_column(String, nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="team")


class User(Base):
    """docs/domain-model.md#user"""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("teams.id"), nullable=False)
    role: Mapped[Role] = mapped_column(_role_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now(), nullable=False)

    team: Mapped["Team"] = relationship(back_populates="users")
