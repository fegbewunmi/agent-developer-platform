"""Public demo sandbox (Phase 7) - app/services/demo.py, the demo_containment_ok
addition to app/services/permissions.py, and the rate-limit/safe-target
guardrails in app/services/evaluations.py. The core property under test: a
demo-team actor (Builder OR Reviewer - elevated roles normally bypass team
checks entirely, see permissions.py's docstring) can never write to a
non-demo Agent, and a real Orion actor never sees demo entities in the
curated dashboard/reviewer-queue views.
"""
import uuid

import pytest_asyncio

from app.config import settings
from app.dependencies import get_agent_eval_client, get_job_dispatcher
from app.main import app
from app.models.enums import PromotionRequestStatus, Role
from app.models.identity import Team, User
from app.services import demo as demo_service
from app.services import permissions
from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator


@pytest_asyncio.fixture
async def demo_org(db_session, org):
    """A dedicated demo team with its own Builder/Reviewer, separate from
    org's team_a/team_b - and settings.demo_team_id pointed at it, exactly
    like the real deployed configuration."""
    demo_team = Team(id=uuid.uuid4(), name=f"Public Demo-{uuid.uuid4().hex[:8]}", slack_channel=None)
    db_session.add(demo_team)
    await db_session.flush()

    demo_builder = User(
        id=uuid.uuid4(), name="Demo Builder", email=f"demo-builder-{uuid.uuid4().hex[:8]}@demo.example",
        team_id=demo_team.id, role=Role.BUILDER,
    )
    demo_reviewer = User(
        id=uuid.uuid4(), name="Demo Reviewer", email=f"demo-reviewer-{uuid.uuid4().hex[:8]}@demo.example",
        team_id=demo_team.id, role=Role.REVIEWER,
    )
    db_session.add_all([demo_builder, demo_reviewer])
    await db_session.commit()

    return {**org, "demo_team": demo_team, "demo_builder": demo_builder, "demo_reviewer": demo_reviewer}


def _with_demo_team(monkeypatch, demo_org):
    monkeypatch.setattr(settings, "demo_team_id", str(demo_org["demo_team"].id))


# --- pure permission-layer tests -------------------------------------------------


def test_is_demo_actor_false_when_not_configured(monkeypatch, org):
    monkeypatch.setattr(settings, "demo_team_id", None)
    assert permissions.is_demo_actor(org["builder"]) is False


def test_demo_containment_ok_is_noop_for_real_users(monkeypatch, demo_org):
    _with_demo_team(monkeypatch, demo_org)
    # A real Orion admin acting on a real Orion team's agent - unaffected.
    assert permissions.demo_containment_ok(demo_org["admin"], demo_org["team_a"].id) is True
    # Even a real Reviewer reaching across teams (the normal, intended
    # elevated-role behavior, ADR-0010) is unaffected - this check only
    # ever constrains demo-team actors.
    assert permissions.demo_containment_ok(demo_org["reviewer"], demo_org["team_b"].id) is True


def test_demo_containment_blocks_demo_reviewer_on_real_team(monkeypatch, demo_org):
    _with_demo_team(monkeypatch, demo_org)
    # The gap this feature exists to close: a Reviewer role normally bypasses
    # the team check entirely (can_decide_promotion has no team_id param at
    # all). demo_containment_ok is the additive guard that still stops it.
    assert permissions.demo_containment_ok(demo_org["demo_reviewer"], demo_org["team_a"].id) is False
    assert permissions.demo_containment_ok(demo_org["demo_reviewer"], demo_org["demo_team"].id) is True


# --- service/API-layer containment ------------------------------------------------


async def test_demo_builder_cannot_create_version_for_real_agent(monkeypatch, client, demo_org, headers_for):
    _with_demo_team(monkeypatch, demo_org)
    agent_resp = await client.post(
        "/v1/agents",
        json={"name": f"real-agent-{uuid.uuid4().hex[:8]}", "team_id": str(demo_org["team_a"].id)},
        headers=headers_for(demo_org["builder"]),
    )
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": "x", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {}, "evaluation": {"policy": "test-policy"},
    }
    resp = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(demo_org["demo_builder"])
    )
    assert resp.status_code == 403


