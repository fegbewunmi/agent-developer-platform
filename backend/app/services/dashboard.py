"""Phase 5: a single, purpose-built read aggregation for the frontend's
Overview page - counts and a "Needs Attention" list, computed from real data
(no invented warnings the backend can't substantiate). This does not
duplicate domain logic: every individual fact here is exactly what
app/services/freshness.py::check_freshness, app/services/promotions.py, and
app/services/mcp.py already compute/return - this module only aggregates and
shapes them for one screen, the same way app/api/promotions.py's
_enrich_with_context is a display join, not new business logic.

Live freshness checks (per evaluated version, per pending request, per
recommended version) each make real calls to agent-eval - bounded by how many Agents/
AgentVersions actually exist, run CONCURRENTLY (not one-at-a-time - a real
performance bug found live: sequential checks against the real deployed
agent-eval-api made this endpoint take 25-47 seconds with only ~7 versions
to check), and each wrapped so one unreachable/slow agent-eval call
degrades that one item, never crashes the whole dashboard (the same "API
unavailable" failure mode every other freshness-consuming view already has
to handle).

Each concurrent check gets its OWN AsyncSession (SessionLocal) rather than
sharing the request's `db` session - AsyncSession is not safe for concurrent
use from multiple coroutines at once, so asyncio.gather-ing check_freshness
calls that all shared one session would risk "another operation is in
progress" errors, not just be slow.
"""
import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.integrations.agent_eval_client import AgentEvalClient
from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import PromotionRequestStatus, Role, Stage
from app.models.identity import User
from app.models.mcp import MCPServer
from app.models.enums import MCPHealthStatus
from app.services import audit as audit_service
from app.services import permissions
from app.services import promotions as promotions_service
from app.services.freshness import FreshnessResult, check_freshness

_UNHEALTHY = {MCPHealthStatus.DEGRADED, MCPHealthStatus.UNAVAILABLE}


@dataclass(frozen=True)
class _FreshnessCheck:
    agent_version_id: uuid.UUID
    agent_name: str
    promotable_stages: frozenset[Stage]


async def _check_freshness_own_session(
    agent_eval_client: AgentEvalClient, check: _FreshnessCheck
) -> FreshnessResult | None:
    try:
        async with SessionLocal() as db:
            return await check_freshness(
                db, agent_eval_client, check.agent_version_id, check.agent_name, promotable_stages=check.promotable_stages
            )
    except Exception:  # noqa: BLE001 - agent-eval unavailable degrades this one item, not the dashboard
        return None


def _demo_visibility_clause(actor: User):
    """Binary demo/non-demo bucket, not a per-team filter: a demo actor sees
    only the demo team's own agent; every real Orion user sees everything
    EXCEPT the demo team's agent, preserving the existing cross-team
    visibility real Reviewers/Admins rely on (ADR-0010). Keeps the curated
    dashboard and reviewer queue free of public-demo noise. Returns None
    (no filter) when the demo isn't configured - unchanged behavior for
    every environment before Phase 7."""
    demo_team = permissions.demo_team_uuid()
    if demo_team is None:
        return None
    if actor.team_id == demo_team:
        return Agent.team_id == demo_team
    return Agent.team_id != demo_team


async def _lifecycle_rows(
    db: AsyncSession, stage: Stage, *, actor: User
) -> list[tuple[AgentVersionLifecycle, AgentVersion, Agent]]:
    stmt = (
        select(AgentVersionLifecycle, AgentVersion, Agent)
        .join(AgentVersion, AgentVersion.id == AgentVersionLifecycle.agent_version_id)
        .join(Agent, Agent.id == AgentVersionLifecycle.agent_id)
        .where(AgentVersionLifecycle.stage == stage)
    )
    clause = _demo_visibility_clause(actor)
    if clause is not None:
        stmt = stmt.where(clause)
    rows = await db.execute(stmt)
    return list(rows.all())


