#!/usr/bin/env python3
"""Seeds the Orion Commerce sample organization - docs/product-overview.md.

Phase 1 scope only: Team, User, Agent rows. AgentVersion/Skill/MCP/etc. seed
data is Phase 2+ (it needs the manifest-validation and registry logic that
doesn't exist yet - docs/roadmap.md). Idempotent: safe to re-run, upserts by
natural key (team name, user email, agent name).

Run: uv run --project backend python scripts/seed_orion_commerce.py
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.models.agent import Agent
from app.models.enums import Role
from app.models.identity import Team, User

TEAMS = [
    {"name": "AI Platform", "slack_channel": "#ai-platform"},
    {"name": "Site Reliability Engineering", "slack_channel": "#sre"},
    {"name": "Customer Support Engineering", "slack_channel": "#support-eng"},
    {"name": "Developer Productivity", "slack_channel": "#dev-productivity"},
]

USERS = [
    {"name": "Maya Chen", "email": "maya.chen@orioncommerce.example", "team": "AI Platform", "role": Role.BUILDER},
    {
        "name": "Jordan Brooks",
        "email": "jordan.brooks@orioncommerce.example",
        "team": "Site Reliability Engineering",
        "role": Role.REVIEWER,
    },
    {
        "name": "Priya Shah",
        "email": "priya.shah@orioncommerce.example",
        "team": "Customer Support Engineering",
        "role": Role.REVIEWER,
    },
    {"name": "Alex Rivera", "email": "alex.rivera@orioncommerce.example", "team": "AI Platform", "role": Role.ADMIN},
]

AGENTS = [
    {
        "name": "incident-investigator",
        "team": "AI Platform",
        "description": (
            "Real integration: LangGraph + Vertex AI Gemini multi-agent incident investigation "
            "system (ai-operations). Telemetry, deployment, and knowledge specialists; Incident "
            "Operations MCP; Agent Evaluation Platform integration."
        ),
        "is_representative_data": False,
    },
    {
        "name": "customer-support-agent",
        "team": "Customer Support Engineering",
        "description": (
            "Seeded, representative platform data - not a live system. RAG over customer "
            "knowledge, customer lookup, order status, refund workflows (write/approval-gated)."
        ),
        "is_representative_data": True,
    },
    {
        "name": "release-risk-agent",
        "team": "Developer Productivity",
        "description": (
            "Seeded, representative platform data - not a live system. Deployment analysis, "
            "repository/change metadata, CI/CD signal ingestion, release-risk recommendations."
        ),
        "is_representative_data": True,
    },
]


async def upsert_team(db: AsyncSession, name: str, slack_channel: str) -> Team:
    existing = (await db.execute(select(Team).where(Team.name == name))).scalar_one_or_none()
    if existing:
        return existing
    team = Team(id=uuid.uuid4(), name=name, slack_channel=slack_channel)
    db.add(team)
    await db.flush()
    return team


async def upsert_user(db: AsyncSession, name: str, email: str, team_id: uuid.UUID, role: Role) -> User:
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        return existing
    user = User(id=uuid.uuid4(), name=name, email=email, team_id=team_id, role=role)
    db.add(user)
    await db.flush()
    return user


async def upsert_agent(
    db: AsyncSession, name: str, team_id: uuid.UUID, description: str, is_representative_data: bool
) -> Agent:
    existing = (await db.execute(select(Agent).where(Agent.name == name))).scalar_one_or_none()
    if existing:
        return existing
    agent = Agent(
        id=uuid.uuid4(),
        name=name,
        team_id=team_id,
        description=description,
        is_representative_data=is_representative_data,
    )
    db.add(agent)
    await db.flush()
    return agent


async def seed() -> None:
    async with SessionLocal() as db:
        teams_by_name: dict[str, Team] = {}
        for t in TEAMS:
            teams_by_name[t["name"]] = await upsert_team(db, t["name"], t["slack_channel"])

        for u in USERS:
            await upsert_user(db, u["name"], u["email"], teams_by_name[u["team"]].id, u["role"])

        for a in AGENTS:
            await upsert_agent(
                db, a["name"], teams_by_name[a["team"]].id, a["description"], a["is_representative_data"]
            )

        await db.commit()

    print(f"Seeded {len(TEAMS)} teams, {len(USERS)} users, {len(AGENTS)} agents.")


if __name__ == "__main__":
    asyncio.run(seed())
