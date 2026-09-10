"""Proves the DB-level invariants in docs/adrs/0002-immutable-versioned-artifacts.md,
docs/audit-model.md, docs/adrs/0009-no-self-approval.md, docs/failure-modes.md,
and (Phase 2) docs/adrs/0004-mcp-capability-grant-model.md's "at most one
active grant" rule are real constraints the application role cannot bypass -
not just conventions the API happens to enforce. Connects directly as
agent_platform_app (the exact role the running application uses), never as
the privileged migration role, so a passing test here is proof the
constraint holds for the actual runtime, not just in principle.
"""
import uuid

import psycopg
import pytest

APP_DSN = "postgresql://agent_platform_app:agent_platform_app_dev@127.0.0.1:5432/agent_dev_platform_test"


@pytest.fixture
def app_conn():
    conn = psycopg.connect(APP_DSN, autocommit=False)
    yield conn
    conn.rollback()
    conn.close()


def _make_team_user_agent(cur) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    team_id, user_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cur.execute("INSERT INTO teams (id, name) VALUES (%s, %s)", (team_id, f"team-{team_id.hex[:8]}"))
    cur.execute(
        "INSERT INTO users (id, name, email, team_id, role) VALUES (%s, %s, %s, %s, %s)",
        (user_id, "Test User", f"{user_id.hex[:8]}@example.com", team_id, "builder"),
    )
    cur.execute(
        "INSERT INTO agents (id, name, team_id) VALUES (%s, %s, %s)",
        (agent_id, f"agent-{agent_id.hex[:8]}", team_id),
    )
    return team_id, user_id, agent_id


def test_agent_version_insert_succeeds(app_conn):
    with app_conn.cursor() as cur:
        _, user_id, agent_id = _make_team_user_agent(cur)
        version_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO agent_versions
               (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (version_id, agent_id, "1.0.0", "{}", "deadbeef", user_id),
        )
    app_conn.commit()


def test_agent_version_update_is_rejected(app_conn):
    with app_conn.cursor() as cur:
        _, user_id, agent_id = _make_team_user_agent(cur)
        version_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO agent_versions
               (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (version_id, agent_id, "1.0.0", "{}", "deadbeef", user_id),
        )
    app_conn.commit()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("UPDATE agent_versions SET content_hash = 'tampered' WHERE id = %s", (version_id,))
    app_conn.rollback()


def test_agent_version_delete_is_rejected(app_conn):
    with app_conn.cursor() as cur:
        _, user_id, agent_id = _make_team_user_agent(cur)
        version_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO agent_versions
               (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (version_id, agent_id, "1.0.0", "{}", "deadbeef", user_id),
        )
    app_conn.commit()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("DELETE FROM agent_versions WHERE id = %s", (version_id,))
    app_conn.rollback()


def test_skill_version_update_is_rejected(app_conn):
    with app_conn.cursor() as cur:
        team_id, user_id, _ = _make_team_user_agent(cur)
        skill_id = uuid.uuid4()
        cur.execute("INSERT INTO skills (id, name, owner_team_id) VALUES (%s, %s, %s)", (skill_id, f"skill-{skill_id.hex[:8]}", team_id))
        sv_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO skill_versions (id, skill_id, version, owner_user_id, purpose) VALUES (%s, %s, %s, %s, %s)",
            (sv_id, skill_id, "1.0", user_id, "test"),
        )
    app_conn.commit()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("UPDATE skill_versions SET purpose = 'tampered' WHERE id = %s", (sv_id,))
    app_conn.rollback()


def test_audit_event_update_and_delete_are_rejected(app_conn):
    with app_conn.cursor() as cur:
        _, user_id, agent_id = _make_team_user_agent(cur)
        event_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO audit_events (id, event_type, entity_type, entity_id, actor) VALUES (%s, %s, %s, %s, %s)",
            (event_id, "agent.created", "agent", agent_id, user_id),
        )
    app_conn.commit()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("UPDATE audit_events SET event_type = 'tampered' WHERE id = %s", (event_id,))
    app_conn.rollback()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute("DELETE FROM audit_events WHERE id = %s", (event_id,))
    app_conn.rollback()


