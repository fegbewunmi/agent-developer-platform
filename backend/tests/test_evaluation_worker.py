"""app/services/evaluation_worker.py - the async pipeline: claim -> call agent-eval
-> compute gates -> persist -> lifecycle transition -> audit. Calls
process_evaluation_job directly (bypassing HTTP/dispatch) for precise control over
timing and failure injection.
"""
import uuid
from decimal import Decimal

from sqlalchemy import select

from app.integrations.agent_eval_client import AgentEvalTimeoutError, AgentEvalUnavailableError, DimensionStat
from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.audit import AuditEvent
from app.models.enums import EvaluationRunStatus, Stage
from app.models.evaluation import EvaluationGateResult, EvaluationRunReference
from app.services.evaluation_policies import create_evaluation_policy
from app.services.evaluation_worker import process_evaluation_job
from app.services.evidence_snapshot import take_capability_grant_snapshot
from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator


async def _setup(db_session, org, thresholds=None, max_new_regressions=0):
    agent = Agent(id=uuid.uuid4(), name="worker-test-agent", team_id=org["team_a"].id)
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version_label="1.0.0", manifest={}, content_hash="h",
        created_by=org["builder"].id,
    )
    db_session.add(version)
    await db_session.flush()
    lifecycle = AgentVersionLifecycle(
        agent_version_id=version.id, agent_id=agent.id, stage=Stage.EVALUATING, entered_by=org["builder"].id
    )
    db_session.add(lifecycle)

    policy = await create_evaluation_policy(
        db_session, actor=org["admin"], name=agent.name, version="v1",
        thresholds=thresholds or {}, required_evaluator_keys={"completion_check": "v1"},
        dataset_key="worker-test-dataset", max_new_regressions=max_new_regressions,
    )

    snapshot = await take_capability_grant_snapshot(db_session, version.id)
    reference = EvaluationRunReference(
        id=uuid.uuid4(), agent_version_id=version.id, evaluation_policy_id=policy.id,
        external_agent_version_id="ext-av-1", external_dataset_id="ext-ds-1",
        external_evaluator_ids={"ids": ["ev1"], "versions": {"completion_check": "v1"}},
        requested_by=org["builder"].id, status=EvaluationRunStatus.REQUESTED,
        capability_grant_snapshot_hash=snapshot.hash, capability_grant_snapshot=snapshot.snapshot,
    )
    db_session.add(reference)
    await db_session.commit()
    return agent, version, policy, reference


def _fake_client(dimension_stats=None, case_statuses=("success",)):
    client = FakeAgentEvalClient()
    client.next_run_dimension_stats = dimension_stats or [
        DimensionStat(dimension="completion", mean_score=1.0, n=1, n_not_applicable=0)
    ]
    client.next_run_case_statuses = list(case_statuses)
    client.datasets = [make_dataset("worker-test-dataset", dataset_id="ext-ds-1")]
    return client


async def test_successful_run_transitions_to_candidate(db_session, org):
    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    updated = (
        await db_session.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one()
    assert updated.status == EvaluationRunStatus.COMPLETED
    assert updated.external_run_id is not None
    assert updated.n_cases_success == 1

    lifecycle = (
        await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version_id))
    ).scalar_one()
    assert lifecycle.stage == Stage.EVALUATED

    gates = (
        await db_session.execute(select(EvaluationGateResult).where(EvaluationGateResult.evaluation_run_reference_id == reference_id))
    ).scalars().all()
    assert len(gates) > 0
    assert all(g.passed for g in gates)


async def test_failing_gate_sends_version_back_to_draft(db_session, org):
    agent, version, policy, reference = await _setup(db_session, org, thresholds={"grounding": {"min_mean": 0.99}})
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client(dimension_stats=[DimensionStat(dimension="grounding", mean_score=0.1, n=1, n_not_applicable=0)])

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    lifecycle = (
        await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version_id))
    ).scalar_one()
    assert lifecycle.stage == Stage.DRAFT

    updated = (
        await db_session.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one()
    assert updated.status == EvaluationRunStatus.COMPLETED  # the RUN completed; it just didn't pass gates


async def test_agent_eval_unavailable_marks_failed_and_reverts_to_draft(db_session, org):
    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()
    client.raise_on_trigger = AgentEvalUnavailableError("connection refused")

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    updated = (
        await db_session.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one()
    assert updated.status == EvaluationRunStatus.FAILED
    assert "unavailable" in updated.error_message.lower()

    lifecycle = (
        await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version_id))
    ).scalar_one()
    assert lifecycle.stage == Stage.DRAFT


