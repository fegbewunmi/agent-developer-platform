"""Policy creation, versioning, immutability, and permission enforcement -
docs/adrs/0015-evaluation-policy-immutability.md.
"""
from decimal import Decimal


async def test_admin_can_create_policy(client, org, headers_for):
    resp = await client.post(
        "/v1/evaluation-policies",
        json={
            "name": "incident-investigator",
            "version": "v1",
            "thresholds": {"grounding": {"min_mean": 0.8}},
            "required_evaluator_keys": {"grounding_judge": "v1"},
            "dataset_key": "incident-investigator-smoke-v1",
        },
        headers=headers_for(org["admin"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "incident-investigator"
    assert body["version"] == "v1"
    assert body["max_new_regressions"] == 0
    assert body["min_completion_rate"] == "1.000"


async def test_non_admin_cannot_create_policy(client, org, headers_for):
    for user_key in ("viewer", "builder", "reviewer"):
        resp = await client.post(
            "/v1/evaluation-policies",
            json={
                "name": f"policy-by-{user_key}",
                "version": "v1",
                "thresholds": {},
                "required_evaluator_keys": {"x": "v1"},
                "dataset_key": "ds",
            },
            headers=headers_for(org[user_key]),
        )
        assert resp.status_code == 403, user_key


async def test_duplicate_name_version_is_409(client, org, headers_for):
    body = {
        "name": "dup-policy", "version": "v1", "thresholds": {}, "required_evaluator_keys": {"x": "v1"},
        "dataset_key": "ds",
    }
    first = await client.post("/v1/evaluation-policies", json=body, headers=headers_for(org["admin"]))
    assert first.status_code == 201
    second = await client.post("/v1/evaluation-policies", json=body, headers=headers_for(org["admin"]))
    assert second.status_code == 409


async def test_new_version_of_same_policy_name_is_allowed(client, org, headers_for):
    base = {"name": "versioned-policy", "thresholds": {}, "required_evaluator_keys": {"x": "v1"}, "dataset_key": "ds"}
    v1 = await client.post("/v1/evaluation-policies", json={**base, "version": "v1"}, headers=headers_for(org["admin"]))
    assert v1.status_code == 201
    v2 = await client.post("/v1/evaluation-policies", json={**base, "version": "v2"}, headers=headers_for(org["admin"]))
    assert v2.status_code == 201
    assert v1.json()["id"] != v2.json()["id"]


async def test_no_mutation_route_exists_for_policies(client, org, headers_for):
    import uuid

    resp = await client.patch(f"/v1/evaluation-policies/{uuid.uuid4()}", json={}, headers=headers_for(org["admin"]))
    assert resp.status_code in (404, 405)


async def test_policy_immutable_at_db_level(db_session, org):
    """Editing means publishing a new (name, version) row - proven at the DB level
    via the actual restricted runtime role, matching the Phase 1/2 pattern."""
    import uuid

    import psycopg
    import pytest

    from app.services.evaluation_policies import create_evaluation_policy

    policy = await create_evaluation_policy(
        db_session, actor=org["admin"], name="immutable-check", version="v1",
        thresholds={}, required_evaluator_keys={"x": "v1"}, dataset_key="ds",
    )

    conn = psycopg.connect("postgresql://agent_platform_app:agent_platform_app_dev@127.0.0.1:5432/agent_dev_platform_test")
    try:
        with conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("UPDATE evaluation_policies SET dataset_key = 'tampered' WHERE id = %s", (policy.id,))
        conn.rollback()
    finally:
        conn.close()


async def test_get_current_policy_for_agent_returns_newest_version(db_session, org):
    from app.services.evaluation_policies import create_evaluation_policy, get_current_policy_for_agent

    await create_evaluation_policy(
        db_session, actor=org["admin"], name="agentX", version="v1",
        thresholds={}, required_evaluator_keys={"x": "v1"}, dataset_key="ds",
    )
    v2 = await create_evaluation_policy(
        db_session, actor=org["admin"], name="agentX", version="v2",
        thresholds={}, required_evaluator_keys={"x": "v1"}, dataset_key="ds",
    )

    current = await get_current_policy_for_agent(db_session, "agentX")
    assert current.id == v2.id


async def test_get_current_policy_for_agent_raises_when_none_exists(db_session):
    from app.services.errors import NotFoundError
    from app.services.evaluation_policies import get_current_policy_for_agent
    import pytest

    with pytest.raises(NotFoundError):
        await get_current_policy_for_agent(db_session, "no-such-agent")
