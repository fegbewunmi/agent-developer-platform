"""app/services/freshness.py - "evaluation passed at the time" vs "evidence is
still valid for promotion now". Each stale reason tested independently.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.integrations.agent_eval_client import DimensionStat
from app.models.agent import Agent, AgentVersion, AgentVersionLifecycle
from app.models.enums import MCPClassification, Stage
from app.models.mcp import AgentCapabilityGrant, MCPServer, MCPTool
from app.services.evaluation_policies import create_evaluation_policy
from app.services.evaluation_worker import process_evaluation_job
from app.services.freshness import check_freshness, dataset_case_set_fingerprint
from tests.fakes.agent_eval import FakeAgentEvalClient, make_dataset, make_evaluator


async def _setup_passing_evaluation(db_session, org, agent_name="freshness-agent"):
    agent = Agent(id=uuid.uuid4(), name=agent_name, team_id=org["team_a"].id)
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(id=uuid.uuid4(), agent_id=agent.id, version_label="1.0.0", manifest={}, content_hash="h", created_by=org["builder"].id)
    db_session.add(version)
    await db_session.flush()
    lifecycle = AgentVersionLifecycle(agent_version_id=version.id, agent_id=agent.id, stage=Stage.EVALUATING, entered_by=org["builder"].id)
    db_session.add(lifecycle)
    policy = await create_evaluation_policy(
        db_session, actor=org["admin"], name=agent_name, version="v1",
        thresholds={}, required_evaluator_keys={"completion_check": "v1"}, dataset_key="fresh-dataset",
    )
    await db_session.commit()

    from app.models.evaluation import EvaluationRunReference
    from app.models.enums import EvaluationRunStatus
    from app.services.evidence_snapshot import take_capability_grant_snapshot

    snapshot = await take_capability_grant_snapshot(db_session, version.id)
    reference = EvaluationRunReference(
        id=uuid.uuid4(), agent_version_id=version.id, evaluation_policy_id=policy.id,
        external_agent_version_id="ext-av", external_dataset_id="ds-1",
        external_evaluator_ids={"ids": ["e1"], "versions": {"completion_check": "v1"}},
        requested_by=org["builder"].id, status=EvaluationRunStatus.REQUESTED,
        capability_grant_snapshot_hash=snapshot.hash, capability_grant_snapshot=snapshot.snapshot,
    )
    db_session.add(reference)
    await db_session.commit()
    reference_id, version_id, agent_id = reference.id, version.id, agent.id

    client = FakeAgentEvalClient(
        evaluators=[make_evaluator("completion_check", "v1")],
        datasets=[make_dataset("fresh-dataset", cases=[{"key": "c1", "tags": []}], dataset_id="ds-1")],
    )
    client.next_run_dimension_stats = [DimensionStat(dimension="completion", mean_score=1.0, n=1, n_not_applicable=0)]
    await process_evaluation_job(reference_id, client)
    # Expire only the two rows the worker actually mutates via its own separate
    # sessions - never expire_all(), which would also expire (and thus force an
    # unsafe synchronous reload of) unrelated objects still in this session's
    # identity map, such as the `org` fixture's Team/User rows touched later in
    # each test body. That was the real, precise cause of a MissingGreenlet here.
    db_session.expire(reference)
    db_session.expire(lifecycle)

    return agent_id, version_id, agent_name, client


async def test_no_evaluation_at_all_is_not_eligible(db_session, org):
    agent = Agent(id=uuid.uuid4(), name="never-evaluated", team_id=org["team_a"].id)
    db_session.add(agent)
    await db_session.flush()
    version = AgentVersion(id=uuid.uuid4(), agent_id=agent.id, version_label="1.0.0", manifest={}, content_hash="h", created_by=org["builder"].id)
    db_session.add(version)
    await db_session.flush()
    db_session.add(AgentVersionLifecycle(agent_version_id=version.id, agent_id=agent.id, stage=Stage.DRAFT, entered_by=org["builder"].id))
    await db_session.commit()

    fake = FakeAgentEvalClient()
    result = await check_freshness(db_session, fake, version.id, agent.name)
    assert result.historically_passed is False
    assert result.currently_eligible is False


async def test_freshly_passed_evaluation_is_currently_eligible(db_session, org):
    agent_id, version_id, agent_name, client = await _setup_passing_evaluation(db_session, org)

    result = await check_freshness(db_session, client, version_id, agent_name)
    assert result.historically_passed is True
    assert result.currently_eligible is True
    assert result.stale_findings == []


async def test_capability_grant_change_after_evaluation_makes_it_stale(db_session, org):
    agent_id, version_id, agent_name, client = await _setup_passing_evaluation(db_session, org)

    server = MCPServer(id=uuid.uuid4(), name=f"srv-{uuid.uuid4().hex[:8]}", environment="development", owner_team_id=org["team_a"].id, connection_ref="http://x")
    db_session.add(server)
    await db_session.flush()
    tool = MCPTool(id=uuid.uuid4(), mcp_server_id=server.id, name="new_tool", classification=MCPClassification.READ)
    db_session.add(tool)
    await db_session.flush()
    db_session.add(AgentCapabilityGrant(id=uuid.uuid4(), agent_version_id=version_id, mcp_tool_id=tool.id, granted_by=org["builder"].id))
    await db_session.commit()
    result = await check_freshness(db_session, client, version_id, agent_name)
    assert result.currently_eligible is False
    assert any(f.reason == "capability_grants_changed" for f in result.stale_findings)


async def test_evaluator_version_change_makes_it_stale(db_session, org):
    agent_id, version_id, agent_name, client = await _setup_passing_evaluation(db_session, org)

    client.evaluators = [make_evaluator("completion_check", "v2")]  # catalog moved on

    result = await check_freshness(db_session, client, version_id, agent_name)
    assert result.currently_eligible is False
    assert any(f.reason == "evaluator_version_changed" for f in result.stale_findings)


async def test_missing_required_evaluator_makes_it_stale(db_session, org):
    agent_id, version_id, agent_name, client = await _setup_passing_evaluation(db_session, org)

    client.evaluators = []  # evaluator removed from the catalog entirely

    result = await check_freshness(db_session, client, version_id, agent_name)
    assert result.currently_eligible is False
    assert any(f.reason == "missing_required_evaluator" for f in result.stale_findings)


async def test_policy_change_makes_it_stale(db_session, org):
    agent_id, version_id, agent_name, client = await _setup_passing_evaluation(db_session, org)

    await create_evaluation_policy(
        db_session, actor=org["admin"], name=agent_name, version="v2",
        thresholds={}, required_evaluator_keys={"completion_check": "v1"}, dataset_key="fresh-dataset",
    )
    result = await check_freshness(db_session, client, version_id, agent_name)
    assert result.currently_eligible is False
    assert any(f.reason == "policy_changed" for f in result.stale_findings)


async def test_dataset_case_set_change_makes_it_stale(db_session, org):
    agent_id, version_id, agent_name, client = await _setup_passing_evaluation(db_session, org)

    # A case added to the dataset - the honest, structural-only proxy CAN catch this.
    client.datasets = [make_dataset("fresh-dataset", cases=[{"key": "c1", "tags": []}, {"key": "c2", "tags": []}], dataset_id="ds-1")]

    result = await check_freshness(db_session, client, version_id, agent_name)
    assert result.currently_eligible is False
    assert any(f.reason == "dataset_changed" for f in result.stale_findings)


async def test_historical_pass_remains_true_even_when_currently_stale(db_session, org):
    """The core distinction the brief calls out: 'evaluation passed at the time'
    is a permanent historical fact, unaffected by later drift."""
    agent_id, version_id, agent_name, client = await _setup_passing_evaluation(db_session, org)
    client.evaluators = []

    result = await check_freshness(db_session, client, version_id, agent_name)
    assert result.historically_passed is True  # unchanged
    assert result.currently_eligible is False  # but no longer promotable


def test_dataset_case_set_fingerprint_is_order_independent():
    a = dataset_case_set_fingerprint([{"key": "b", "tags": []}, {"key": "a", "tags": []}])
    b = dataset_case_set_fingerprint([{"key": "a", "tags": []}, {"key": "b", "tags": []}])
    assert a == b


def test_dataset_case_set_fingerprint_changes_with_tags():
    a = dataset_case_set_fingerprint([{"key": "a", "tags": []}])
    b = dataset_case_set_fingerprint([{"key": "a", "tags": ["critical"]}])
    assert a != b
