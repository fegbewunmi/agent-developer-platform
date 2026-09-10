"""MCP registry: docs/mcp-governance.md. Registration is Admin-only and
explicit (not "discovered") - see app/services/mcp.py's docstring on why.
Health checks are real HTTP calls, tested here against a real local server,
not a mocked status flip.
"""
import http.server
import threading

import pytest


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def real_health_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=2)


async def test_register_server_and_tool_admin_only(client, org, headers_for):
    resp = await client.post(
        "/v1/mcp-servers",
        json={
            "name": "incident-operations",
            "environment": "development",
            "owner_team_id": str(org["team_a"].id),
            "connection_ref": "http://127.0.0.1:8080",
        },
        headers=headers_for(org["admin"]),
    )
    assert resp.status_code == 201
    server_id = resp.json()["id"]
    assert resp.json()["health_status"] == "unknown"

    tool_resp = await client.post(
        f"/v1/mcp-servers/{server_id}/tools",
        json={"name": "create_ticket", "classification": "write", "requires_approval": True},
        headers=headers_for(org["admin"]),
    )
    assert tool_resp.status_code == 201
    tool = tool_resp.json()
    assert tool["classification"] == "write"
    assert tool["requires_approval"] is True


async def test_register_server_forbidden_for_non_admin(client, org, headers_for):
    for user_key in ("viewer", "builder", "reviewer"):
        resp = await client.post(
            "/v1/mcp-servers",
            json={
                "name": f"server-by-{user_key}",
                "environment": "development",
                "owner_team_id": str(org["team_a"].id),
                "connection_ref": "http://127.0.0.1:8080",
            },
            headers=headers_for(org[user_key]),
        )
        assert resp.status_code == 403, user_key


async def test_register_tool_forbidden_for_non_admin(client, org, headers_for):
    server_resp = await client.post(
        "/v1/mcp-servers",
        json={
            "name": "restricted-server",
            "environment": "development",
            "owner_team_id": str(org["team_a"].id),
            "connection_ref": "http://127.0.0.1:8080",
        },
        headers=headers_for(org["admin"]),
    )
    server_id = server_resp.json()["id"]
    resp = await client.post(
        f"/v1/mcp-servers/{server_id}/tools",
        json={"name": "get_investigation_status", "classification": "read", "requires_approval": False},
        headers=headers_for(org["reviewer"]),
    )
    assert resp.status_code == 403


async def test_duplicate_tool_name_on_same_server_is_409(client, org, headers_for):
    server_resp = await client.post(
        "/v1/mcp-servers",
        json={
            "name": "dup-tool-server",
            "environment": "development",
            "owner_team_id": str(org["team_a"].id),
            "connection_ref": "http://127.0.0.1:8080",
        },
        headers=headers_for(org["admin"]),
    )
    server_id = server_resp.json()["id"]
    body = {"name": "get_incident_history", "classification": "read", "requires_approval": False}
    first = await client.post(f"/v1/mcp-servers/{server_id}/tools", json=body, headers=headers_for(org["admin"]))
    assert first.status_code == 201
    second = await client.post(f"/v1/mcp-servers/{server_id}/tools", json=body, headers=headers_for(org["admin"]))
    assert second.status_code == 409


async def test_health_check_against_a_real_healthy_server(client, org, headers_for, real_health_server):
    server_resp = await client.post(
        "/v1/mcp-servers",
        json={
            "name": "healthy-server",
            "environment": "development",
            "owner_team_id": str(org["team_a"].id),
            "connection_ref": real_health_server,
        },
        headers=headers_for(org["admin"]),
    )
    server_id = server_resp.json()["id"]

    check_resp = await client.post(f"/v1/mcp-servers/{server_id}/health-check", headers=headers_for(org["viewer"]))
    assert check_resp.status_code == 200
    body = check_resp.json()
    assert body["health_status"] == "healthy"
    assert body["last_health_check_at"] is not None


async def test_health_check_against_an_unreachable_server(client, org, headers_for):
    server_resp = await client.post(
        "/v1/mcp-servers",
        json={
            "name": "unreachable-server",
            "environment": "development",
            "owner_team_id": str(org["team_a"].id),
            "connection_ref": "http://127.0.0.1:1",
        },
        headers=headers_for(org["admin"]),
    )
    server_id = server_resp.json()["id"]

    check_resp = await client.post(f"/v1/mcp-servers/{server_id}/health-check", headers=headers_for(org["viewer"]))
    assert check_resp.status_code == 200
    assert check_resp.json()["health_status"] == "unavailable"