async def get_dashboard_summary(db: AsyncSession, agent_eval_client: AgentEvalClient, *, actor: User) -> dict:
    recommended_rows = await _lifecycle_rows(db, Stage.RECOMMENDED, actor=actor)
    evaluated_rows = await _lifecycle_rows(db, Stage.EVALUATED, actor=actor)

    pending_requests = await promotions_service.list_promotion_requests(
        db, status=PromotionRequestStatus.PENDING, actor=actor
    )
    my_reviewable = [
        r for r in pending_requests if actor.role in (Role.REVIEWER, Role.ADMIN) and r.requested_by != actor.id
    ]

    # Display context for pending requests (agent/version names), fetched once.
    pending_version_ids = {r.agent_version_id for r in pending_requests}
    pending_context: dict[uuid.UUID, tuple[AgentVersion, Agent]] = {}
    if pending_version_ids:
        rows = await db.execute(
            select(AgentVersion, Agent).join(Agent, Agent.id == AgentVersion.agent_id).where(AgentVersion.id.in_(pending_version_ids))
        )
        pending_context = {v.id: (v, a) for v, a in rows.all()}

    needs_attention: list[dict] = []

    # Every live freshness check this endpoint needs, across all three
    # categories, dispatched together - not one category at a time, each
    # waiting on the previous.
    evaluated_checks = [_FreshnessCheck(version.id, agent.name, frozenset({Stage.EVALUATED})) for _, version, agent in evaluated_rows]
    pending_checks = [
        _FreshnessCheck(pending_context[r.agent_version_id][0].id, pending_context[r.agent_version_id][1].name, frozenset({Stage.EVALUATED, Stage.DEPRECATED}))
        for r in pending_requests
        if r.agent_version_id in pending_context
    ]
    recommended_checks = [_FreshnessCheck(version.id, agent.name, frozenset({Stage.RECOMMENDED})) for _, version, agent in recommended_rows]

    all_checks = evaluated_checks + pending_checks + recommended_checks
    all_results = await asyncio.gather(*[_check_freshness_own_session(agent_eval_client, c) for c in all_checks])

    evaluated_results = dict(zip((c.agent_version_id for c in evaluated_checks), all_results[: len(evaluated_checks)]))
    pending_results = dict(
        zip(
            (c.agent_version_id for c in pending_checks),
            all_results[len(evaluated_checks) : len(evaluated_checks) + len(pending_checks)],
        )
    )
    recommended_results = dict(zip((c.agent_version_id for c in recommended_checks), all_results[len(evaluated_checks) + len(pending_checks) :]))

    stale_evaluated: list[dict] = []
    for _, version, agent in evaluated_rows:
        result = evaluated_results.get(version.id)
        if result is not None and result.stale_findings:
            item = {
                "type": "stale_evaluated",
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "agent_version_id": str(version.id),
                "version_label": version.version_label,
                "stale_findings": [{"reason": f.reason, "detail": f.detail} for f in result.stale_findings],
            }
            stale_evaluated.append(item)
            needs_attention.append(item)

    blocked_reviews: list[dict] = []
    for r in pending_requests:
        ctx = pending_context.get(r.agent_version_id)
        if ctx is None:
            continue
        version, agent = ctx
        result = pending_results.get(r.agent_version_id)
        if result is not None and not result.currently_eligible:
            item = {
                "type": "blocked_review",
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "agent_version_id": str(version.id),
                "version_label": version.version_label,
                "promotion_request_id": str(r.id),
                "stale_findings": [{"reason": f.reason, "detail": f.detail} for f in result.stale_findings],
            }
            blocked_reviews.append(item)
            needs_attention.append(item)

    for r in my_reviewable:
        ctx = pending_context.get(r.agent_version_id)
        needs_attention.append(
            {
                "type": "pending_review",
                "promotion_request_id": str(r.id),
                "agent_id": str(ctx[1].id) if ctx else None,
                "agent_name": ctx[1].name if ctx else None,
                "agent_version_id": str(r.agent_version_id),
                "version_label": ctx[0].version_label if ctx else None,
                "from_stage": r.from_stage.value,
                "requested_at": r.requested_at.isoformat(),
            }
        )

    stale_recommended: list[dict] = []
    for _, version, agent in recommended_rows:
        result = recommended_results.get(version.id)
        if result is not None and result.stale_findings:
            item = {
                "type": "stale_recommended_evidence",
                "agent_id": str(agent.id),
                "agent_name": agent.name,
                "agent_version_id": str(version.id),
                "version_label": version.version_label,
                "stale_findings": [{"reason": f.reason, "detail": f.detail} for f in result.stale_findings],
            }
            stale_recommended.append(item)
            needs_attention.append(item)

    unhealthy_servers = (
        await db.execute(select(MCPServer).where(MCPServer.health_status.in_(_UNHEALTHY)))
    ).scalars().all()
    for s in unhealthy_servers:
        needs_attention.append(
            {
                "type": "unhealthy_mcp",
                "mcp_server_id": str(s.id),
                "name": s.name,
                "health_status": s.health_status.value,
            }
        )

    # Phase 7: the global feed is real internal Orion Commerce activity - a
    # public demo actor never sees it here (AuditEvent has no team column to
    # filter by cheaply, and the point of this widget for a demo visitor is
    # "what have I/other demo visitors done," not the whole org's history).
    # A real Orion actor's feed is unfiltered, unchanged from Phase 5 - full
    # transparency for trusted internal staff, including any demo activity.
    recent_activity = [] if permissions.is_demo_actor(actor) else await audit_service.list_audit_events(db, limit=15)

    return {
        "counts": {
            "recommended_agents": len(recommended_rows),
            "evaluated_versions": len(evaluated_rows),
            "pending_reviews": len(my_reviewable),
            "blocked_reviews": len(blocked_reviews),
            "stale_evaluated_evidence": len(stale_evaluated),
            "unhealthy_mcp_servers": len(unhealthy_servers),
        },
        "needs_attention": needs_attention,
        "recent_activity": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "entity_type": e.entity_type,
                "entity_id": str(e.entity_id),
                "actor": str(e.actor),
                "occurred_at": e.occurred_at.isoformat(),
                "payload": e.payload,
            }
            for e in recent_activity
        ],
    }
