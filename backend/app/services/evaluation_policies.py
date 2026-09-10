import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationPolicy
from app.models.identity import User
from app.services import permissions
from app.services.audit import record_audit_event
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError


async def create_evaluation_policy(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    version: str,
    thresholds: dict,
    required_evaluator_keys: dict,
    dataset_key: str,
    max_new_regressions: int = 0,
    zero_failure_tags: list[str] | None = None,
    min_completion_rate: Decimal = Decimal("1.0"),
) -> EvaluationPolicy:
    """Admin-only (docs/auth-and-approval-model.md). Immutable once created -
    no edit endpoint, DB-level UPDATE/DELETE revoked for agent_platform_app
    (migration 0011) - "editing" a policy means publishing a new (name, version)
    row. See docs/adrs/0015-evaluation-policy-immutability.md.
    """
    if not permissions.can_manage_evaluation_policy(actor):
        raise PermissionDeniedError("only Admins may create evaluation policies")

    if not thresholds and not required_evaluator_keys:
        raise ValidationError("a policy must define at least one threshold or required evaluator")

    existing = (
        await db.execute(
            select(EvaluationPolicy.id).where(
                EvaluationPolicy.name == name, EvaluationPolicy.version == version
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"evaluation policy {name!r} already has a version {version!r}")

    policy = EvaluationPolicy(
        id=uuid.uuid4(),
        name=name,
        version=version,
        thresholds=thresholds,
        required_evaluator_keys=required_evaluator_keys,
        max_new_regressions=max_new_regressions,
        zero_failure_tags=zero_failure_tags or [],
        min_completion_rate=min_completion_rate,
        dataset_key=dataset_key,
        created_by=actor.id,
    )
    db.add(policy)
    await db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        event_type="evaluation_policy.created",
        entity_type="evaluation_policy",
        entity_id=policy.id,
        payload={"name": name, "version": version, "dataset_key": dataset_key},
    )
    await db.commit()
    await db.refresh(policy)
    return policy


async def list_evaluation_policies(db: AsyncSession) -> list[EvaluationPolicy]:
    result = await db.execute(select(EvaluationPolicy).order_by(EvaluationPolicy.name, EvaluationPolicy.created_at))
    return list(result.scalars().all())


async def get_evaluation_policy(db: AsyncSession, policy_id: uuid.UUID) -> EvaluationPolicy:
    policy = (
        await db.execute(select(EvaluationPolicy).where(EvaluationPolicy.id == policy_id))
    ).scalar_one_or_none()
    if policy is None:
        raise NotFoundError(f"no evaluation policy with id {policy_id}")
    return policy


async def get_current_policy_for_agent(db: AsyncSession, agent_name: str) -> EvaluationPolicy:
    """docs/evaluation-and-promotion.md: gates are always computed against
    whichever policy is *current* for an Agent - the newest (name, version)
    row, never a version pinned to a specific past evaluation. "Current for
    an Agent" is resolved by policy name == agent name, the simplest
    unambiguous convention available without adding a new Agent<->Policy
    mapping table this phase didn't otherwise need.
    """
    result = await db.execute(
        select(EvaluationPolicy)
        .where(EvaluationPolicy.name == agent_name)
        .order_by(EvaluationPolicy.created_at.desc())
        .limit(1)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise NotFoundError(f"no evaluation policy found for agent {agent_name!r}")
    return policy
