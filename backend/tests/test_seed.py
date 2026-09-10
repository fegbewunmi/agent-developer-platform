"""Runs the real scripts/seed_orion_commerce.py against the test DB (via the
same DATABASE_URL override conftest.py sets), proving the seed data
described in docs/product-overview.md actually loads and that re-running it
is a no-op, not a duplicate-row error.
"""
import sys
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import seed_orion_commerce  # noqa: E402

from app.models.agent import Agent
from app.models.enums import Role
from app.models.identity import Team, User


async def test_seed_creates_expected_orion_commerce_org(db_session):
    await seed_orion_commerce.seed()

    team_count = (await db_session.execute(select(func.count()).select_from(Team))).scalar_one()
    user_count = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    agent_count = (await db_session.execute(select(func.count()).select_from(Agent))).scalar_one()
    assert (team_count, user_count, agent_count) == (4, 4, 3)

    admin = (
        await db_session.execute(select(User).where(User.email == "alex.rivera@orioncommerce.example"))
    ).scalar_one()
    assert admin.role == Role.ADMIN

    incident_investigator = (
        await db_session.execute(select(Agent).where(Agent.name == "incident-investigator"))
    ).scalar_one()
    assert incident_investigator.is_representative_data is False

    support_agent = (
        await db_session.execute(select(Agent).where(Agent.name == "customer-support-agent"))
    ).scalar_one()
    assert support_agent.is_representative_data is True


async def test_seed_is_idempotent(db_session):
    await seed_orion_commerce.seed()
    await seed_orion_commerce.seed()

    team_count = (await db_session.execute(select(func.count()).select_from(Team))).scalar_one()
    user_count = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    agent_count = (await db_session.execute(select(func.count()).select_from(Agent))).scalar_one()
    assert (team_count, user_count, agent_count) == (4, 4, 3)
