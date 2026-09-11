"""Phase 5's new purpose-built read endpoints - agent catalog enrichment,
global audit events, the global promotion-request reviewer queue, the MCP
tool grants reverse lookup, and the dashboard summary. These are display
aggregations over Phase 1-4 domain logic (docs/phase-notes/phase-5.md), not
new business rules, so tests here mostly check shape/filtering/enrichment
rather than re-testing authorization or state machines already covered
elsewhere.
"""
import uuid

from app.dependencies import get_agent_eval_client, get_job_dispatcher
from app.main import app
from app.models.enums import MCPClassification
from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator


class _RecordingNoOpDispatcher:
    async def dispatch_evaluation_job(self, evaluation_run_reference_id):
        pass


def _wire_fake_client(fake_client: FakeAgentEvalClient):
    app.dependency_overrides[get_agent_eval_client] = lambda: fake_client
    app.dependency_overrides[get_job_dispatcher] = lambda: _RecordingNoOpDispatcher()


async def test_list_agents_includes_production_version(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "catalog-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]

    manifest = {
        "agent": {"name": "catalog-agent", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {"servers": [], "tools": []}, "evaluation": {"policy": "catalog-agent"},
    }
    await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))

    list_resp = await client.get("/v1/agents", headers=headers_for(org["viewer"]))
    entry = next(a for a in list_resp.json() if a["id"] == agent_id)
    assert entry["production_version_id"] is None  # still draft, not production
    assert entry["stage_counts"] == {"draft": 1}

    detail_resp = await client.get(f"/v1/agents/{agent_id}", headers=headers_for(org["viewer"]))
    assert detail_resp.json()["stage_counts"] == {"draft": 1}


async def test_audit_events_filters_by_entity(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "audit-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]

    all_events = await client.get("/v1/audit-events", headers=headers_for(org["viewer"]))
    assert all_events.status_code == 200
    assert any(e["entity_id"] == agent_id and e["event_type"] == "agent.created" for e in all_events.json())

    scoped = await client.get(f"/v1/audit-events?entity_type=agent&entity_id={agent_id}", headers=headers_for(org["viewer"]))
    assert len(scoped.json()) == 1
    assert scoped.json()[0]["event_type"] == "agent.created"


async def test_audit_events_requires_auth(client):
    resp = await client.get("/v1/audit-events")
    assert resp.status_code == 401


async def _make_candidate_via_api(client, org, headers_for, name):
    agent_resp = await client.post("/v1/agents", json={"name": name, "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"]))
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": name, "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {"servers": [], "tools": []}, "evaluation": {"policy": name},
    }
    v_resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    version_id = v_resp.json()["id"]

    await client.post(
        "/v1/evaluation-policies",
        json={"name": name, "version": "v1", "thresholds": {}, "required_evaluator_keys": {"completion_check": "v1"}, "dataset_key": name},
        headers=headers_for(org["admin"]),
    )
    fake_client = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset(name, cases=[{"key": "c1", "tags": []}], dataset_id=f"ds-{name}")],
    )
    from app.integrations.agent_eval_client import DimensionStat

    fake_client.next_run_dimension_stats = [DimensionStat(dimension="completion", mean_score=1.0, n=1, n_not_applicable=0)]
    _wire_fake_client(fake_client)

    eval_resp = await client.post(
        f"/v1/agent-versions/{version_id}/evaluations", json={"external_agent_version_id": f"ext-{version_id}"},
        headers=headers_for(org["builder"]),
    )
    reference_id = eval_resp.json()["id"]
    from app.services.evaluation_worker import process_evaluation_job

    await process_evaluation_job(uuid.UUID(reference_id), fake_client)
    return agent_id, version_id, fake_client


