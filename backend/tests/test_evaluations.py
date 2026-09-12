"""Request-evaluation flow (app/services/evaluations.py) and the API layer wired
to it - permission checks, idempotency, dataset/evaluator resolution failures,
lifecycle transition to 'evaluating', and the 202 async-acceptance contract.
"""
import uuid

from app.dependencies import get_agent_eval_client, get_job_dispatcher
from app.main import app
from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator


class _RecordingNoOpDispatcher:
    """These tests exercise the REQUEST layer only (permission checks, dataset/
    evaluator resolution, idempotency, lifecycle transition on accept) - actual
    worker execution (agent-eval call, gate computation, completion) is fully
    covered by tests/test_evaluation_worker.py, which calls process_evaluation_job
    directly. Using LocalSyncDispatcher's real asyncio.create_task here would race
    the test's own assertions against a background task with no way to await it
    from outside - exactly the non-durability LocalSyncDispatcher's own docstring
    warns about, not something worth fighting in a test.
    """

    def __init__(self):
        self.dispatched_ids = []

    async def dispatch_evaluation_job(self, evaluation_run_reference_id):
        self.dispatched_ids.append(evaluation_run_reference_id)


def _wire_fake_client(client: FakeAgentEvalClient):
    app.dependency_overrides[get_agent_eval_client] = lambda: client
    app.dependency_overrides[get_job_dispatcher] = lambda: _RecordingNoOpDispatcher()


async def _make_agent_version(client, org, headers_for, name="eval-req-agent"):
    agent_resp = await client.post("/v1/agents", json={"name": name, "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"]))
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": name, "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {"servers": [], "tools": []}, "evaluation": {"policy": "test-policy"},
    }
    v_resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    return agent_id, v_resp.json()["id"]


async def _make_policy(client, org, headers_for, agent_name, dataset_key="fake-dataset", required_evaluator_keys=None):
    resp = await client.post(
        "/v1/evaluation-policies",
        json={
            "name": agent_name, "version": "v1", "thresholds": {},
            "required_evaluator_keys": required_evaluator_keys or {"completion_check": "v1"},
            "dataset_key": dataset_key,
        },
        headers=headers_for(org["admin"]),
    )
    return resp.json()


async def test_request_evaluation_success_returns_202_and_transitions_to_evaluating(client, org, headers_for):
    agent_name = "eval-success-agent"
    agent_id, version_id = await _make_agent_version(client, org, headers_for, agent_name)
    await _make_policy(client, org, headers_for, agent_name, dataset_key="fake-dataset")

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset("fake-dataset", dataset_id="ds-1")],
    )
    _wire_fake_client(fake)
    try:
        resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "ext-av-1"},
            headers=headers_for(org["builder"]),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "requested"  # dispatch is a separate, async step - see _RecordingNoOpDispatcher

        detail = await client.get(f"/v1/agent-versions/{version_id}", headers=headers_for(org["builder"]))
        assert detail.json()["stage"] == "evaluating"
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


async def test_request_evaluation_resolves_target_from_provenance_when_omitted(client, org, headers_for, db_session):
    """Phase 9: a normal user should never have to know or type an agent-eval
    UUID - app/services/evaluations.py::_resolve_external_agent_version_id.
    Simulates a CI-published version (real provenance, set at creation time -
    AgentVersion.provenance is write-once, same as every other column)."""
    from app.services import agents as agents_service

    agent_name = "eval-provenance-agent"
    agent = await agents_service.create_agent(
        db_session, actor=org["builder"], name=agent_name, team_id=org["team_a"].id, description=None
    )
    manifest = {
        "agent": {"name": agent_name, "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {"servers": [], "tools": []}, "evaluation": {"policy": "test-policy"},
    }
    version = await agents_service.create_agent_version(
        db_session,
        actor=org["builder"],
        agent_id=agent.id,
        manifest=manifest,
        via_ci=True,
        provenance={"git_repo": "org/repo", "git_commit_sha": "abc123", "agent_eval_agent_version_id": "resolved-target-1"},
    )
    version_id = str(version.id)
    await _make_policy(client, org, headers_for, agent_name, dataset_key="fake-dataset")

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset("fake-dataset", dataset_id="ds-1")],
    )
    _wire_fake_client(fake)
    try:
        resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={},
            headers=headers_for(org["builder"]),
        )
        assert resp.status_code == 202
        detail = await client.get(f"/v1/evaluations/{resp.json()['id']}", headers=headers_for(org["builder"]))
        assert detail.json()["external_agent_version_id"] == "resolved-target-1"
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