async def test_demo_reviewer_cannot_approve_real_promotion_request(monkeypatch, client, demo_org, headers_for):
    _with_demo_team(monkeypatch, demo_org)
    agent_name = f"real-agent-{uuid.uuid4().hex[:8]}"
    agent_resp = await client.post(
        "/v1/agents", json={"name": agent_name, "team_id": str(demo_org["team_a"].id)}, headers=headers_for(demo_org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    await client.post(
        "/v1/evaluation-policies",
        json={
            "name": agent_name, "version": "v1", "thresholds": {},
            "required_evaluator_keys": {"completion_check": "v1"}, "dataset_key": "fake-dataset",
        },
        headers=headers_for(demo_org["admin"]),
    )
    manifest = {
        "agent": {"name": agent_name, "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {}, "evaluation": {"policy": agent_name},
    }
    v_resp = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(demo_org["builder"])
    )
    version_id = v_resp.json()["id"]

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")], datasets=[make_dataset("fake-dataset", dataset_id="ds-1")]
    )
    app.dependency_overrides[get_agent_eval_client] = lambda: fake

    class _Dispatcher:
        async def dispatch_evaluation_job(self, ref_id):
            from app.services.evaluation_worker import process_evaluation_job

            await process_evaluation_job(ref_id, fake)

    app.dependency_overrides[get_job_dispatcher] = lambda: _Dispatcher()
    try:
        eval_resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "ext-av-1"},
            headers=headers_for(demo_org["builder"]),
        )
        assert eval_resp.status_code == 202

        promo_resp = await client.post(
            f"/v1/agent-versions/{version_id}/promotion-requests",
            json={"reason": "ready"},
            headers=headers_for(demo_org["builder"]),
        )
        assert promo_resp.status_code == 201, promo_resp.text
        request_id = promo_resp.json()["id"]

        # The demo Reviewer is a real Reviewer role (elevated - normally can
        # decide ANY team's request). demo_containment_ok must still block it.
        decide_resp = await client.post(
            f"/v1/promotion-requests/{request_id}/approve", json={}, headers=headers_for(demo_org["demo_reviewer"])
        )
        assert decide_resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


# --- evaluation rate-limit / safe-target guardrails -------------------------------


async def test_demo_evaluation_rejects_non_designated_external_target(monkeypatch, client, demo_org, headers_for, db_session):
    _with_demo_team(monkeypatch, demo_org)
    monkeypatch.setattr(settings, "demo_external_agent_version_id", "the-only-safe-target")

    agent_name = f"demo-agent-{uuid.uuid4().hex[:8]}"
    agent_resp = await client.post(
        "/v1/agents", json={"name": agent_name, "team_id": str(demo_org["demo_team"].id)}, headers=headers_for(demo_org["demo_builder"])
    )
    agent_id = agent_resp.json()["id"]
    await client.post(
        "/v1/evaluation-policies",
        json={
            "name": agent_name, "version": "v1", "thresholds": {},
            "required_evaluator_keys": {"completion_check": "v1"}, "dataset_key": "fake-dataset",
        },
        headers=headers_for(demo_org["admin"]),
    )
    manifest = {
        "agent": {"name": agent_name, "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [], "mcp": {}, "evaluation": {"policy": agent_name},
    }
    v_resp = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(demo_org["demo_builder"])
    )
    version_id = v_resp.json()["id"]

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")], datasets=[make_dataset("fake-dataset", dataset_id="ds-1")]
    )
    app.dependency_overrides[get_agent_eval_client] = lambda: fake
    app.dependency_overrides[get_job_dispatcher] = lambda: _NoOpDispatcher()
    try:
        resp = await client.post(
            f"/v1/agent-versions/{version_id}/evaluations",
            json={"external_agent_version_id": "some-other-target"},
            headers=headers_for(demo_org["demo_builder"]),
        )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


class _NoOpDispatcher:
    async def dispatch_evaluation_job(self, ref_id):
        pass


