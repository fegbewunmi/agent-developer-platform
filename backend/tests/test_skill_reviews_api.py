"""HTTP-layer wiring for app/api/skill_reviews.py - routes, status codes, and
the DomainError -> HTTP status mapping over a real request. Service-layer
behavior (self-approval, supersession, impact analysis) is fully covered by
tests/test_skill_reviews.py.
"""


async def _publish_skill_version(client, org, headers_for, skill_name="api-review-skill", version="1.0"):
    skill_resp = await client.post(
        "/v1/skills", json={"name": skill_name, "owner_team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    skill_id = skill_resp.json()["id"]
    sv_resp = await client.post(
        f"/v1/skills/{skill_id}/versions",
        json={"version": version, "purpose": "p", "compatible_frameworks": []},
        headers=headers_for(org["builder"]),
    )
    return skill_id, sv_resp.json()["id"]


async def test_review_request_approve_flow_over_http(client, org, headers_for):
    skill_id, skill_version_id = await _publish_skill_version(client, org, headers_for)

    req_resp = await client.post(
        f"/v1/skill-versions/{skill_version_id}/review-requests", json={}, headers=headers_for(org["builder"])
    )
    assert req_resp.status_code == 201
    request_id = req_resp.json()["id"]
    assert req_resp.json()["status"] == "pending"

    queue = await client.get("/v1/skill-review-requests?status=pending", headers=headers_for(org["reviewer"]))
    assert queue.status_code == 200
    entry = next(r for r in queue.json() if r["id"] == request_id)
    assert entry["skill_name"] == "api-review-skill"

    approve_resp = await client.post(
        f"/v1/skill-review-requests/{request_id}/approve", json={"comment": "looks good"}, headers=headers_for(org["reviewer"])
    )
    assert approve_resp.status_code == 201
    assert approve_resp.json()["decision"] == "approve"

    sv_detail = await client.get(f"/v1/skill-versions/{skill_version_id}", headers=headers_for(org["builder"]))
    assert sv_detail.json()["stage"] == "recommended"

    request_detail = await client.get(f"/v1/skill-review-requests/{request_id}", headers=headers_for(org["builder"]))
    assert request_detail.json()["decision"]["decision"] == "approve"


async def test_reviewer_cannot_approve_own_request_over_http(client, org, headers_for):
    _skill_id, skill_version_id = await _publish_skill_version(client, org, headers_for, "self-approve-skill")
    req_resp = await client.post(
        f"/v1/skill-versions/{skill_version_id}/review-requests", json={}, headers=headers_for(org["reviewer"])
    )
    request_id = req_resp.json()["id"]

    approve_resp = await client.post(
        f"/v1/skill-review-requests/{request_id}/approve", json={}, headers=headers_for(org["reviewer"])
    )
    assert approve_resp.status_code == 403


async def test_skill_impact_endpoint_over_http(client, org, headers_for):
    skill_id, _old_id = await _publish_skill_version(client, org, headers_for, "impact-skill", "1.0")
    new_resp = await client.post(
        f"/v1/skills/{skill_id}/versions",
        json={"version": "2.0", "purpose": "p", "compatible_frameworks": []},
        headers=headers_for(org["builder"]),
    )
    assert new_resp.status_code == 201

    agent_resp = await client.post(
        "/v1/agents", json={"name": "impact-consumer", "team_id": str(org["team_a"].id)}, headers=headers_for(org["builder"])
    )
    agent_id = agent_resp.json()["id"]
    manifest = {
        "agent": {"name": "impact-consumer", "version": "1.0.0", "framework": "langgraph"},
        "model": {"provider": "vertex-ai", "name": "gemini-2.5-flash"},
        "skills": ["impact-skill@1.0"],
        "mcp": {"servers": [], "tools": []},
        "evaluation": {"policy": "irrelevant"},
    }
    await client.post(f"/v1/agents/{agent_id}/versions", json={"manifest": manifest}, headers=headers_for(org["builder"]))

    impact = await client.get(f"/v1/skills/{skill_id}/impact", headers=headers_for(org["builder"]))
    assert impact.status_code == 200
    body = impact.json()
    assert body["latest_version"]["version"] == "2.0"
    assert any(c["agent_name"] == "impact-consumer" for c in body["current_impact"])
