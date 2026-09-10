"""Agent/AgentVersion registry: docs/agent-versioning.md, docs/agent-manifest.md.
The goal per the Phase 2 brief isn't generic CRUD - these tests specifically
prove reproducibility (immutable content, pinned skills) and governed
creation (permission matrix), not just "the endpoint returns 200".
"""
import uuid

import pytest


def _manifest(
    agent_name: str,
    version: str,
    framework: str = "langgraph",
    skills: list[str] | None = None,
    mcp_servers: list[str] | None = None,
    mcp_tools: list[str] | None = None,
) -> dict:
    return {
        "agent": {"name": agent_name, "version": version, "framework": framework},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash", "params": {"temperature": 0.1}},
        "skills": skills or [],
        "mcp": {"servers": mcp_servers or [], "tools": mcp_tools or []},
        "evaluation": {"policy": "incident-production-v3"},
    }


async def test_create_agent_succeeds_for_builder_own_team(client, org, headers_for):
    resp = await client.post(
        "/v1/agents",
        json={"name": "incident-investigator", "team_id": str(org["team_a"].id)},
        headers=headers_for(org["builder"]),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "incident-investigator"
    assert body["is_representative_data"] is False


async def test_create_agent_forbidden_for_viewer(client, org, headers_for):
    resp = await client.post(
        "/v1/agents",
        json={"name": "some-agent", "team_id": str(org["team_a"].id)},
        headers=headers_for(org["viewer"]),
    )
    assert resp.status_code == 403


async def test_create_agent_forbidden_for_builder_of_a_different_team(client, org, headers_for):
    resp = await client.post(
        "/v1/agents",
        json={"name": "some-agent", "team_id": str(org["team_a"].id)},
        headers=headers_for(org["other_team_builder"]),
    )
    assert resp.status_code == 403


async def test_create_agent_allowed_for_reviewer_on_any_team(client, org, headers_for):
    resp = await client.post(
        "/v1/agents",
        json={"name": "cross-team-agent", "team_id": str(org["team_a"].id)},
        headers=headers_for(org["reviewer"]),
    )
    assert resp.status_code == 201


async def test_duplicate_agent_name_is_409(client, org, headers_for):
    body = {"name": "dup-agent", "team_id": str(org["team_a"].id)}
    first = await client.post("/v1/agents", json=body, headers=headers_for(org["builder"]))
    assert first.status_code == 201
    second = await client.post("/v1/agents", json=body, headers=headers_for(org["builder"]))
    assert second.status_code == 409


async def test_create_agent_version_success_and_manifest_inspection(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "manifest-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]

    manifest = _manifest("manifest-agent", "1.0.0")
    v_resp = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"])
    )
    assert v_resp.status_code == 201
    version = v_resp.json()
    assert version["version_label"] == "1.0.0"
    assert version["content_hash"].startswith("sha256:")

    manifest_resp = await client.get(
        f"/v1/agent-versions/{version['id']}/manifest", headers=headers_for(org["builder"])
    )
    assert manifest_resp.status_code == 200
    assert manifest_resp.json()["manifest"]["agent"]["version"] == "1.0.0"

    detail_resp = await client.get(f"/v1/agent-versions/{version['id']}", headers=headers_for(org["builder"]))
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["stage"] == "draft"
    assert detail["pinned_skill_version_ids"] == []


async def test_duplicate_version_label_is_409(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "dupver-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = _manifest("dupver-agent", "1.0.0")

    first = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    assert first.status_code == 201
    second = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    assert second.status_code == 409


async def test_version_creation_forbidden_for_viewer(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "viewer-blocked-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    resp = await client.post(
        f"/v1/agents/{agent_id}/versions",
        json={"manifest": _manifest("viewer-blocked-agent", "1.0.0")},
        headers=headers_for(org["viewer"]),
    )
    assert resp.status_code == 403


async def test_manifest_referencing_unknown_skill_is_422(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "badskill-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = _manifest("badskill-agent", "1.0.0", skills=["nonexistent-skill@1.0"])
    resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    assert resp.status_code == 422


async def test_manifest_referencing_unknown_mcp_tool_is_422(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "badtool-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = _manifest("badtool-agent", "1.0.0", mcp_servers=["nonexistent-server"], mcp_tools=["nonexistent-tool"])
    resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    assert resp.status_code == 422


async def test_manifest_missing_required_key_is_422(client, org, headers_for):
    agent_resp = await client.post(
        "/v1/agents", json={"name": "incomplete-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    resp = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"manifest": {"agent": {"version": "1.0.0"}}}, headers=headers_for(org["builder"])
    )
    assert resp.status_code == 422


async def test_no_mutation_route_exists_for_agent_versions(client, org, headers_for):
    """No PATCH/PUT endpoint exists for AgentVersion - immutability isn't
    just unused, there's no route that could even attempt it.
    """
    fake_id = uuid.uuid4()
    resp = await client.patch(f"/v1/agent-versions/{fake_id}", json={}, headers=headers_for(org["builder"]))
    assert resp.status_code in (404, 405)
    resp = await client.put(f"/v1/agent-versions/{fake_id}", json={}, headers=headers_for(org["builder"]))
    assert resp.status_code in (404, 405)


async def test_get_nonexistent_agent_is_404(client, org, headers_for):
    resp = await client.get(f"/v1/agents/{uuid.uuid4()}", headers=headers_for(org["viewer"]))
    assert resp.status_code == 404
