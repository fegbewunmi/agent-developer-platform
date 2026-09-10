"""Shared column type for every timestamp in the schema.

Bug found during Phase 2 live testing: `Mapped[datetime]` alone lets
SQLAlchemy infer a timezone-naive Postgres column, which then rejects any
tz-aware Python datetime.now(timezone.utc) passed as a bind parameter
(`asyncpg.exceptions.DataError: can't subtract offset-naive and
offset-aware datetimes`). It only surfaced on columns a service actually
sets client-side (MCPServer.last_health_check_at,
AgentCapabilityGrant.revoked_at) - server_default=func.now() columns never
hit the bug because Postgres computes those values itself, with no Python
value bound. Using this type everywhere, including on server_default
columns, closes the gap before the same mistake recurs on
EvaluationRunReference.completed_at/fetched_at in Phase 3, which nothing
sets yet.
"""
from sqlalchemy import DateTime

UTCDateTime = DateTime(timezone=True)
