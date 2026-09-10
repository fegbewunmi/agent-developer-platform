from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.db.session import get_db
from app.models.identity import Team, User

router = APIRouter(prefix="/v1/teams", tags=["teams"])


@router.get("")
async def list_teams(
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Read access is Viewer+, i.e. any authenticated platform user -
    docs/auth-and-approval-model.md's permission matrix. Write endpoints
    (create/edit team) are Admin-only and are Phase 2+ scope, not built yet.
    """
    result = await db.execute(select(Team).order_by(Team.name))
    return [
        {"id": str(t.id), "name": t.name, "slack_channel": t.slack_channel}
        for t in result.scalars().all()
    ]
