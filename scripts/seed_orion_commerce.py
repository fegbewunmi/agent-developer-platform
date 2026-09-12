#!/usr/bin/env python3
"""Seeds the Orion Commerce sample organization - docs/product-overview.md.

Team/User/Agent rows are upserted directly (Phase 1). Skill/SkillVersion/
MCPServer/MCPTool rows are created by calling the real Phase 2 service
layer (app/services/skills.py, app/services/mcp.py) as Maya Chen (Builder)
and Alex Rivera (Admin) respectively - so seeding exercises the same
permission checks, validation, and audit-event emission a real API caller
would, rather than writing rows directly. Idempotent throughout.

The MCP server/tools seeded here are the real, inspected Incident
Operations MCP server (ai-operations/mcp_server/server.py) - not invented.
See docs/mcp-governance.md.

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
from app.models.agent import Agent, AgentVersion
from app.models.enums import MCPClassification, Role, SkillStage
from app.models.identity import Team, User
from app.models.mcp import MCPServer, MCPTool
from app.models.skill import AgentVersionSkill, Skill, SkillVersion, SkillVersionLifecycle
from app.services import agents as agents_service
from app.services import mcp as mcp_service
from app.services import skill_reviews as skill_reviews_service
from app.services import skills as skills_service
from app.services.errors import ConflictError

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


SKILLS = [
    {
        "skill_name": "telemetry-investigation",
        "version": "2.1",
        "purpose": "Correlates metrics, logs, and traces around an incident's onset to surface the "
        "anomalous signals worth investigating further.",
        "implementation_ref": "ai-operations/backend/app/graph/nodes/telemetry.py",
        "compatible_frameworks": ["langgraph"],
    },
    {
        "skill_name": "deployment-analysis",
        "version": "1.3",
        "purpose": "Correlates recent deployments/config changes against an incident's onset to "
        "identify likely triggering changes.",
        "implementation_ref": "ai-operations/backend/app/graph/nodes/deployment.py",
        "compatible_frameworks": ["langgraph"],
    },
    {
        "skill_name": "knowledge-search",
        "version": "3.0",
        "purpose": "Semantic search over runbooks, postmortems, and architecture docs for prior "
        "incidents, known error patterns, and remediation steps.",
        "implementation_ref": "ai-operations/backend/app/graph/nodes/knowledge.py",
        "compatible_frameworks": ["langgraph"],
    },
]

MCP_SERVER = {
    "name": "incident-operations",
    "environment": "development",
    "team": "Site Reliability Engineering",
    "connection_ref": "http://127.0.0.1:8080",
}

# Read directly from ai-operations/mcp_server/server.py - not invented. See
# docs/mcp-governance.md for the exact enforcement-boundary analysis behind
# create_ticket's requires_approval=True.
MCP_TOOLS = [
    {
        "name": "get_investigation_status",
        "description": "Get the current status of an incident investigation.",
        "classification": MCPClassification.READ,
        "requires_approval": False,
    },
    {
        "name": "search_documents",
        "description": "Semantic search over the knowledge base for content relevant to an incident.",
        "classification": MCPClassification.READ,
        "requires_approval": False,
    },
    {
        "name": "get_incident_history",
        "description": "List past incident investigations, live and fixture replays.",
        "classification": MCPClassification.READ,
        "requires_approval": False,
    },
    {
        "name": "create_ticket",
        "description": "Create a ticket for an investigation in the mocked ticketing system. "
        "Confirm-gated in the tool itself; see docs/mcp-governance.md for the exact enforcement "
        "boundary this platform does and does not claim.",
        "classification": MCPClassification.WRITE,
        "requires_approval": True,
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


async def seed_skills(db: AsyncSession, builder: User, team_id: uuid.UUID) -> None:
    for s in SKILLS:
        skill = (
            await db.execute(select(Skill).where(Skill.name == s["skill_name"]))
        ).scalar_one_or_none()
        if skill is None:
            try:
                skill = await skills_service.create_skill(
                    db, actor=builder, name=s["skill_name"], owner_team_id=team_id, description=s["purpose"]
                )
            except ConflictError:
                skill = (
                    await db.execute(select(Skill).where(Skill.name == s["skill_name"]))
                ).scalar_one()

        existing_version = (
            await db.execute(
                select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == s["version"])
            )
        ).scalar_one_or_none()
        if existing_version is None:
            try:
                await skills_service.create_skill_version(
                    db,
                    actor=builder,
                    skill_id=skill.id,
                    version=s["version"],
                    purpose=s["purpose"],
                    input_contract=None,
                    output_contract=None,
                    implementation_ref=s["implementation_ref"],
                    compatible_frameworks=s["compatible_frameworks"],
                )
            except ConflictError:
                pass


async def seed_shared_skill_story(
    db: AsyncSession, builder: User, reviewer: User, admin: User, ai_platform_team_id: uuid.UUID
) -> None:
    """Phase 9 (docs/phase-notes/phase-9.md): the shared-skill developer
    story needs a real, demonstrable example, not just UI polish. Before
    this, `release-risk-agent` had zero AgentVersions and `deployment-
    analysis` had no history of ever being recommended - the "two agents
    share a skill, a newer version exists, consumers aren't auto-upgraded"
    story was literally not present in any seeded data. Idempotent
    throughout, same pattern as seed_skills above.
    """
    skill = (await db.execute(select(Skill).where(Skill.name == "deployment-analysis"))).scalar_one_or_none()
    if skill is None:
        return  # seed_skills runs first; nothing to attach this to if it didn't create the skill

    v13 = (
        await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == "1.3"))
    ).scalar_one_or_none()
    if v13 is None:
        return

    # deployment-analysis@1.4 - published, deliberately left with no
    # consumers, so the skill page can show a real "new version available"
    # story rather than a fabricated one.
    v14 = (
        await db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == "1.4"))
    ).scalar_one_or_none()
    if v14 is None:
        try:
            v14 = await skills_service.create_skill_version(
                db,
                actor=builder,
                skill_id=skill.id,
                version="1.4",
                purpose="Adds config-drift detection to the existing deployment/config-change correlation.",
                input_contract=None,
                output_contract=None,
                implementation_ref="ai-operations/backend/app/graph/nodes/deployment.py",
                compatible_frameworks=["langgraph"],
            )
        except ConflictError:
            v14 = (
                await db.execute(
                    select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version == "1.4")
                )
            ).scalar_one()

    # release-risk-agent's first real AgentVersion, pinning deployment-analysis@1.3 -
    # it had none before this. Not CI-integrated (representative data), so
    # ordinary creation is legitimate here, same as any manually-published version.
    release_risk = (await db.execute(select(Agent).where(Agent.name == "release-risk-agent"))).scalar_one()
    existing_versions = (
        await db.execute(select(AgentVersion).where(AgentVersion.agent_id == release_risk.id))
    ).scalars().all()
    if not existing_versions:
        manifest = {
            "agent": {"name": "release-risk-agent", "version": "2.0.0", "framework": "langgraph"},
            "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
            "skills": ["deployment-analysis@1.3"],
            "mcp": {"servers": [], "tools": []},
            "evaluation": {"policy": "release-risk-v1"},
        }
        await agents_service.create_agent_version(db, actor=admin, agent_id=release_risk.id, manifest=manifest)

    # incident-investigator: only seedable manually where it isn't
    # CI-locked (local dev/test - the real deployed instance has
    # requires_ci_provenance=True, where the only honest way to add a real
    # skill pin is fixing what the real CI pipeline actually publishes, not
    # faking a version here - see ai-operations' publish-to-orion.yml).
    incident_investigator = (
        await db.execute(select(Agent).where(Agent.name == "incident-investigator"))
    ).scalar_one_or_none()
    if incident_investigator is not None and not incident_investigator.requires_ci_provenance:
        pin_exists = (
            await db.execute(
                select(AgentVersionSkill)
                .join(AgentVersion, AgentVersion.id == AgentVersionSkill.agent_version_id)
                .where(AgentVersion.agent_id == incident_investigator.id, AgentVersionSkill.skill_version_id == v13.id)
            )
        ).first()
        if pin_exists is None:
            ii_manifest = {
                "agent": {"name": "incident-investigator", "version": "4.3.0", "framework": "langgraph"},
                "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
                "skills": ["deployment-analysis@1.3"],
                "mcp": {"servers": [], "tools": []},
                "evaluation": {"policy": "incident-investigator"},
            }
            try:
                await agents_service.create_agent_version(
                    db, actor=admin, agent_id=incident_investigator.id, manifest=ii_manifest
                )
            except ConflictError:
                pass

    # deployment-analysis@1.3 becomes RECOMMENDED via a real, decided review -
    # not a lifecycle row silently set to "recommended" by the seed script.
    lifecycle_13 = (
        await db.execute(select(SkillVersionLifecycle).where(SkillVersionLifecycle.skill_version_id == v13.id))
    ).scalar_one_or_none()
    if lifecycle_13 is not None and lifecycle_13.stage == SkillStage.PUBLISHED:
        request = await skill_reviews_service.request_skill_review(
            db, actor=builder, skill_version_id=v13.id, reason="Used by incident-investigator and release-risk-agent; stable in production."
        )
        await skill_reviews_service.approve_skill_review(
            db, actor=reviewer, skill_review_request_id=request.id, comment="Reviewed - safe to recommend for reuse."
        )


async def seed_mcp(db: AsyncSession, admin: User, team_id: uuid.UUID) -> None:
    server = (
        await db.execute(select(MCPServer).where(MCPServer.name == MCP_SERVER["name"]))
    ).scalar_one_or_none()
    if server is None:
        try:
            server = await mcp_service.register_mcp_server(
                db,
                actor=admin,
                name=MCP_SERVER["name"],
                environment=MCP_SERVER["environment"],
                owner_team_id=team_id,
                connection_ref=MCP_SERVER["connection_ref"],
            )
        except ConflictError:
            server = (
                await db.execute(select(MCPServer).where(MCPServer.name == MCP_SERVER["name"]))
            ).scalar_one()

    for t in MCP_TOOLS:
        existing_tool = (
            await db.execute(
                select(MCPTool).where(MCPTool.mcp_server_id == server.id, MCPTool.name == t["name"])
            )
        ).scalar_one_or_none()
        if existing_tool is None:
            try:
                await mcp_service.register_mcp_tool(
                    db,
                    actor=admin,
                    server_id=server.id,
                    name=t["name"],
                    description=t["description"],
                    io_schema=None,
                    classification=t["classification"],
                    requires_approval=t["requires_approval"],
                )
            except ConflictError:
                pass


async def seed() -> None:
    async with SessionLocal() as db:
        teams_by_name: dict[str, Team] = {}
        for t in TEAMS:
            teams_by_name[t["name"]] = await upsert_team(db, t["name"], t["slack_channel"])

        users_by_email: dict[str, User] = {}
        for u in USERS:
            users_by_email[u["email"]] = await upsert_user(
                db, u["name"], u["email"], teams_by_name[u["team"]].id, u["role"]
            )

        for a in AGENTS:
            await upsert_agent(
                db, a["name"], teams_by_name[a["team"]].id, a["description"], a["is_representative_data"]
            )

        await db.commit()

        maya = users_by_email["maya.chen@orioncommerce.example"]
        alex = users_by_email["alex.rivera@orioncommerce.example"]
        jordan = users_by_email["jordan.brooks@orioncommerce.example"]
        ai_platform_team_id = teams_by_name["AI Platform"].id
        sre_team_id = teams_by_name["Site Reliability Engineering"].id

        await seed_skills(db, maya, ai_platform_team_id)
        await seed_mcp(db, alex, sre_team_id)
        await seed_shared_skill_story(db, maya, jordan, alex, ai_platform_team_id)

    print(
        f"Seeded {len(TEAMS)} teams, {len(USERS)} users, {len(AGENTS)} agents, "
        f"{len(SKILLS)} skill versions, 1 MCP server with {len(MCP_TOOLS)} tools."
    )


if __name__ == "__main__":
    asyncio.run(seed())
