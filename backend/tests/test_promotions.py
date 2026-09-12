"""app/services/promotions.py - request/approve/reject, decision-time freshness
re-checks, rollback, and the concurrency backstop. Mirrors
tests/test_freshness.py's setup shape (a real passing evaluation, run through
the real worker) so promotion tests exercise the same candidate-producing path
production code does, not a hand-faked lifecycle row.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.integrations.agent_eval_client import DimensionStat
from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.audit import AuditEvent
from app.models.enums import MCPClassification, PromotionRequestStatus, Stage
from app.models.mcp import AgentCapabilityGrant, MCPServer, MCPTool
from app.models.outbox import OutboxEvent
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.services.evaluation_policies import create_evaluation_policy
from app.services.evaluation_worker import process_evaluation_job
from app.services.event_publisher import LocalNoopPublisher
from app.services import promotions as promotions_service
from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator


async def _setup_candidate(db_session, org, agent_name: str, version_label: str = "1.0.0"):
    """Builds a real Agent + AgentVersion, runs a real (fake-backed) passing
    evaluation through the actual worker, landing at stage=candidate - the
    same production code path Phase 3 exercises, not a hand-set lifecycle row.
    Returns (agent, version, client) - reuse the same `client` across calls in
    a test so its catalog/dataset stay consistent (keeping the version
    currently_eligible) unless a test deliberately mutates it to go stale.
    """
    agent = Agent(id=uuid.uuid4(), name=agent_name, team_id=org["team_a"].id)
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version_label=version_label, manifest={},
        content_hash=f"hash-{version_label}", created_by=org["builder"].id,
    )
    db_session.add(version)
    await db_session.flush()
    lifecycle = AgentVersionLifecycle(agent_version_id=version.id, agent_id=agent.id, stage=Stage.EVALUATING, entered_by=org["builder"].id)
    db_session.add(lifecycle)
    policy = await create_evaluation_policy(
        db_session, actor=org["admin"], name=agent_name, version="v1",
        thresholds={}, required_evaluator_keys={"completion_check": "v1"}, dataset_key=f"dataset-{agent_name}",
    )
    await db_session.commit()

    from app.models.evaluation import EvaluationRunReference
    from app.models.enums import EvaluationRunStatus
    from app.services.evidence_snapshot import take_capability_grant_snapshot

    snapshot = await take_capability_grant_snapshot(db_session, version.id)
    reference = EvaluationRunReference(
        id=uuid.uuid4(), agent_version_id=version.id, evaluation_policy_id=policy.id,
        external_agent_version_id=f"ext-{version.id}", external_dataset_id=f"ds-{agent_name}",
        external_evaluator_ids={"ids": ["e1"], "versions": {"completion_check": "v1"}},
        requested_by=org["builder"].id, status=EvaluationRunStatus.REQUESTED,
        capability_grant_snapshot_hash=snapshot.hash, capability_grant_snapshot=snapshot.snapshot,
    )
    db_session.add(reference)
    await db_session.commit()
    reference_id, version_id = reference.id, version.id

    client = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset(f"dataset-{agent_name}", cases=[{"key": "c1", "tags": []}], dataset_id=f"ds-{agent_name}")],
    )
    client.next_run_dimension_stats = [DimensionStat(dimension="completion", mean_score=1.0, n=1, n_not_applicable=0)]
    await process_evaluation_job(reference_id, client)
    db_session.expire(reference)
    db_session.expire(lifecycle)

    return agent, version, client


async def test_request_promotion_happy_path(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "req-happy")

    request = await promotions_service.request_promotion(
        db_session, client, actor=org["builder"], agent_version_id=version.id, reason="ready to ship"
    )

    assert request.status == PromotionRequestStatus.PENDING
    assert request.from_stage == Stage.EVALUATED
    assert request.to_stage == Stage.RECOMMENDED
    assert request.evaluation_policy_id is not None
    assert request.capability_grant_snapshot_hash is not None
    assert request.production_version_id_at_request is None  # nothing in production yet
    assert request.freshness_snapshot["currently_eligible"] is True
    assert request.reason == "ready to ship"


async def test_request_promotion_blocked_when_not_candidate_or_retired(db_session, org):
    agent = Agent(id=uuid.uuid4(), name="draft-agent", team_id=org["team_a"].id)
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(id=uuid.uuid4(), agent_id=agent.id, version_label="1.0.0", manifest={}, content_hash="h", created_by=org["builder"].id)
    db_session.add(version)
    await db_session.flush()
    db_session.add(AgentVersionLifecycle(agent_version_id=version.id, agent_id=agent.id, stage=Stage.DRAFT, entered_by=org["builder"].id))
    await db_session.commit()

    client = FakeAgentEvalClient()
    with pytest.raises(ConflictError, match="draft"):
        await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)


async def test_request_promotion_blocked_when_stale(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "req-stale")
    client.evaluators = []  # required evaluator vanishes from the live catalog -> stale

    with pytest.raises(ConflictError, match="not currently eligible"):
        await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)


async def test_request_promotion_rejects_duplicate_pending(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "req-dup")
    await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)

    with pytest.raises(ConflictError, match="already has a pending"):
        await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)


async def test_request_promotion_viewer_forbidden(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "req-viewer")
    with pytest.raises(PermissionDeniedError):
        await promotions_service.request_promotion(db_session, client, actor=org["viewer"], agent_version_id=version.id)


async def test_request_promotion_other_team_builder_forbidden(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "req-cross-team")
    with pytest.raises(PermissionDeniedError):
        await promotions_service.request_promotion(
            db_session, client, actor=org["other_team_builder"], agent_version_id=version.id
        )


async def test_approve_promotion_happy_path(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "approve-happy")
    request = await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)

    publisher = LocalNoopPublisher()
    decision = await promotions_service.approve_promotion(
        db_session, client, publisher, actor=org["reviewer"], promotion_request_id=request.id, comment="looks good"
    )

    assert decision.decision.value == "approve"
    assert decision.freshness_snapshot_at_decision["currently_eligible"] is True

    await db_session.refresh(request)
    assert request.status == PromotionRequestStatus.APPROVED

    lifecycle = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version.id))).scalar_one()
    assert lifecycle.stage == Stage.RECOMMENDED

    events = (await db_session.execute(select(AuditEvent).where(AuditEvent.entity_id == version.id))).scalars().all()
    event_types = {e.event_type for e in events}
    assert "agent_version.promoted" in event_types

    outbox_rows = (await db_session.execute(select(OutboxEvent).where(OutboxEvent.entity_id == version.id))).scalars().all()
    assert len(outbox_rows) == 1
    assert outbox_rows[0].published_at is not None  # LocalNoopPublisher marks it published


async def test_approve_promotion_self_approval_forbidden(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "approve-self")
    request = await promotions_service.request_promotion(db_session, client, actor=org["reviewer"], agent_version_id=version.id)

    publisher = LocalNoopPublisher()
    with pytest.raises(PermissionDeniedError):
        await promotions_service.approve_promotion(
            db_session, client, publisher, actor=org["reviewer"], promotion_request_id=request.id
        )


async def test_approve_promotion_builder_forbidden(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "approve-builder")
    request = await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)

    publisher = LocalNoopPublisher()
    with pytest.raises(PermissionDeniedError):
        await promotions_service.approve_promotion(
            db_session, client, publisher, actor=org["builder"], promotion_request_id=request.id
        )


async def test_reject_promotion_by_unauthorized_user_forbidden(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "reject-unauth")
    request = await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)

    with pytest.raises(PermissionDeniedError):
        await promotions_service.reject_promotion(db_session, client, actor=org["viewer"], promotion_request_id=request.id)


async def test_approve_promotion_blocked_by_stale_evidence_no_production_mutation(db_session, org):
    """The core stale-block demo: evidence goes stale AFTER the request was
    filed (fresh at request time) but BEFORE it's decided - approval must be
    blocked, and the version must NOT become production."""
    agent, version, client = await _setup_candidate(db_session, org, "approve-stale")
    request = await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)
    assert request.freshness_snapshot["currently_eligible"] is True

    # Revoke evidence freshness by granting a new capability after the request
    # was filed - changes the capability-grant snapshot hash.
    server = MCPServer(id=uuid.uuid4(), name=f"srv-{uuid.uuid4().hex[:8]}", environment="development", owner_team_id=org["team_a"].id, connection_ref="http://x")
    db_session.add(server)
    await db_session.flush()
    tool = MCPTool(id=uuid.uuid4(), mcp_server_id=server.id, name="new_tool", classification=MCPClassification.READ)
    db_session.add(tool)
    await db_session.flush()
    db_session.add(AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version.id, mcp_tool_id=tool.id, granted_by=org["builder"].id))
    await db_session.commit()

    publisher = LocalNoopPublisher()
    with pytest.raises(ConflictError, match="no longer eligible"):
        await promotions_service.approve_promotion(
            db_session, client, publisher, actor=org["reviewer"], promotion_request_id=request.id
        )

    await db_session.refresh(request)
    assert request.status == PromotionRequestStatus.PENDING  # unchanged - still pending, not auto-rejected

    lifecycle = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version.id))).scalar_one()
    assert lifecycle.stage == Stage.EVALUATED  # no production mutation happened

    blocked_events = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.event_type == "promotion.approval_blocked_stale"))
    ).scalars().all()
    assert len(blocked_events) == 1


async def test_approve_promotion_already_decided_is_conflict(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "approve-twice")
    request = await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)
    publisher = LocalNoopPublisher()
    await promotions_service.approve_promotion(db_session, client, publisher, actor=org["reviewer"], promotion_request_id=request.id)

    with pytest.raises(ConflictError, match="already been decided"):
        await promotions_service.approve_promotion(db_session, client, publisher, actor=org["admin"], promotion_request_id=request.id)


async def test_reject_promotion_leaves_candidate_in_candidate(db_session, org):
    agent, version, client = await _setup_candidate(db_session, org, "reject-stays-candidate")
    request = await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)

    decision = await promotions_service.reject_promotion(
        db_session, client, actor=org["reviewer"], promotion_request_id=request.id, comment="not ready"
    )
    assert decision.decision.value == "reject"

    await db_session.refresh(request)
    assert request.status == PromotionRequestStatus.REJECTED

    lifecycle = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version.id))).scalar_one()
    assert lifecycle.stage == Stage.EVALUATED  # unchanged - no candidate -> draft edge exists

    # A fresh request can be filed once the rejected one is no longer pending.
    second_request = await promotions_service.request_promotion(db_session, client, actor=org["builder"], agent_version_id=version.id)
    assert second_request.id != request.id
    assert second_request.status == PromotionRequestStatus.PENDING


async def test_rollback_full_history_preserved(db_session, org):
    """v1 -> production, v2 -> production (v1 retired), rollback: promote v1
    again (now from stage=retired) -> v1 production, v2 retired. Full
    PromotionRequest/PromotionDecision history for both versions survives
    unmodified throughout."""
    agent = Agent(id=uuid.uuid4(), name="rollback-agent", team_id=org["team_a"].id)
    db_session.add(agent)
    await db_session.flush()
    await db_session.commit()

    # One shared policy for both versions - a second policy version would
    # make v1's already-recorded evidence "policy_changed"-stale, which is a
    # different scenario than this test is about.
    policy = await create_evaluation_policy(
        db_session, actor=org["admin"], name="rollback-agent", version="v1",
        thresholds={}, required_evaluator_keys={"completion_check": "v1"}, dataset_key="rollback-dataset",
    )
    await db_session.commit()

    async def _candidate_version(label, dataset_cases_suffix):
        version = AgentVersion(id=uuid.uuid4(), agent_id=agent.id, version_label=label, manifest={}, content_hash=f"hash-{label}", created_by=org["builder"].id)
        db_session.add(version)
        await db_session.flush()
        lifecycle = AgentVersionLifecycle(agent_version_id=version.id, agent_id=agent.id, stage=Stage.EVALUATING, entered_by=org["builder"].id)
        db_session.add(lifecycle)
        await db_session.commit()

        from app.models.evaluation import EvaluationRunReference
        from app.models.enums import EvaluationRunStatus
        from app.services.evidence_snapshot import take_capability_grant_snapshot

        snapshot = await take_capability_grant_snapshot(db_session, version.id)
        reference = EvaluationRunReference(
            id=uuid.uuid4(), agent_version_id=version.id, evaluation_policy_id=policy.id,
            external_agent_version_id=f"ext-{version.id}", external_dataset_id="ds-rollback",
            external_evaluator_ids={"ids": ["e1"], "versions": {"completion_check": "v1"}},
            requested_by=org["builder"].id, status=EvaluationRunStatus.REQUESTED,
            capability_grant_snapshot_hash=snapshot.hash, capability_grant_snapshot=snapshot.snapshot,
        )
        db_session.add(reference)
        await db_session.commit()

        client = FakeAgentEvalClient(
            evaluators=[make_evaluator("completion_check", "v1")],
            datasets=[make_dataset("rollback-dataset", cases=[{"key": "c1", "tags": []}], dataset_id="ds-rollback")],
        )
        client.next_run_dimension_stats = [DimensionStat(dimension="completion", mean_score=1.0, n=1, n_not_applicable=0)]
        await process_evaluation_job(reference.id, client)
        db_session.expire(reference)
        db_session.expire(lifecycle)
        return version, client

    v1, client1 = await _candidate_version("1.0.0", "v1")
    v2, client2 = await _candidate_version("2.0.0", "v2")

    publisher = LocalNoopPublisher()

    req1 = await promotions_service.request_promotion(db_session, client1, actor=org["builder"], agent_version_id=v1.id)
    await promotions_service.approve_promotion(db_session, client1, publisher, actor=org["reviewer"], promotion_request_id=req1.id)

    lifecycle_v1 = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == v1.id))).scalar_one()
    assert lifecycle_v1.stage == Stage.RECOMMENDED

    req2 = await promotions_service.request_promotion(db_session, client2, actor=org["builder"], agent_version_id=v2.id)
    assert req2.production_version_id_at_request == v1.id
    await promotions_service.approve_promotion(db_session, client2, publisher, actor=org["reviewer"], promotion_request_id=req2.id)

    db_session.expire(lifecycle_v1)
    lifecycle_v1 = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == v1.id))).scalar_one()
    lifecycle_v2 = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == v2.id))).scalar_one()
    assert lifecycle_v1.stage == Stage.DEPRECATED
    assert lifecycle_v2.stage == Stage.RECOMMENDED

    # Rollback: v1 is now `retired` - promote it again.
    req3 = await promotions_service.request_promotion(db_session, client1, actor=org["builder"], agent_version_id=v1.id)
    assert req3.from_stage == Stage.DEPRECATED
    decision3 = await promotions_service.approve_promotion(db_session, client1, publisher, actor=org["reviewer"], promotion_request_id=req3.id)
    assert decision3.decision.value == "approve"

    db_session.expire(lifecycle_v1)
    db_session.expire(lifecycle_v2)
    lifecycle_v1 = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == v1.id))).scalar_one()
    lifecycle_v2 = (await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == v2.id))).scalar_one()
    assert lifecycle_v1.stage == Stage.RECOMMENDED
    assert lifecycle_v2.stage == Stage.DEPRECATED

    rollback_events = (await db_session.execute(select(AuditEvent).where(AuditEvent.event_type == "promotion.rollback"))).scalars().all()
    assert len(rollback_events) == 1
    assert rollback_events[0].entity_id == v1.id

    history = await promotions_service.list_promotion_history_for_agent(db_session, agent.id)
    assert len(history) == 3  # all three requests preserved, unmodified, across both versions
    assert {r.id for r in history} == {req1.id, req2.id, req3.id}


async def test_concurrent_approvals_for_same_agent_only_one_ends_in_production(db_session, org):
    """Real DB-level concurrency proof: two candidate versions of the SAME
    Agent, both approved via truly concurrent transactions (separate
    sessions/connections). The advisory lock in
    app/services/promotions.py::approve_promotion must serialize them - the
    unique partial index is the final backstop if it somehow didn't. Exactly
    one version must end up in production; the DB must never be left with
    both, or with neither audit trail explaining what happened.
    """
    agent, v1, client1 = await _setup_candidate(db_session, org, "concurrent-agent", version_label="1.0.0")
    # Build a second candidate version of the SAME agent, independently.
    v2 = AgentVersion(id=uuid.uuid4(), agent_id=agent.id, version_label="2.0.0", manifest={}, content_hash="hash-2.0.0", created_by=org["builder"].id)
    db_session.add(v2)
    await db_session.flush()
    lifecycle2 = AgentVersionLifecycle(agent_version_id=v2.id, agent_id=agent.id, stage=Stage.EVALUATING, entered_by=org["builder"].id)
    db_session.add(lifecycle2)
    await db_session.commit()

    # Same agent as v1 -> same policy name resolves to the SAME policy
    # `_setup_candidate` already created for "concurrent-agent"; creating a
    # second policy version here would make v1's already-recorded evidence
    # policy_changed-stale, which isn't what this test is about.
    from app.services.evaluation_policies import get_current_policy_for_agent

    policy2 = await get_current_policy_for_agent(db_session, agent.name)

    from app.models.evaluation import EvaluationRunReference
    from app.models.enums import EvaluationRunStatus
    from app.services.evidence_snapshot import take_capability_grant_snapshot

    snapshot2 = await take_capability_grant_snapshot(db_session, v2.id)
    reference2 = EvaluationRunReference(
        id=uuid.uuid4(), agent_version_id=v2.id, evaluation_policy_id=policy2.id,
        external_agent_version_id=f"ext-{v2.id}", external_dataset_id="ds-concurrent-agent-2",
        external_evaluator_ids={"ids": ["e1"], "versions": {"completion_check": "v1"}},
        requested_by=org["builder"].id, status=EvaluationRunStatus.REQUESTED,
        capability_grant_snapshot_hash=snapshot2.hash, capability_grant_snapshot=snapshot2.snapshot,
    )
    db_session.add(reference2)
    await db_session.commit()

    client2 = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset("dataset-concurrent-agent-2", cases=[{"key": "c1", "tags": []}], dataset_id="ds-concurrent-agent-2")],
    )
    client2.next_run_dimension_stats = [DimensionStat(dimension="completion", mean_score=1.0, n=1, n_not_applicable=0)]
    await process_evaluation_job(reference2.id, client2)
    db_session.expire(reference2)
    db_session.expire(lifecycle2)

    req1 = await promotions_service.request_promotion(db_session, client1, actor=org["builder"], agent_version_id=v1.id)
    req2 = await promotions_service.request_promotion(db_session, client2, actor=org["builder"], agent_version_id=v2.id)
    agent_id, v1_id, v2_id, req1_id, req2_id = agent.id, v1.id, v2.id, req1.id, req2.id

    async def _approve(request_id, client):
        async with SessionLocal() as session:
            publisher = LocalNoopPublisher()
            # Re-fetch actor in this session's identity map.
            from app.models.identity import User as UserModel
            reviewer = (await session.execute(select(UserModel).where(UserModel.id == org["reviewer"].id))).scalar_one()
            try:
                await promotions_service.approve_promotion(
                    session, client, publisher, actor=reviewer, promotion_request_id=request_id
                )
                return "approved"
            except ConflictError:
                return "conflict"

    results = await asyncio.gather(_approve(req1_id, client1), _approve(req2_id, client2))
    assert set(results) <= {"approved", "conflict"}
    assert results.count("approved") >= 1  # at least the winner must succeed

    async with SessionLocal() as verify_session:
        lifecycles = (
            await verify_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_id == agent_id))
        ).scalars().all()
        production_versions = [lc.agent_version_id for lc in lifecycles if lc.stage == Stage.RECOMMENDED]
        assert len(production_versions) == 1  # never both, never zero once one approval succeeded
