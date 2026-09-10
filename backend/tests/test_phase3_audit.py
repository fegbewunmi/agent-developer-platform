"""Audit coverage specific to Phase 3 writes - docs/audit-model.md's transactional
guarantee extended to evaluation_policy.created and evaluation.requested, plus the
event types already proven in test_evaluation_worker.py
(evaluation.completed/failed, agent_version.became_candidate).
"""
import uuid

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.evaluation import EvaluationPolicy


async def test_evaluation_policy_created_emits_audit_event(db_session, org):
    from app.services.evaluation_policies import create_evaluation_policy

    policy = await create_evaluation_policy(
        db_session, actor=org["admin"], name="audit-policy-test", version="v1",
        thresholds={}, required_evaluator_keys={"x": "v1"}, dataset_key="ds",
    )

    events = (
        await db_session.execute(select(AuditEvent.event_type).where(AuditEvent.entity_id == policy.id))
    ).scalars().all()
    assert events == ["evaluation_policy.created"]


async def test_evaluation_policy_creation_rolls_back_if_audit_fails(db_session, org, monkeypatch):
    import app.services.evaluation_policies as policies_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(policies_module, "record_audit_event", _boom)

    try:
        await policies_module.create_evaluation_policy(
            db_session, actor=org["admin"], name="rollback-policy-test", version="v1",
            thresholds={}, required_evaluator_keys={"x": "v1"}, dataset_key="ds",
        )
        assert False, "expected the simulated audit failure to propagate"
    except RuntimeError:
        pass

    await db_session.rollback()

    result = await db_session.execute(select(EvaluationPolicy).where(EvaluationPolicy.name == "rollback-policy-test"))
    assert result.scalar_one_or_none() is None


async def test_evaluation_requested_emits_audit_event(client, org, headers_for, db_session):
    from app.dependencies import get_agent_eval_client, get_job_dispatcher
    from app.main import app
    from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator

    agent_resp = await client.post(
        "/v1/agents", json={"name": "audit-eval-req-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": "audit-eval-req-agent", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {"servers": [], "tools": []}, "evaluation": {"policy": "x"},
    }
    v_resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    version_id = v_resp.json()["id"]

    await client.post(
        "/v1/evaluation-policies",
        json={
            "name": "audit-eval-req-agent", "version": "v1", "thresholds": {},
            "required_evaluator_keys": {"completion_check": "v1"}, "dataset_key": "fake-dataset",
        },
        headers=headers_for(org["admin"]),
    )

    class _NoOpDispatcher:
        async def dispatch_evaluation_job(self, reference_id):
            pass

    fake = FakeAgentEvalClient(evaluators=[make_evaluator("completion_check", "v1")], datasets=[make_dataset("fake-dataset", dataset_id="ds-1")])
    app.dependency_overrides[get_agent_eval_client] = lambda: fake
    app.dependency_overrides[get_job_dispatcher] = lambda: _NoOpDispatcher()
    try:
        resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "ext-1"},
            headers=headers_for(org["builder"]),
        )
        assert resp.status_code == 202
        reference_id = resp.json()["id"]
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)

    events = (
        await db_session.execute(select(AuditEvent.event_type).where(AuditEvent.entity_id == uuid.UUID(reference_id)))
    ).scalars().all()
    assert events == ["evaluation.requested"]
