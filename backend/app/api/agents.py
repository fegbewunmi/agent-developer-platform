from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.identity import User

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.get("")
async def list_agents(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Read-only list of seeded Agent rows. is_representative_data is always
    returned so any UI surface can visibly label non-real agents, per
    docs/product-overview.md. AgentVersion CRUD (and therefore anything
    about manifests/stage/lifecycle) is Phase 2 scope, not built yet.
    """
    result = await db.execute(select(Agent).order_by(Agent.name))
    return [
        {
            "id": str(a.id),
            "name": a.name,
            "team_id": str(a.team_id),
            "description": a.description,
            "is_representative_data": a.is_representative_data,
        }
        for a in result.scalars().all()
    ]
