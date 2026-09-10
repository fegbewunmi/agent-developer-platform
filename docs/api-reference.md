# API Reference

Every endpoint requires a valid bearer token (`docs/auth-and-approval-model.md`) except `GET /health`. This is a hand-maintained summary of intent and permission requirements; the live, authoritative shape (request/response schemas) is FastAPI's generated `GET /openapi.json` / `GET /docs` on the running service - this doc exists to answer "who can call what and why," which the generated schema doesn't say.

No `PATCH`/`PUT` route exists anywhere for `AgentVersion`, `SkillVersion`, or any other immutable resource - deliberately, per `docs/adrs/0002-immutable-versioned-artifacts.md`. A new configuration is always a new resource.

## Identity

| Method & path | Auth | Notes |
|---|---|---|
| `GET /health` | none | Liveness only |
| `GET /v1/me` | any authenticated user | Resolves the bearer token to a platform `User` |
| `GET /v1/teams` | any authenticated user | Read-only |

## Agents and versions

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/agents` | any authenticated user | Includes `is_representative_data` |
| `POST /v1/agents` | Builder (own team), Reviewer, Admin | `409` on duplicate name |
| `GET /v1/agents/{agent_id}` | any authenticated user | |
| `GET /v1/agents/{agent_id}/versions` | any authenticated user | |
| `POST /v1/agents/{agent_id}/versions` | Builder (own team), Reviewer, Admin | Body: `{"manifest": {...}}` (see `docs/agent-manifest.md`). `409` on duplicate `version_label`; `422` if the manifest references an unresolvable skill/tool or an incompatible framework |
| `GET /v1/agent-versions/{version_id}` | any authenticated user | Includes `stage` and `pinned_skill_version_ids` |
| `GET /v1/agent-versions/{version_id}/manifest` | any authenticated user | Full manifest + `content_hash` |

## Skills

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/skills` | any authenticated user | |
| `POST /v1/skills` | Builder (own team), Reviewer, Admin | `409` on duplicate name |
| `GET /v1/skills/{skill_id}` | any authenticated user | |
| `GET /v1/skills/{skill_id}/versions` | any authenticated user | |
| `POST /v1/skills/{skill_id}/versions` | Builder (owner team of the skill), Reviewer, Admin | `409` on duplicate `(skill, version)` |
| `GET /v1/skill-versions/{skill_version_id}` | any authenticated user | |
| `GET /v1/skill-versions/{skill_version_id}/agent-versions` | any authenticated user | Reverse lookup: which `AgentVersion`s pin this exact `SkillVersion` |

## MCP registry

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/mcp-servers` | any authenticated user | |
| `POST /v1/mcp-servers` | Admin only | `409` on duplicate name |
| `GET /v1/mcp-servers/{server_id}` | any authenticated user | |
| `POST /v1/mcp-servers/{server_id}/health-check` | any authenticated user | Real HTTP call to `{connection_ref}/health`; health is availability, not authorization |
| `GET /v1/mcp-servers/{server_id}/tools` | any authenticated user | |
| `POST /v1/mcp-servers/{server_id}/tools` | Admin only | `409` on duplicate `(server, name)` |
| `GET /v1/mcp-tools/{tool_id}` | any authenticated user | |

## Capability grants

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/agent-versions/{version_id}/capability-grants` | any authenticated user | `?include_revoked=true` for full history; default is active-only |
| `POST /v1/agent-versions/{version_id}/capability-grants` | Builder (own team) for `read`-classified tools; Reviewer/Admin for `write` or `requires_approval` tools | `409` on an already-active grant for the same `(version, tool)` pair |
| `POST /v1/capability-grants/{grant_id}/revoke` | Reviewer, Admin | `409` if already revoked |

## Error conventions

| Status | Meaning |
|---|---|
| `401` | Missing/invalid/expired token, or the authenticated email has no matching platform `User` |
| `403` | Authenticated, but the role/team doesn't permit this action (`app/services/permissions.py`) |
| `404` | Referenced entity (agent, version, skill, tool, grant, team) doesn't exist |
| `409` | A uniqueness or state constraint would be violated (duplicate name/version/label, duplicate active grant, already-revoked grant) |
| `422` | Well-formed request, invalid content (manifest references something unresolvable, incompatible framework) |

Every `4xx` above is a real, distinct `DomainError` subclass (`app/services/errors.py`) caught by a single set of FastAPI exception handlers (`app/main.py`) - service functions never construct HTTP responses directly, keeping the service layer testable without a running API.