async def test_reviewer_queue_lists_pending_with_context(client, org, headers_for):
    agent_id, version_id, fake_client = await _make_candidate_via_api(client, org, headers_for, "queue-agent")
    _wire_fake_client(fake_client)

    req_resp = await client.post(
        f"/v1/agent-versions/{version_id}/promotion-requests", json={"reason": "ship it"}, headers=headers_for(org["builder"])
    )
    assert req_resp.status_code == 201

    queue = await client.get("/v1/promotion-requests?status=pending", headers=headers_for(org["reviewer"]))
    assert queue.status_code == 200
    entry = next(r for r in queue.json() if r["agent_version_id"] == version_id)
    assert entry["agent_name"] == "queue-agent"
    assert entry["version_label"] == "1.0.0"
    assert entry["requested_by_name"] == "Test builder"
    assert entry["decision"] is None

    approved = await client.get("/v1/promotion-requests?status=approved", headers=headers_for(org["reviewer"]))
    assert approved.json() == []


async def test_promotion_history_includes_decider_name(client, org, headers_for):
    agent_id, version_id, fake_client = await _make_candidate_via_api(client, org, headers_for, "history-ctx-agent")
    _wire_fake_client(fake_client)
    req_resp = await client.post(
        f"/v1/agent-versions/{version_id}/promotion-requests", json={}, headers=headers_for(org["builder"])
    )
    request_id = req_resp.json()["id"]
    await client.post(f"/v1/promotion-requests/{request_id}/approve", json={}, headers=headers_for(org["reviewer"]))

    history = await client.get(f"/v1/agents/{agent_id}/promotion-history", headers=headers_for(org["admin"]))
    entry = history.json()[0]
    assert entry["decision"]["decided_by_name"] == "Test reviewer"


async def test_mcp_tool_grants_reverse_lookup(client, org, headers_for):
    server_resp = await client.post(
        "/v1/mcp-servers",
        json={"name": "grants-lookup-server", "environment": "development", "owner_team_id": str(org["team_a"].id), "connection_ref": "http://127.0.0.1:9"},
        headers=headers_for(org["admin"]),
    )
    server_id = server_resp.json()["id"]
    tool_resp = await client.post(
        f"/v1/mcp-servers/{server_id}/tools",
        json={"name": "lookup_tool", "classification": "read", "requires_approval": False},
        headers=headers_for(org["admin"]),
    )
    tool_id = tool_resp.json()["id"]

    agent_resp = await client.post(
        "/v1/agents", json={"name": "grant-lookup-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": "grant-lookup-agent", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {"servers": [], "tools": []}, "evaluation": {"policy": "grant-lookup-agent"},
    }
    v_resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    version_id = v_resp.json()["id"]

    empty = await client.get(f"/v1/mcp-tools/{tool_id}/grants", headers=headers_for(org["viewer"]))
    assert empty.json() == []

    await client.post(
        f"/v1/agent-versions/{version_id}/capability-grants", json={"mcp_tool_id": tool_id}, headers=headers_for(org["builder"])
    )

    grants = await client.get(f"/v1/mcp-tools/{tool_id}/grants", headers=headers_for(org["viewer"]))
    assert len(grants.json()) == 1
    assert grants.json()[0]["agent_name"] == "grant-lookup-agent"
    assert grants.json()[0]["version_label"] == "1.0.0"


async def test_dashboard_summary_counts_production_and_candidate(client, org, headers_for):
    agent_id, version_id, fake_client = await _make_candidate_via_api(client, org, headers_for, "dashboard-agent")
    _wire_fake_client(fake_client)

    summary = await client.get("/v1/dashboard/summary", headers=headers_for(org["admin"]))
    assert summary.status_code == 200
    body = summary.json()
    assert body["counts"]["candidate_versions"] >= 1
    assert isinstance(body["needs_attention"], list)
    assert isinstance(body["recent_activity"], list)
    assert any(item["type"] == "stale_candidate" for item in body["needs_attention"]) is False  # freshly passed, not stale


async def test_dashboard_summary_requires_auth(client):
    resp = await client.get("/v1/dashboard/summary")
    assert resp.status_code == 401
