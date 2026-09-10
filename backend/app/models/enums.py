import enum

from sqlalchemy import Enum as _SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> _SAEnum:
    """A native Postgres enum column type that stores each member's .value
    (e.g. "builder"), not its .name (e.g. "BUILDER") - SQLAlchemy's Enum()
    maps by .name by default, which silently mismatches the lowercase
    values every migration creates (see migrations/versions/0001..0006).
    Discovered when scripts/seed_orion_commerce.py's first live run failed
    with `invalid input value for enum role: "BUILDER"` - see the Phase 1
    report's "bugs discovered" section.
    """
    return _SAEnum(enum_cls, name=name, native_enum=True, values_callable=lambda e: [m.value for m in e])


class Role(str, enum.Enum):
    """Global roles - see docs/auth-and-approval-model.md."""

    VIEWER = "viewer"
    BUILDER = "builder"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class Stage(str, enum.Enum):
    """AgentVersionLifecycle.stage - see docs/evaluation-and-promotion.md."""

    DRAFT = "draft"
    EVALUATING = "evaluating"
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    RETIRED = "retired"


class MCPClassification(str, enum.Enum):
    READ = "read"
    WRITE = "write"


class MCPHealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class EvaluationRunStatus(str, enum.Enum):
    REQUESTED = "requested"
    COMPLETED = "completed"
    FAILED = "failed"


class PromotionRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class PromotionDecisionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
