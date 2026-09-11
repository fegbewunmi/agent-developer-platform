from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.dependencies import get_agent_eval_client
from app.integrations.agent_eval_client import AgentEvalClient
from app.models.identity import User
from app.services import dashboard as dashboard_service

router = APIRouter(prefix="/v1/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_dashboard_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    agent_eval_client: AgentEvalClient = Depends(get_agent_eval_client),
) -> dict:
    return await dashboard_service.get_dashboard_summary(db, agent_eval_client, actor=user)
