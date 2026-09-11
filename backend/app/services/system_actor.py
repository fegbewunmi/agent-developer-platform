"""The one shared system actor used for audit events/writes this platform
makes without a human in the loop - originally added for the evaluation
worker (docs/audit-model.md), reused as-is by the Phase 7 demo reset job
rather than creating a second system identity for the same purpose.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SYSTEM_ACTOR_EMAIL = "system@orion-agent-platform.internal"


async def get_system_actor_id(db: AsyncSession) -> uuid.UUID:
    from app.models.enums import Role
    from app.models.identity import Team, User

    result = await db.execute(select(User.id).where(User.email == SYSTEM_ACTOR_EMAIL))
    actor_id = result.scalar_one_or_none()
    if actor_id is not None:
        return actor_id

    team = (await db.execute(select(Team).where(Team.name == "AI Platform"))).scalar_one_or_none()
    if team is None:
        team = Team(id=uuid.uuid4(), name="AI Platform", slack_channel=None)
        db.add(team)
        await db.flush()

    user = User(id=uuid.uuid4(), name="System (Automated Actor)", email=SYSTEM_ACTOR_EMAIL, team_id=team.id, role=Role.ADMIN)
    db.add(user)
    await db.flush()
    return user.id