async def test_demo_evaluation_cooldown_rejects_rapid_resubmission(monkeypatch, client, demo_org, headers_for):
    _with_demo_team(monkeypatch, demo_org)
    monkeypatch.setattr(settings, "demo_eval_cooldown_seconds", 3600)  # generous, deterministic

    agent_name = f"demo-agent-{uuid.uuid4().hex[:8]}"
    agent_resp = await client.post(
        "/v1/agents", json={"name": agent_name, "team_id": str(demo_org["demo_team"].id)}, headers=headers_for(demo_org["demo_builder"])
    )
    agent_id = agent_resp.json()["id"]
    await client.post(
        "/v1/evaluation-policies",
        json={
            "name": agent_name, "version": "v1", "thresholds": {},
            "required_evaluator_keys": {"completion_check": "v1"}, "dataset_key": "fake-dataset",
        },
        headers=headers_for(demo_org["admin"]),
    )

    async def _new_draft(label):
        manifest = {
            "agent": {"name": agent_name, "version": label, "framework": "langgraph"},
            "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
            "skills": [], "mcp": {}, "evaluation": {"policy": agent_name},
        }
        r = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(demo_org["demo_builder"]))
        return r.json()["id"]

    v1 = await _new_draft("1.0.0")
    v2 = await _new_draft("1.0.1")

    fake = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")], datasets=[make_dataset("fake-dataset", dataset_id="ds-1")]
    )
    app.dependency_overrides[get_agent_eval_client] = lambda: fake
    app.dependency_overrides[get_job_dispatcher] = lambda: _NoOpDispatcher()
    try:
        first = await client.post(
            f"/v1/agent-versions/{v1}/evaluations", json={"external_agent_version_id": "ext-1"}, headers=headers_for(demo_org["demo_builder"])
        )
        assert first.status_code == 202

        second = await client.post(
            f"/v1/agent-versions/{v2}/evaluations", json={"external_agent_version_id": "ext-1"}, headers=headers_for(demo_org["demo_builder"])
        )
        assert second.status_code == 409
    finally:
        app.dependency_overrides.pop(get_agent_eval_client, None)
        app.dependency_overrides.pop(get_job_dispatcher, None)


# --- reset ---------------------------------------------------------------------


async def test_reset_closes_stale_pending_request_and_creates_fresh_draft(monkeypatch, db_session, demo_org):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
    from app.models.enums import Stage
    from app.models.evaluation import EvaluationGateResult, EvaluationRunReference
    from app.models.promotion import PromotionRequest
    from app.services import agents as agents_service
    from app.services import evaluation_policies as policies_service

    _with_demo_team(monkeypatch, demo_org)

    agent = await agents_service.create_agent(
        db_session, actor=demo_org["admin"], name=f"demo-agent-{uuid.uuid4().hex[:8]}", team_id=demo_org["demo_team"].id, description=None
    )
    await policies_service.create_evaluation_policy(
        db_session, actor=demo_org["admin"], name=agent.name, version="v1", thresholds={},
        required_evaluator_keys={"completion_check": "v1"}, dataset_key="fake-dataset",
    )
    version = await agents_service.create_agent_version(
        db_session,
        actor=demo_org["demo_builder"],
        agent_id=agent.id,
        manifest={
            "agent": {"name": agent.name, "version": "1.0.0", "framework": "langgraph"},
            "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
            "skills": [], "mcp": {}, "evaluation": {"policy": agent.name},
        },
    )

    # Manufacture a stale pending PromotionRequest directly (bypassing the
    # real request_promotion flow, which would require a real passing
    # evaluation first - irrelevant to what reset is testing).
    lifecycle = (
        await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version.id))
    ).scalar_one()
    lifecycle.stage = Stage.CANDIDATE
    reference = EvaluationRunReference(
        id=uuid.uuid4(), agent_version_id=version.id, evaluation_policy_id=(await policies_service.get_current_policy_for_agent(db_session, agent.name)).id,
        external_agent_version_id="ext-1", external_dataset_id="ds-1", requested_by=demo_org["demo_builder"].id,
        status="completed", capability_grant_snapshot_hash="sha256:x",
    )
    db_session.add(reference)
    await db_session.flush()
    stale_request = PromotionRequest(
        id=uuid.uuid4(), agent_version_id=version.id, from_stage=Stage.CANDIDATE, to_stage=Stage.PRODUCTION,
        requested_by=demo_org["demo_builder"].id, evaluation_run_reference_id=reference.id,
        evaluation_policy_id=reference.evaluation_policy_id, capability_grant_snapshot_hash="sha256:x",
        status=PromotionRequestStatus.PENDING,
        requested_at=datetime.now(timezone.utc) - timedelta(hours=5),
    )
    db_session.add(stale_request)
    await db_session.commit()

    fake = FakeAgentEvalClient(evaluators=[make_evaluator("completion_check", "v1")], datasets=[make_dataset("fake-dataset", dataset_id="ds-1")])
    result = await demo_service.reset_demo_environment(db_session, fake)

    assert str(stale_request.id) in result["closed_stale_requests"]
    await db_session.refresh(stale_request)
    assert stale_request.status == PromotionRequestStatus.REJECTED

    assert result["new_draft_version_label"].startswith("sandbox-")
    fresh = (
        await db_session.execute(select(AgentVersion).where(AgentVersion.id == uuid.UUID(result["new_draft_version_id"])))
    ).scalar_one()
    assert fresh.agent_id == agent.id