async def test_request_evaluation_with_no_target_and_no_provenance_is_meaningful_422(client, org, headers_for):
    """No raw foreign-ID plumbing error - a real, actionable product message."""
    agent_name = "eval-no-target-agent"
    agent_id, version_id = await _make_agent_version(client, org, headers_for, agent_name)
    await _make_policy(client, org, headers_for, agent_name, dataset_key="fake-dataset")

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset("fake-dataset", dataset_id="ds-1")],
    )
    _wire_fake_client(fake)
    try:
        resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations", json={}, headers=headers_for(org["builder"])
        )
        assert resp.status_code == 422
        assert "not been registered with Agent Eval" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


async def test_request_evaluation_forbidden_for_viewer(client, org, headers_for):
    agent_name = "eval-forbidden-agent"
    agent_id, version_id = await _make_agent_version(client, org, headers_for, agent_name)
    await _make_policy(client, org, headers_for, agent_name)

    resp = await client.post(
        f"/v1/agent-versions/{version_id}/evaluations",
        json={"external_agent_version_id": "ext-av-1"},
        headers=headers_for(org["viewer"]),
    )
    assert resp.status_code == 403


async def test_request_evaluation_with_no_policy_is_error(client, org, headers_for):
    agent_id, version_id = await _make_agent_version(client, org, headers_for, "no-policy-agent")
    resp = await client.post(
        f"/v1/agent-versions/{version_id}/evaluations",
        json={"external_agent_version_id": "ext-av-1"},
        headers=headers_for(org["builder"]),
    )
    assert resp.status_code == 404


async def test_request_evaluation_with_missing_dataset_is_422(client, org, headers_for):
    agent_name = "missing-dataset-agent"
    agent_id, version_id = await _make_agent_version(client, org, headers_for, agent_name)
    await _make_policy(client, org, headers_for, agent_name, dataset_key="nonexistent-dataset")

    fake = FakeAgentEvalClient(evaluators=[make_evaluator("completion_check", "v1")], datasets=[])
    _wire_fake_client(fake)
    try:
        resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "ext-av-1"},
            headers=headers_for(org["builder"]),
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


async def test_request_evaluation_with_wrong_evaluator_version_is_422(client, org, headers_for):
    agent_name = "wrong-evaluator-agent"
    agent_id, version_id = await _make_agent_version(client, org, headers_for, agent_name)
    await _make_policy(
        client, org, headers_for, agent_name, dataset_key="fake-dataset",
        required_evaluator_keys={"completion_check": "v2"},  # policy wants v2
    )

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],  # catalog only has v1
        datasets=[make_dataset("fake-dataset", dataset_id="ds-1")],
    )
    _wire_fake_client(fake)
    try:
        resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "ext-av-1"},
            headers=headers_for(org["builder"]),
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


async def test_idempotency_key_returns_existing_reference_not_a_duplicate(client, org, headers_for):
    agent_name = "idempotent-agent"
    agent_id, version_id = await _make_agent_version(client, org, headers_for, agent_name)
    await _make_policy(client, org, headers_for, agent_name, dataset_key="fake-dataset")

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset("fake-dataset", dataset_id="ds-1")],
    )
    _wire_fake_client(fake)
    try:
        key = str(uuid.uuid4())
        first = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "ext-av-1", "idempotency_key": key},
            headers=headers_for(org["builder"]),
        )
        second = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "ext-av-1", "idempotency_key": key},
            headers=headers_for(org["builder"]),
        )
        assert first.json()["id"] == second.json()["id"]
        assert len(fake.trigger_calls) <= 1  # the second request must not re-trigger a run
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


async def test_cannot_request_evaluation_for_candidate_version(client, org, headers_for, db_session):
    """Once a version reaches candidate/production/retired, a fresh evaluation
    request is rejected - fix means a new AgentVersion, per
    docs/evaluation-and-promotion.md's lifecycle rules."""
    import uuid as _uuid

    from app.models.agent import AgentVersionLifecycle
    from app.models.enums import Stage
    from sqlalchemy import select

    agent_name = "already-candidate-agent"
    agent_id, version_id = await _make_agent_version(client, org, headers_for, agent_name)
    await _make_policy(client, org, headers_for, agent_name)

    lifecycle = (
        await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == _uuid.UUID(version_id)))
    ).scalar_one()
    lifecycle.stage = Stage.EVALUATED
    await db_session.commit()

    resp = await client.post(
        f"/v1/agent-versions/{version_id}/evaluations",
        json={"external_agent_version_id": "ext-av-1"},
        headers=headers_for(org["builder"]),
    )
    assert resp.status_code == 409
