"""Public demo sandbox routes (Phase 7) - docs/phase-notes/phase-7.md.

Two ways to trigger the same reset (app/services/demo.py::reset_demo_environment):
Cloud Scheduler (recurring, OIDC-verified - see app/api/tasks.py) and this
router's Admin-authenticated on-demand endpoint, for a real Orion Admin who
wants a clean demo state right now (e.g. before a screenshot or a live walk-
through). `GET /v1/demo/status` is unauthenticated on purpose - it only ever
returns the demo agent's id/name, the same information anyone browsing the
public catalog can already see, needed so the frontend's "Continue as demo
user" flow can redirect somewhere useful without an extra authenticated call.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import settings
from app.db.session import get_db
from app.dependencies import get_agent_eval_client
from app.integrations.agent_eval_client import AgentEvalClient
from app.models.enums import Role
from app.models.identity import User
from app.services import demo as demo_service
from app.services.errors import PermissionDeniedError

router = APIRouter(prefix="/v1/demo", tags=["demo"])


@router.get("/status")
async def demo_status(db: AsyncSession = Depends(get_db)) -> dict:
    agent = await demo_service.get_demo_agent(db)
    return {
        "demo_agent_id": str(agent.id),
        "demo_agent_name": agent.name,
        "demo_team_id": str(agent.team_id),
        # Not sensitive - the frontend pre-fills the evaluation-request form
        # with this so a visitor never has to know/guess it; the backend
        # still independently rejects any other value regardless (see
        # app/services/evaluations.py::_enforce_demo_evaluation_guardrails).
        "demo_external_agent_version_id": settings.demo_external_agent_version_id,
    }


@router.post("/reset")
async def reset_demo(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
) -> dict:
    if user.role != Role.ADMIN:
        raise PermissionDeniedError("only Admins may trigger an on-demand demo reset")
    return await demo_service.reset_demo_environment(db, agent_eval_client)
