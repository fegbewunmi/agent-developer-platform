"""Public demo sandbox (Phase 7) - docs/phase-notes/phase-7.md,
docs/adrs/0022-public-demo-sandbox.md.

This module does not introduce a second authorization model. It reuses the
real one: `permissions.is_demo_actor`/`demo_containment_ok` (the actor-side
containment, wired into every real write path this phase) and the demo
Agent's `team_id`, exactly like every other Agent in the system. What this
module adds is narrow and operational:

- resolving "the" demo agent (the single Agent owned by the demo team -
  there is deliberately only ever one, created once by
  scripts/seed_demo_sandbox.py, never recreated),
- a periodic/on-demand reset that keeps the public sandbox presentable
  (closes stale abandoned promotion requests, ensures a fresh draft
  version exists) using the exact same real service functions
  (app/services/promotions.py, app/services/agents.py) any real user call
  would use - never a special-cased shortcut.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.agent_eval_client import AgentEvalClient
from app.models.agent import Agent, AgentVersion
from app.models.enums import PromotionRequestStatus
from app.models.identity import User
from app.models.promotion import PromotionRequest
from app.services import agents as agents_service
from app.services import permissions
from app.services import promotions as promotions_service
from app.services.errors import NotFoundError
from app.services.system_actor import get_system_actor_id

# How long a demo visitor's abandoned pending promotion request sits before
# the scheduled reset closes it on their behalf - long enough that no
# realistic single demo walkthrough gets interrupted, short enough that the
# public reviewer queue doesn't accumulate indefinitely.
_STALE_PENDING_REQUEST_AGE = timedelta(hours=2)


async def get_demo_agent(db: AsyncSession) -> Agent:
    demo_team_id = permissions.demo_team_uuid()
    if demo_team_id is None:
        raise NotFoundError("the public demo is not configured in this environment")
    agent = (
        await db.execute(select(Agent).where(Agent.team_id == demo_team_id))
    ).scalar_one_or_none()
    if agent is None:
        raise NotFoundError("the public demo agent has not been seeded yet - run scripts/seed_demo_sandbox.py")
    return agent


def _demo_baseline_manifest(agent_name: str, version_label: str) -> dict:
    return {
        "agent": {"name": agent_name, "version": version_label, "framework": "langgraph"},
        "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
        "skills": [],
        "mcp": {},
        "evaluation": {"policy": f"{agent_name}@v1"},
    }


async def reset_demo_environment(db: AsyncSession, agent_eval_client: AgentEvalClient) -> dict:
    """Real, idempotent tidy-up - never destructive. Old versions, grants,
    evaluations, and promotion history are never deleted (this platform
    never deletes real history, demo included); this only (1) closes any
    promotion request a visitor left dangling past the age above, using the
    real `reject_promotion` path, and (2) ensures a fresh, unpromoted draft
    AgentVersion exists so the next visitor always has somewhere to start.
    """
    agent = await get_demo_agent(db)
    system_actor_id = await get_system_actor_id(db)
    system_actor = (await db.execute(select(User).where(User.id == system_actor_id))).scalar_one()

    cutoff = datetime.now(timezone.utc) - _STALE_PENDING_REQUEST_AGE
    stale_requests = (
        await db.execute(
            select(PromotionRequest)
            .join(AgentVersion, AgentVersion.id == PromotionRequest.agent_version_id)
            .where(
                AgentVersion.agent_id == agent.id,
                PromotionRequest.status == PromotionRequestStatus.PENDING,
                PromotionRequest.requested_at < cutoff,
            )
        )
    ).scalars().all()

    closed_ids: list[str] = []
    for request in stale_requests:
        if request.requested_by == system_actor.id:
            continue  # can never happen in practice (system actor never requests), defensive only
        await promotions_service.reject_promotion(
            db,
            agent_eval_client,
            actor=system_actor,
            promotion_request_id=request.id,
            comment=(
                "Auto-closed by the scheduled public-demo reset (pending longer than "
                f"{int(_STALE_PENDING_REQUEST_AGE.total_seconds() // 3600)}h). Feel free to try the "
                "promotion flow again - this does not affect any other demo history."
            ),
        )
        closed_ids.append(str(request.id))

    fresh_label = f"sandbox-{uuid.uuid4().hex[:8]}"
    fresh_version = await agents_service.create_agent_version(
        db,
        actor=system_actor,
        agent_id=agent.id,
        manifest=_demo_baseline_manifest(agent.name, fresh_label),
    )

    return {
        "demo_agent_id": str(agent.id),
        "closed_stale_requests": closed_ids,
        "new_draft_version_id": str(fresh_version.id),
        "new_draft_version_label": fresh_version.version_label,
    }
