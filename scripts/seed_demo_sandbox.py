#!/usr/bin/env python3
"""Seeds the public demo sandbox (Phase 7) - docs/phase-notes/phase-7.md,
docs/adrs/0022-public-demo-sandbox.md.

Separate from seed_orion_commerce.py deliberately: this is not part of the
curated Orion Commerce sample org (docs/product-overview.md) and must never
be confused with it - a distinct team, a distinct email domain, agent/policy
created through the real service layer exactly like the Orion seed does for
Skills/MCP. Idempotent throughout: safe to run again after
settings.demo_team_id is set, or after a manual cleanup.

Neither demo identity is ever granted Admin - policy/agent creation below
runs as the shared system actor (app/services/system_actor.py, already used
by the evaluation worker and the demo reset job) instead, keeping the demo
Builder/Reviewer accounts' real authority exactly Builder/Reviewer.

Run: uv run --project backend python scripts/seed_demo_sandbox.py
Prints the demo team id - set DEMO_TEAM_ID (backend) to that value.
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.agent import AgentVersion
from app.models.enums import Role
from app.models.identity import Team, User
from app.services import agents as agents_service
from app.services import evaluation_policies as policies_service
from app.services.errors import ConflictError
from app.services.system_actor import get_system_actor_id

TEAM_NAME = "Public Demo Sandbox"
DEMO_USERS = [
    {"name": "Demo Builder", "email": "demo-builder@agent-platform-demo.example", "role": Role.BUILDER},
    {"name": "Demo Reviewer", "email": "demo-reviewer@agent-platform-demo.example", "role": Role.REVIEWER},
]
AGENT_NAME = "public-demo-agent"
AGENT_DESCRIPTION = (
    "The public, interactive sandbox. Sign in as a dedicated demo Builder/Reviewer "
    "identity and walk the real create -> evaluate -> promote -> review lifecycle "
    "against this Agent only - every write is real and backend-authorized."
)


async def upsert_team(db, name: str) -> Team:
    existing = (await db.execute(select(Team).where(Team.name == name))).scalar_one_or_none()
    if existing:
        return existing
    team = Team(id=uuid.uuid4(), name=name, slack_channel=None)
    db.add(team)
    await db.flush()
    return team


async def upsert_user(db, name: str, email: str, team_id: uuid.UUID, role: Role) -> User:
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return existing
    user = User(id=uuid.uuid4(), name=name, email=email, team_id=team_id, role=role)
    db.add(user)
    await db.flush()
    return user


async def upsert_demo_agent(db, actor: User, team_id: uuid.UUID):
    existing = (
        await db.execute(select(agents_service.Agent).where(agents_service.Agent.name == AGENT_NAME))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return await agents_service.create_agent(
        db, actor=actor, name=AGENT_NAME, team_id=team_id, description=AGENT_DESCRIPTION
    )


async def seed() -> None:
    async with SessionLocal() as db:
        team = await upsert_team(db, TEAM_NAME)
        users = {u["email"]: await upsert_user(db, u["name"], u["email"], team.id, u["role"]) for u in DEMO_USERS}
        await db.commit()

        system_actor_id = await get_system_actor_id(db)
        system_actor = (await db.execute(select(User).where(User.id == system_actor_id))).scalar_one()
        await db.commit()

        agent = await upsert_demo_agent(db, system_actor, team.id)

        try:
            await policies_service.create_evaluation_policy(
                db,
                actor=system_actor,
                name=AGENT_NAME,
                version="v1",
                thresholds={},
                required_evaluator_keys={"completion_check": "v1"},
                dataset_key="stub-agent-smoke-v1",
                max_new_regressions=0,
                min_completion_rate=Decimal("0.800"),
            )
        except ConflictError:
            pass

        has_version = (
            await db.execute(select(AgentVersion.id).where(AgentVersion.agent_id == agent.id).limit(1))
        ).scalar_one_or_none()
        if has_version is None:
            await agents_service.create_agent_version(
                db,
                actor=system_actor,
                agent_id=agent.id,
                manifest={
                    "agent": {"name": AGENT_NAME, "version": "sandbox-0", "framework": "langgraph"},
                    "model": {"provider": "anthropic", "name": "claude-sonnet-5"},
                    "skills": [],
                    "mcp": {},
                    "evaluation": {"policy": f"{AGENT_NAME}@v1"},
                },
            )

    print(f"Demo team id: {team.id}")
    print(f"Demo agent: {AGENT_NAME} ({agent.id})")
    print("Demo identities:")
    for u in users.values():
        print(f"  {u.role.value:>8}  {u.email}")
    print(
        "\nSet backend DEMO_TEAM_ID to the team id above, and create real Identity "
        "Platform accounts for the two demo emails (same Admin REST API flow used for "
        "the Orion Commerce users - see docs/phase-notes/phase-7.md)."
    )


if __name__ == "__main__":
    asyncio.run(seed())
