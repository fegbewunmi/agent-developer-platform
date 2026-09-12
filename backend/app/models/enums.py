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
    """AgentVersionLifecycle.stage - see docs/evaluation-and-promotion.md.

    Phase 8 product correction: renamed from
    draft/evaluating/candidate/production/retired. "production" specifically
    implied Orion managed deployment/traffic, which it never has and no
    longer will - see docs/adrs/0023-registry-not-deployment-platform.md.
    The state machine, invariants (one RECOMMENDED version per Agent,
    no-self-approval, hard gates), and every service function are otherwise
    unchanged - this is a vocabulary correction, not a redesign.
    """

    DRAFT = "draft"
    EVALUATING = "evaluating"
    EVALUATED = "evaluated"
    RECOMMENDED = "recommended"
    DEPRECATED = "deprecated"


class MCPClassification(str, enum.Enum):
    READ = "read"
    WRITE = "write"


class MCPHealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class EvaluationRunStatus(str, enum.Enum):
    """docs/evaluation-and-promotion.md's evaluation sequence:
    requested (row created, job dispatched) -> dispatched (worker picked it up,
    calling agent-eval now) -> completed | failed.
    """

    REQUESTED = "requested"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"


class StaleReason(str, enum.Enum):
    """docs/evaluation-and-promotion.md's freshness model - explicit stale reasons,
    never a single boolean. Stored as plain strings in EvaluationGateResult.evidence_ref
    / a dedicated freshness-check response, not a DB enum (these are computed at
    read time, never persisted as a column value)."""

    DATASET_CHANGED = "dataset_changed"
    EVALUATOR_VERSION_CHANGED = "evaluator_version_changed"
    POLICY_CHANGED = "policy_changed"
    CAPABILITY_GRANTS_CHANGED = "capability_grants_changed"
    MISSING_REQUIRED_EVALUATOR = "missing_required_evaluator"


class PromotionRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class PromotionDecisionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"


class SkillStage(str, enum.Enum):
    """SkillVersionLifecycle.stage - docs/skills-and-capabilities.md.

    Phase 9: deliberately a separate, narrower enum from Stage, not a reuse
    of it - a SkillVersion has no automated evaluation/gate step the way an
    AgentVersion does (no agent-eval integration for skills), so DRAFT/
    EVALUATING/EVALUATED would be meaningless here. A SkillVersion is PUBLISHED
    the moment it's created (immutable, same as today); becoming RECOMMENDED
    requires an independent reviewer (SkillReviewRequest/SkillReviewDecision,
    same no-self-approval guarantee as PromotionRequest/PromotionDecision).
    """

    PUBLISHED = "published"
    RECOMMENDED = "recommended"
    DEPRECATED = "deprecated"


class SkillReviewRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SkillReviewDecisionType(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
