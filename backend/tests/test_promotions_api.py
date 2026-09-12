"""HTTP-layer wiring for app/api/promotions.py - confirms routes, status
codes, DI overrides, and the DomainError -> HTTP status mapping actually work
over a real request, not just at the service layer (tests/test_promotions.py
covers the service layer's full behavior in detail).
"""
import uuid

from app.dependencies import get_agent_eval_client, get_event_publisher, get_job_dispatcher
from app.main import app
from app.services.event_publisher import LocalNoopPublisher
from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator


class _RecordingNoOpDispatcher:
    """Same reasoning as tests/test_evaluations.py's dispatcher double: this
    test drives evaluation completion explicitly via a direct
    process_evaluation_job(...) call against our fake client, so the real
    dispatch path must not also fire in the background - it would use the
    lru_cache'd real HttpAgentEvalClient (unrelated to our fake) and race our
    explicit call for the same DB rows, which is exactly what caused a real
    hang here (two concurrent writers contending for the same row lock)."""

    async def dispatch_evaluation_job(self, evaluation_run_reference_id):
        pass


def _wire_fake_client(fake_client: FakeAgentEvalClient):
    app.dependency_overrides[get_agent_eval_client] = lambda: fake_client
    app.dependency_overrides[get_event_publisher] = lambda: LocalNoopPublisher()
    app.dependency_overrides[get_job_dispatcher] = lambda: _RecordingNoOpDispatcher()


async def _make_candidate_version_via_api(client, org, headers_for, name):
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
        f"/v1/agent-versions/{version_id}/evaluations",
        json={"external_agent_version_id": f"ext-{version_id}"},
        headers=headers_for(org["builder"]),
    )
    assert eval_resp.status_code == 202
    reference_id = eval_resp.json()["id"]

    from app.services.evaluation_worker import process_evaluation_job

    await process_evaluation_job(uuid.UUID(reference_id), fake_client)

    return agent_id, version_id, fake_client


async def test_promotion_full_flow_via_api(client, org, headers_for):
    agent_id, version_id, fake_client = await _make_candidate_version_via_api(client, org, headers_for, "api-promo-agent")

    request_resp = await client.post(
        f"/v1/agent-versions/{version_id}/promotion-requests", json={"reason": "ship it"}, headers=headers_for(org["builder"])
    )
    assert request_resp.status_code == 201, request_resp.text
    body = request_resp.json()
    assert body["status"] == "pending"
    assert body["from_stage"] == "evaluated"
    request_id = body["id"]

    approve_resp = await client.post(
        f"/v1/promotion-requests/{request_id}/approve", json={"comment": "lgtm"}, headers=headers_for(org["reviewer"])
    )
    assert approve_resp.status_code == 201, approve_resp.text
    assert approve_resp.json()["decision"] == "approve"

    get_resp = await client.get(f"/v1/promotion-requests/{request_id}", headers=headers_for(org["admin"]))
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "approved"
    assert get_resp.json()["decision"]["decision"] == "approve"

    version_detail = await client.get(f"/v1/agent-versions/{version_id}", headers=headers_for(org["admin"]))
    assert version_detail.json()["stage"] == "recommended"

    history_resp = await client.get(f"/v1/agents/{agent_id}/promotion-history", headers=headers_for(org["admin"]))
    assert history_resp.status_code == 200
    assert len(history_resp.json()) == 1


async def test_promotion_self_approval_returns_403_via_api(client, org, headers_for):
    agent_id, version_id, fake_client = await _make_candidate_version_via_api(client, org, headers_for, "api-self-approve")

    request_resp = await client.post(
        f"/v1/agent-versions/{version_id}/promotion-requests", json={}, headers=headers_for(org["reviewer"])
    )
    request_id = request_resp.json()["id"]

    approve_resp = await client.post(
        f"/v1/promotion-requests/{request_id}/approve", json={}, headers=headers_for(org["reviewer"])
    )
    assert approve_resp.status_code == 403


async def test_promotion_viewer_cannot_request_via_api(client, org, headers_for):
    agent_id, version_id, fake_client = await _make_candidate_version_via_api(client, org, headers_for, "api-viewer-req")

    request_resp = await client.post(
        f"/v1/agent-versions/{version_id}/promotion-requests", json={}, headers=headers_for(org["viewer"])
    )
    assert request_resp.status_code == 403


async def test_promotion_rejection_via_api_leaves_candidate(client, org, headers_for):
    agent_id, version_id, fake_client = await _make_candidate_version_via_api(client, org, headers_for, "api-reject")

    request_resp = await client.post(
        f"/v1/agent-versions/{version_id}/promotion-requests", json={}, headers=headers_for(org["builder"])
    )
    request_id = request_resp.json()["id"]

    reject_resp = await client.post(
        f"/v1/promotion-requests/{request_id}/reject", json={"comment": "needs more work"}, headers=headers_for(org["reviewer"])
    )
    assert reject_resp.status_code == 201
    assert reject_resp.json()["decision"] == "reject"

    version_detail = await client.get(f"/v1/agent-versions/{version_id}", headers=headers_for(org["admin"]))
    assert version_detail.json()["stage"] == "evaluated"


async def test_promotion_requires_auth(client):
    resp = await client.post(f"/v1/agent-versions/{uuid.uuid4()}/promotion-requests", json={})
    assert resp.status_code in (401, 403)
