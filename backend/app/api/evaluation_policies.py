from decimal import Decimal
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.identity import User
from app.services import evaluation_policies as policies_service

router = APIRouter(prefix="/v1/evaluation-policies", tags=["evaluation-policies"])


class CreatePolicyRequest(BaseModel):
    name: str
    version: str
    thresholds: dict = {}
    required_evaluator_keys: dict = {}
    dataset_key: str
    max_new_regressions: int = 0
    zero_failure_tags: list[str] = []
    min_completion_rate: Decimal = Decimal("1.0")


def _policy_to_dict(p) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "version": p.version,
        "thresholds": p.thresholds,
        "required_evaluator_keys": p.required_evaluator_keys,
        "max_new_regressions": p.max_new_regressions,
        "zero_failure_tags": p.zero_failure_tags,
        "min_completion_rate": str(p.min_completion_rate),
        "dataset_key": p.dataset_key,
        "created_by": str(p.created_by),
        "created_at": p.created_at.isoformat(),
    }


@router.get("")
async def list_policies(_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[dict]:
    return [_policy_to_dict(p) for p in await policies_service.list_evaluation_policies(db)]


@router.post("", status_code=201)
async def create_policy(
    body: CreatePolicyRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    """No PATCH endpoint, deliberately - a policy is immutable once created
    (docs/adrs/0015-evaluation-policy-immutability.md); a change is a new
    (name, version) row."""
    policy = await policies_service.create_evaluation_policy(
        db,
        actor=user,
        name=body.name,
        version=body.version,
        thresholds=body.thresholds,
        required_evaluator_keys=body.required_evaluator_keys,
        dataset_key=body.dataset_key,
        max_new_regressions=body.max_new_regressions,
        zero_failure_tags=body.zero_failure_tags,
        min_completion_rate=body.min_completion_rate,
    )
    return _policy_to_dict(policy)


@router.get("/{policy_id}")
async def get_policy(
    policy_id: uuid.UUID, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict:
    return _policy_to_dict(await policies_service.get_evaluation_policy(db, policy_id))
