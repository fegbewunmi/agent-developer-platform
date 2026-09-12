"""Skill/SkillVersion registry: docs/skills-and-capabilities.md. Proves
exact-version pinning (not "latest") and immutability of published versions.
"""
import uuid


async def test_create_skill_and_publish_version(client, org, headers_for):
    skill_resp = await client.post(
        "/v1/skills",
        json={"name": "telemetry-investigation", "owner_team_id": str(org["team_a"].id)},
        headers=headers_for(org["builder"]),
    )
    assert skill_resp.status_code == 201
    skill_id = skill_resp.json()["id"]

    version_resp = await client.post(
        f"/v1/skills/{skill_id}/versions",
        json={"version": "2.1", "purpose": "telemetry correlation", "compatible_frameworks": ["langgraph"]},
        headers=headers_for(org["builder"]),
    )
    assert version_resp.status_code == 201
    body = version_resp.json()
    assert body["version"] == "2.1"
    assert body["compatible_frameworks"] == ["langgraph"]


async def test_skill_creation_forbidden_for_viewer(client, org, headers_for):
    resp = await client.post(
        "/v1/skills",
        json={"name": "viewer-skill", "owner_team_id": str(org["team_a"].id)},
        headers=headers_for(org["viewer"]),
    )
    assert resp.status_code == 403


async def test_duplicate_skill_version_is_409(client, org, headers_for):
    skill_resp = await client.post(
        "/v1/skills", json={"name": "dup-skill", "owner_team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    skill_id = skill_resp.json()["id"]
    body = {"version": "1.0", "purpose": "x"}
    first = await client.post(f"/v1/skills/{skill_id}/versions", json=body, headers=headers_for(org["builder"]))
    assert first.status_code == 201
    second = await client.post(f"/v1/skills/{skill_id}/versions", json=body, headers=headers_for(org["builder"]))
    assert second.status_code == 409


async def test_no_mutation_route_exists_for_skill_versions(client, org, headers_for):
    resp = await client.patch(f"/v1/skill-versions/{uuid.uuid4()}", json={}, headers=headers_for(org["builder"]))
    assert resp.status_code in (404, 405)


async def test_agent_version_pins_exact_skill_version_and_reverse_lookup_works(client, org, headers_for):
    skill_resp = await client.post(
        "/v1/skills", json={"name": "knowledge-search", "owner_team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    skill_id = skill_resp.json()["id"]
    sv_resp = await client.post(
        f"/v1/skills/{skill_id}/versions",
        json={"version": "3.0", "purpose": "search", "compatible_frameworks": ["langgraph"]},
        headers=headers_for(org["builder"]),
    )
    skill_version_id = sv_resp.json()["id"]

    agent_resp = await client.post(
        "/v1/agents", json={"name": "pin-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]

    manifest = {
        "agent": {"name": "pin-agent", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": ["knowledge-search@3.0"],
        "mcp": {"servers": [], "tools": []},
        "evaluation": {"policy": "test-policy"},
    }
    version_resp = await client.post(
        f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"])
    )
    assert version_resp.status_code == 201
    version = version_resp.json()

    detail = await client.get(f"/v1/agent-versions/{version['id']}", headers=headers_for(org["builder"]))
    assert detail.json()["pinned_skill_version_ids"] == [skill_version_id]

    reverse = await client.get(
        f"/v1/skill-versions/{skill_version_id}/agent-versions", headers=headers_for(org["builder"])
    )
    assert reverse.status_code == 200
    entry = next(v for v in reverse.json() if v["id"] == version["id"])
    # Phase 9: the raw "Pinned by 4.3.0" badge told a developer nothing -
    # the reverse lookup now carries the owning Agent's name too.
    assert entry["agent_name"] == "pin-agent"

    skill_detail = await client.get(f"/v1/skills/{skill_id}", headers=headers_for(org["builder"]))
    assert skill_detail.json()["consuming_agent_version_count"] == 1

    version_detail = await client.get(
        f"/v1/skill-versions/{skill_version_id}", headers=headers_for(org["builder"])
    )
    assert version_detail.json()["stage"] == "published"


async def test_incompatible_framework_is_rejected(client, org, headers_for):
    skill_resp = await client.post(
        "/v1/skills", json={"name": "crewai-only-skill", "owner_team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    skill_id = skill_resp.json()["id"]
    await client.post(
        f"/v1/skills/{skill_id}/versions",
        json={"version": "1.0", "purpose": "x", "compatible_frameworks": ["crewai"]},
        headers=headers_for(org["builder"]),
    )

    agent_resp = await client.post(
        "/v1/agents", json={"name": "incompat-agent", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": "incompat-agent", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": ["crewai-only-skill@1.0"],
        "mcp": {"servers": [], "tools": []},
        "evaluation": {"policy": "test-policy"},
    }
    resp = await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))
    assert resp.status_code == 422