async def test_agent_eval_timeout_marks_failed_distinctly(db_session, org):
    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()
    client.raise_on_trigger = AgentEvalTimeoutError("timed out after 240s")

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    updated = (
        await db_session.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one()
    assert updated.status == EvaluationRunStatus.FAILED
    assert "timeout" in updated.error_message.lower()


async def test_duplicate_dispatch_is_a_safe_no_op(db_session, org):
    """Simulates at-least-once Cloud Tasks delivery: processing the same reference
    twice must not submit two runs to agent-eval or double-transition the lifecycle."""
    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()
    first_call_count = len(client.trigger_calls)
    await process_evaluation_job(reference_id, client)  # duplicate delivery

    assert len(client.trigger_calls) == first_call_count  # no second submission


async def test_evaluation_completed_and_became_candidate_audit_events_are_recorded(db_session, org):
    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    events = (
        await db_session.execute(select(AuditEvent.event_type).where(AuditEvent.entity_id == reference_id))
    ).scalars().all()
    assert "evaluation.completed" in events

    became_candidate = (
        await db_session.execute(
            select(AuditEvent.event_type).where(
                AuditEvent.entity_id == version_id, AuditEvent.event_type == "agent_version.became_candidate"
            )
        )
    ).scalars().all()
    assert became_candidate == ["agent_version.became_candidate"]


async def test_failed_run_emits_evaluation_failed_audit_event(db_session, org):
    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()
    client.raise_on_trigger = AgentEvalUnavailableError("down")

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    events = (
        await db_session.execute(select(AuditEvent.event_type).where(AuditEvent.entity_id == reference_id))
    ).scalars().all()
    assert "evaluation.failed" in events


async def test_max_new_regressions_uses_production_baseline(db_session, org):
    """Sets up a second, production-stage AgentVersion for the same Agent with a
    completed evaluation, then verifies the worker calls compare_runs against it."""
    agent, version, policy, reference = await _setup(db_session, org, max_new_regressions=0)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id

    baseline_version = AgentVersion(
        id=uuid.uuid4(), agent_id=agent.id, version_label="0.9.0", manifest={}, content_hash="h0",
        created_by=org["builder"].id,
    )
    db_session.add(baseline_version)
    await db_session.flush()
    db_session.add(
        AgentVersionLifecycle(agent_version_id=baseline_version.id, agent_id=agent.id, stage=Stage.RECOMMENDED, entered_by=org["admin"].id)
    )
    baseline_ref = EvaluationRunReference(
        id=uuid.uuid4(), agent_version_id=baseline_version.id, evaluation_policy_id=policy.id,
        external_agent_version_id="ext-av-0", external_dataset_id="ext-ds-1", external_run_id="baseline-run-id",
        requested_by=org["builder"].id, status=EvaluationRunStatus.COMPLETED,
    )
    db_session.add(baseline_ref)
    await db_session.commit()

    client = _fake_client()
    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    updated = (
        await db_session.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one()
    gates = (
        await db_session.execute(select(EvaluationGateResult).where(EvaluationGateResult.evaluation_run_reference_id == updated.id))
    ).scalars().all()
    regression_gate = next(g for g in gates if g.gate_type == "max_new_regressions")
    assert regression_gate.evidence_ref.get("baseline_run_id") == "baseline-run-id"


async def test_malformed_agent_eval_response_marks_failed(db_session, org):
    from app.integrations.agent_eval_client import AgentEvalMalformedResponseError

    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()
    client.raise_on_trigger = AgentEvalMalformedResponseError("unexpected shape: missing 'dimension_stats'")

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    updated = (
        await db_session.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one()
    assert updated.status == EvaluationRunStatus.FAILED
    assert "malformed" in updated.error_message.lower()


async def test_policy_change_mid_run_does_not_affect_the_in_flight_evaluation(db_session, org):
    """docs/failure-modes.md: 'policy changed while evaluation was running'. Gates
    are computed against the policy_id pinned on the EvaluationRunReference at
    request time - a new policy version published after the run started has zero
    effect on how THIS run's gates are computed (it only affects freshness checks
    for FUTURE promotion-eligibility queries - see app/services/freshness.py)."""
    agent, version, policy, reference = await _setup(db_session, org, thresholds={"grounding": {"min_mean": 0.5}})
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id

    # A new, stricter policy version is published for the same agent - simulating
    # an Admin editing policy while this evaluation is still in flight.
    new_policy = await create_evaluation_policy(
        db_session, actor=org["admin"], name=agent.name, version="v2",
        thresholds={"grounding": {"min_mean": 0.99}}, required_evaluator_keys={"completion_check": "v1"},
        dataset_key="worker-test-dataset",
    )
    assert new_policy.id != policy_id

    client = _fake_client(dimension_stats=[DimensionStat(dimension="grounding", mean_score=0.6, n=1, n_not_applicable=0)])
    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    gates = (
        await db_session.execute(select(EvaluationGateResult).where(EvaluationGateResult.evaluation_run_reference_id == reference_id))
    ).scalars().all()
    grounding_gate = next(g for g in gates if g.gate_type == "min_dimension_score")
    # Graded against the OLD (pinned) policy's 0.5 threshold, not the new 0.99 one -
    # 0.6 passes against 0.5.
    assert grounding_gate.passed is True
    assert grounding_gate.expected == "0.5"


async def test_capability_grants_changed_mid_run_fails_the_snapshot_consistency_gate(db_session, org):
    """docs/failure-modes.md: 'capability grants changed while evaluation was
    running'. Simulated by committing a new grant between request time (when the
    reference's snapshot hash was captured) and worker execution (when the
    completion-time snapshot is taken)."""
    from app.models.enums import MCPClassification
    from app.models.mcp import AgentCapabilityGrant, MCPServer, MCPTool

    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id

    server = MCPServer(id=uuid.uuid4(), name=f"srv-{uuid.uuid4().hex[:8]}", environment="development", owner_team_id=org["team_a"].id, connection_ref="http://x")
    db_session.add(server)
    await db_session.flush()
    tool = MCPTool(id=uuid.uuid4(), mcp_server_id=server.id, name="mid_run_tool", classification=MCPClassification.READ)
    db_session.add(tool)
    await db_session.flush()
    db_session.add(AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version_id, mcp_tool_id=tool.id, granted_by=org["builder"].id))
    await db_session.commit()  # a grant appears AFTER reference.capability_grant_snapshot_hash was captured

    client = _fake_client()
    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    gates = (
        await db_session.execute(select(EvaluationGateResult).where(EvaluationGateResult.evaluation_run_reference_id == reference_id))
    ).scalars().all()
    snapshot_gate = next(g for g in gates if g.gate_type == "capability_snapshot_consistency")
    assert snapshot_gate.passed is False

    # This is exactly what makes the version end up back in draft even though the
    # actual evaluation result itself was fine - one failing gate is enough.
    lifecycle = (
        await db_session.execute(select(AgentVersionLifecycle).where(AgentVersionLifecycle.agent_version_id == version_id))
    ).scalar_one()
    assert lifecycle.stage == Stage.DRAFT


async def test_db_write_failure_after_external_success_preserves_external_run_id(db_session, org, monkeypatch):
    """docs/failure-modes.md's distributed failure boundary: agent-eval genuinely
    succeeded, but persisting the result locally fails. The external_run_id must
    survive as a reconciliation breadcrumb - never silently lost."""
    import app.services.evaluation_worker as worker_module

    agent, version, policy, reference = await _setup(db_session, org)
    agent_id, version_id, policy_id, reference_id = agent.id, version.id, policy.id, reference.id
    client = _fake_client()

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated local persistence failure")

    monkeypatch.setattr(worker_module, "_persist_success", _boom)

    await process_evaluation_job(reference_id, client)
    db_session.expire_all()

    updated = (
        await db_session.execute(select(EvaluationRunReference).where(EvaluationRunReference.id == reference_id))
    ).scalar_one()
    assert updated.status == EvaluationRunStatus.FAILED
    assert updated.external_run_id is not None  # the breadcrumb survives
    assert "external evaluation run" in updated.error_message
    assert "re-fetch" in updated.error_message.lower() or "retry" in updated.error_message.lower()

    events = (
        await db_session.execute(select(AuditEvent.event_type).where(AuditEvent.entity_id == reference_id))
    ).scalars().all()
    assert "evaluation.failed" in events
