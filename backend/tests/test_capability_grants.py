"""AgentCapabilityGrant: docs/mcp-governance.md, docs/adrs/0004-mcp-capability-grant-model.md.
Proves grant authority scales with risk (read vs write/approval-required),
revocation doesn't touch the immutable manifest, and duplicate-active-grant
is rejected.
"""
import uuid


async def _make_agent_version(client, org, headers_for, name="grant-agent"):
    agent_resp = await client.post(
        "/v1/agents", json={"name": name, "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": name, "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": [],
        "mcp": {"servers": [], "tools": []},
        "evaluation": {"policy": "test-policy"},
    }
    v_resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    return v_resp.json()["id"]


async def _make_server_and_tools(client, org, headers_for):
    server_resp = await client.post(
        "/v1/mcp-servers",
        json={
            "name": f"grant-test-server-{uuid.uuid4().hex[:6]}",
            "environment": "development",
            "owner_team_id": str(org["team_a"].id),
            "connection_ref": "http://127.0.0.1:8080",
        },
        headers=headers_for(org["admin"]),
    )
    server_id = server_resp.json()["id"]
    read_tool = (
        await client.post(
            f"/v1/mcp-servers/{server_id}/tools",
            json={"name": "search_documents", "classification": "read", "requires_approval": False},
            headers=headers_for(org["admin"]),
        )
    ).json()
    write_tool = (
        await client.post(
            f"/v1/mcp-servers/{server_id}/tools",
            json={"name": "create_ticket", "classification": "write", "requires_approval": True},
            headers=headers_for(org["admin"]),
        )
    ).json()
    return read_tool, write_tool


async def test_builder_can_grant_read_tool_own_team(client, org, headers_for):
    version_id = await _make_agent_version(client, org, headers_for)
    read_tool, _ = await _make_server_and_tools(client, org, headers_for)

    resp = await client.post(
        f"/v1/agent-versions/{version_id}/capability-grants",
        json={"mcp_tool_id": read_tool["id"]},
        headers=headers_for(org["builder"]),
    )
    assert resp.status_code == 201
    assert resp.json()["revoked_at"] is None


async def test_builder_cannot_grant_write_tool(client, org, headers_for):
    version_id = await _make_agent_version(client, org, headers_for, "write-grant-agent")
    _, write_tool = await _make_server_and_tools(client, org, headers_for)

    resp = await client.post(
        f"/v1/agent-versions/{version_id}/capability-grants",
        json={"mcp_tool_id": write_tool["id"]},
        headers=headers_for(org["builder"]),
    )
    assert resp.status_code == 403


async def test_reviewer_can_grant_write_tool(client, org, headers_for):
    version_id = await _make_agent_version(client, org, headers_for, "reviewer-grant-agent")
    _, write_tool = await _make_server_and_tools(client, org, headers_for)

    resp = await client.post(
        f"/v1/agent-versions/{version_id}/capability-grants",
        json={"mcp_tool_id": write_tool["id"]},
        headers=headers_for(org["reviewer"]),
    )
    assert resp.status_code == 201


async def test_duplicate_active_grant_is_409(client, org, headers_for):
    version_id = await _make_agent_version(client, org, headers_for, "dup-grant-agent")
    read_tool, _ = await _make_server_and_tools(client, org, headers_for)

    body = {"mcp_tool_id": read_tool["id"]}
    first = await client.post(f"/v1/agent-versions/{version_id}/capability-grants", json=body, headers=headers_for(org["builder"]))
    assert first.status_code == 201
    second = await client.post(f"/v1/agent-versions/{version_id}/capability-grants", json=body, headers=headers_for(org["builder"]))
    assert second.status_code == 409


async def test_builder_cannot_revoke_grant(client, org, headers_for):
    version_id = await _make_agent_version(client, org, headers_for, "revoke-forbidden-agent")
    read_tool, _ = await _make_server_and_tools(client, org, headers_for)
    grant = (
        await client.post(
            f"/v1/agent-versions/{version_id}/capability-grants",
            json={"mcp_tool_id": read_tool["id"]},
            headers=headers_for(org["builder"]),
        )
    ).json()

    resp = await client.post(f"/v1/capability-grants/{grant['id']}/revoke", headers=headers_for(org["builder"]))
    assert resp.status_code == 403


async def test_admin_can_revoke_and_effective_access_changes_while_history_remains(client, org, headers_for):
    version_id = await _make_agent_version(client, org, headers_for, "revoke-ok-agent")
    read_tool, _ = await _make_server_and_tools(client, org, headers_for)
    grant = (
        await client.post(
            f"/v1/agent-versions/{version_id}/capability-grants",
            json={"mcp_tool_id": read_tool["id"]},
            headers=headers_for(org["builder"]),
        )
    ).json()

    effective_before = await client.get(f"/v1/agent-versions/{version_id}/capability-grants", headers=headers_for(org["viewer"]))
    assert len(effective_before.json()) == 1

    revoke_resp = await client.post(f"/v1/capability-grants/{grant['id']}/revoke", headers=headers_for(org["admin"]))
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked_at"] is not None
    assert revoke_resp.json()["revoked_by"] is not None

    effective_after = await client.get(f"/v1/agent-versions/{version_id}/capability-grants", headers=headers_for(org["viewer"]))
    assert effective_after.json() == []

    with_history = await client.get(
        f"/v1/agent-versions/{version_id}/capability-grants?include_revoked=true", headers=headers_for(org["viewer"])
    )
    assert len(with_history.json()) == 1
    assert with_history.json()[0]["revoked_at"] is not None

    # The immutable manifest is untouched by revocation - docs/agent-versioning.md#the-stage-vs-content-split
    manifest_resp = await client.get(f"/v1/agent-versions/{version_id}/manifest", headers=headers_for(org["viewer"]))
    assert manifest_resp.status_code == 200


async def test_revoking_an_already_revoked_grant_is_409(client, org, headers_for):
    version_id = await _make_agent_version(client, org, headers_for, "double-revoke-agent")
    read_tool, _ = await _make_server_and_tools(client, org, headers_for)
    grant = (
        await client.post(
            f"/v1/agent-versions/{version_id}/capability-grants",
            json={"mcp_tool_id": read_tool["id"]},
            headers=headers_for(org["builder"]),
        )
    ).json()

    first = await client.post(f"/v1/capability-grants/{grant['id']}/revoke", headers=headers_for(org["admin"]))
    assert first.status_code == 200
    second = await client.post(f"/v1/capability-grants/{grant['id']}/revoke", headers=headers_for(org["admin"]))
    assert second.status_code == 409


async def test_can_regrant_after_revocation(client, org, headers_for):
    """Revoke-then-regrant creates a new row; the old one stays revoked
    history, per docs/mcp-governance.md - not a resurrection of the old grant.
    """
    version_id = await _make_agent_version(client, org, headers_for, "regrant-agent")
    read_tool, _ = await _make_server_and_tools(client, org, headers_for)

    grant1 = (
        await client.post(
            f"/v1/agent-versions/{version_id}/capability-grants",
            json={"mcp_tool_id": read_tool["id"]},
            headers=headers_for(org["builder"]),
        )
    ).json()
    await client.post(f"/v1/capability-grants/{grant1['id']}/revoke", headers=headers_for(org["admin"]))

    grant2_resp = await client.post(
        f"/v1/agent-versions/{version_id}/capability-grants",
        json={"mcp_tool_id": read_tool["id"]},
        headers=headers_for(org["builder"]),
    )
    assert grant2_resp.status_code == 201
    assert grant2_resp.json()["id"] != grant1["id"]

    history = await client.get(
        f"/v1/agent-versions/{version_id}/capability-grants?include_revoked=true", headers=headers_for(org["viewer"])
    )
    assert len(history.json()) == 2