def test_only_one_production_version_per_agent(app_conn):
    with app_conn.cursor() as cur:
        _, user_id, agent_id = _make_team_user_agent(cur)

        v1, v2 = uuid.uuid4(), uuid.uuid4()
        for v, label in [(v1, "1.0.0"), (v2, "2.0.0")]:
            cur.execute(
                """INSERT INTO agent_versions
                   (id, agent_id, version_label, manifest, content_hash, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (v, agent_id, label, "{}", f"hash-{label}", user_id),
            )
        cur.execute(
            "INSERT INTO agent_version_lifecycle (agent_version_id, agent_id, stage, entered_by) VALUES (%s, %s, 'production', %s)",
            (v1, agent_id, user_id),
        )
    app_conn.commit()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.UniqueViolation):
        cur.execute(
            "INSERT INTO agent_version_lifecycle (agent_version_id, agent_id, stage, entered_by) VALUES (%s, %s, 'production', %s)",
            (v2, agent_id, user_id),
        )
    app_conn.rollback()


def test_second_agent_can_independently_have_a_production_version(app_conn):
    """The partial unique index is scoped per-agent, not global - a second
    Agent having its own production version must not be blocked by the
    first Agent's production version.
    """
    with app_conn.cursor() as cur:
        _, user_id, agent1_id = _make_team_user_agent(cur)
        team2_id, _, agent2_id = _make_team_user_agent(cur)

        v1, v2 = uuid.uuid4(), uuid.uuid4()
        cur.execute(
            """INSERT INTO agent_versions (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (v1, agent1_id, "1.0.0", "{}", "hash-1", user_id),
        )
        cur.execute(
            """INSERT INTO agent_versions (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (v2, agent2_id, "1.0.0", "{}", "hash-2", user_id),
        )
        cur.execute(
            "INSERT INTO agent_version_lifecycle (agent_version_id, agent_id, stage, entered_by) VALUES (%s, %s, 'production', %s)",
            (v1, agent1_id, user_id),
        )
        cur.execute(
            "INSERT INTO agent_version_lifecycle (agent_version_id, agent_id, stage, entered_by) VALUES (%s, %s, 'production', %s)",
            (v2, agent2_id, user_id),
        )
    app_conn.commit()


def test_promotion_decision_rejects_self_approval(app_conn):
    with app_conn.cursor() as cur:
        _, user_id, agent_id = _make_team_user_agent(cur)
        version_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO agent_versions (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (version_id, agent_id, "1.0.0", "{}", "hash", user_id),
        )
        request_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO promotion_requests
               (id, agent_version_id, from_stage, to_stage, requested_by)
               VALUES (%s, %s, 'candidate', 'production', %s)""",
            (request_id, version_id, user_id),
        )
    app_conn.commit()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(
            "INSERT INTO promotion_decisions (id, promotion_request_id, decision, decided_by) VALUES (%s, %s, 'approve', %s)",
            (uuid.uuid4(), request_id, user_id),
        )
    app_conn.rollback()


def test_promotion_decision_by_a_different_user_succeeds(app_conn):
    with app_conn.cursor() as cur:
        team_id, requester_id, agent_id = _make_team_user_agent(cur)
        reviewer_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO users (id, name, email, team_id, role) VALUES (%s, %s, %s, %s, %s)",
            (reviewer_id, "Reviewer", f"{reviewer_id.hex[:8]}@example.com", team_id, "reviewer"),
        )
        version_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO agent_versions (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (version_id, agent_id, "1.0.0", "{}", "hash", requester_id),
        )
        request_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO promotion_requests
               (id, agent_version_id, from_stage, to_stage, requested_by)
               VALUES (%s, %s, 'candidate', 'production', %s)""",
            (request_id, version_id, requester_id),
        )
        cur.execute(
            "INSERT INTO promotion_decisions (id, promotion_request_id, decision, decided_by) VALUES (%s, %s, 'approve', %s)",
            (uuid.uuid4(), request_id, reviewer_id),
        )
    app_conn.commit()


def test_only_one_active_grant_per_version_and_tool(app_conn):
    """Phase 2: migration 0009's partial unique index on
    agent_capability_grants(agent_version_id, mcp_tool_id) WHERE revoked_at
    IS NULL - the DB-level backstop behind the API's 409 in
    app/services/capability_grants.py::grant_capability.
    """
    with app_conn.cursor() as cur:
        team_id, user_id, agent_id = _make_team_user_agent(cur)
        version_id = uuid.uuid4()
        cur.execute(
            """INSERT INTO agent_versions (id, agent_id, version_label, manifest, content_hash, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (version_id, agent_id, "1.0.0", "{}", "hash", user_id),
        )
        server_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO mcp_servers (id, name, environment, owner_team_id, connection_ref) VALUES (%s, %s, %s, %s, %s)",
            (server_id, f"server-{server_id.hex[:8]}", "development", team_id, "http://127.0.0.1:8080"),
        )
        tool_id = uuid.uuid4()
        cur.execute(
            "INSERT INTO mcp_tools (id, mcp_server_id, name, classification) VALUES (%s, %s, %s, 'read')",
            (tool_id, server_id, "search_documents"),
        )
        cur.execute(
            "INSERT INTO agent_capability_grants (id, agent_version_id, mcp_tool_id, granted_by) VALUES (%s, %s, %s, %s)",
            (uuid.uuid4(), version_id, tool_id, user_id),
        )
    app_conn.commit()

    with app_conn.cursor() as cur, pytest.raises(psycopg.errors.UniqueViolation):
        cur.execute(
            "INSERT INTO agent_capability_grants (id, agent_version_id, mcp_tool_id, granted_by) VALUES (%s, %s, %s, %s)",
            (uuid.uuid4(), version_id, tool_id, user_id),
        )
    app_conn.rollback()
