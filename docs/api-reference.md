# API Reference

Every endpoint requires a valid bearer token (`docs/auth-and-approval-model.md`) except `GET /health`. This is a hand-maintained summary of intent and permission requirements; the live, authoritative shape (request/response schemas) is FastAPI's generated `GET /openapi.json` / `GET /docs` on the running service - this doc exists to answer "who can call what and why," which the generated schema doesn't say.

No `PATCH`/`PUT` route exists anywhere for `AgentVersion`, `SkillVersion`, or any other immutable resource - deliberately, per `docs/adrs/0002-immutable-versioned-artifacts.md`. A new configuration is always a new resource.

## Identity

| Method & path | Auth | Notes |
|---|---|---|
| `GET /health` | none | Liveness only |
| `GET /v1/me` | any authenticated user | Resolves the bearer token to a platform `User` |
| `GET /v1/teams` | any authenticated user | Read-only |
| `GET /v1/dev-login/users` | none | Dev-only (only registered when the backend has `AUTH_JWKS_FILE` set - never in a real deployment). Lists the seeded users the frontend's `/login` page can sign in as |
| `POST /v1/dev-login` | none | Dev-only, same gating. Body: `{"email": "..."}`, must be one of the seeded users. Returns a real, backend-verifiable JWT signed with the same key `scripts/dev_login.py` uses - see `docs/frontend-architecture.md` |

## Agents and versions

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/agents` | any authenticated user | Includes `is_representative_data`, and (Phase 5) `production_version_id`/`production_version_label`/`stage_counts` - a display aggregation over `AgentVersionLifecycle`, not new domain logic |
| `POST /v1/agents` | Builder (own team), Reviewer, Admin | `409` on duplicate name |
| `GET /v1/agents/{agent_id}` | any authenticated user | Same Phase 5 enrichment as the list endpoint |
| `GET /v1/agents/{agent_id}/versions` | any authenticated user | |
| `POST /v1/agents/{agent_id}/versions` | Builder (own team), Reviewer, Admin | Body: `{"manifest": {...}}` (see `docs/agent-manifest.md`). `409` on duplicate `version_label`; `422` if the manifest references an unresolvable skill/tool or an incompatible framework |
| `GET /v1/agent-versions/{version_id}` | any authenticated user | Includes `stage` and `pinned_skill_version_ids` |
| `GET /v1/agent-versions/{version_id}/manifest` | any authenticated user | Full manifest + `content_hash` |

## Audit (Phase 5)

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/audit-events` | any authenticated user | Query: `entity_type`, `entity_id`, `limit` (default 50, max 200). Powers the frontend's Activity page and dashboard recent-activity feed - a thin list wrapper over `AuditEvent`, no new event types |

## Dashboard (Phase 5)

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/dashboard/summary` | any authenticated user | Counts (production agents, candidate versions, pending-my-review, blocked promotions, stale candidate evidence, unhealthy MCP servers) plus a structured `needs_attention` list and recent activity. Runs live `check_freshness` calls, concurrently, against every candidate/production `AgentVersion` and pending `PromotionRequest` - see `docs/phase-notes/phase-5.md`'s "Bugs discovered" for why concurrency here matters |

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
| `GET /v1/mcp-tools/{tool_id}/grants` | any authenticated user | Phase 5. "Which `AgentVersion`s have a grant for this tool" - mirrors `GET /v1/skill-versions/{id}/agent-versions`'s reverse lookup. Query: `include_revoked` |

## Capability grants

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/agent-versions/{version_id}/capability-grants` | any authenticated user | `?include_revoked=true` for full history; default is active-only |
| `POST /v1/agent-versions/{version_id}/capability-grants` | Builder (own team) for `read`-classified tools; Reviewer/Admin for `write` or `requires_approval` tools | `409` on an already-active grant for the same `(version, tool)` pair |
| `POST /v1/capability-grants/{grant_id}/revoke` | Reviewer, Admin | `409` if already revoked |

## Evaluation policies

| Method & path | Auth | Notes |
|---|---|---|
| `GET /v1/evaluation-policies` | any authenticated user | |
| `POST /v1/evaluation-policies` | Admin only | `409` on duplicate `(name, version)`. No edit endpoint - immutable, see [ADR-0015](adrs/0015-evaluation-policy-immutability.md) |
| `GET /v1/evaluation-policies/{policy_id}` | any authenticated user | |

## Evaluations

| Method & path | Auth | Notes |
|---|---|---|
| `POST /v1/agent-versions/{agent_version_id}/evaluations` | Builder (own team), Reviewer, Admin | Body: `{"external_agent_version_id": "...", "idempotency_key": "..." (optional)}`. Returns `202` with `status: "requested"` immediately - the real `agent-eval` call happens asynchronously (see [`evaluation-and-promotion.md`](evaluation-and-promotion.md)). `404` if no `EvaluationPolicy` exists for the agent; `422` if the policy's required dataset/evaluator isn't currently resolvable in `agent-eval`; `409` if the version isn't in `draft`/`evaluating` |
| `GET /v1/agent-versions/{agent_version_id}/evaluations` | any authenticated user | All `EvaluationRunReference`s for this version, newest first |
| `GET /v1/evaluations/{reference_id}` | any authenticated user | Status, summary evidence (`dimension_stats`, case counts), `external_run_id` for deeper inspection in `agent-eval` |
| `GET /v1/evaluations/{reference_id}/gates` | any authenticated user | One row per gate criterion - never a blended score |
| `GET /v1/agent-versions/{agent_version_id}/candidacy` | any authenticated user | Live-computed: `historically_passed` (permanent fact) vs. `currently_eligible` (computed fresh every call) with explicit `stale_findings[]` - see [`evaluation-and-promotion.md`](evaluation-and-promotion.md#evidence-freshness) |

## Promotions

No generic update endpoint - every state transition is its own explicit action.

| Method & path | Auth | Notes |
|---|---|---|
| `POST /v1/agent-versions/{agent_version_id}/promotion-requests` | Builder (own team), Reviewer, Admin | Body: `{"reason": "..." (optional)}`. `201` with the created `PromotionRequest` (full context snapshot - see [ADR-0018](adrs/0018-promotion-request-immutability.md)). `409` if the version isn't `candidate`/`retired`, if a pending request already exists for it, or if it isn't currently eligible (evidence not fresh, or no passing evaluation at all) |
| `GET /v1/agent-versions/{agent_version_id}/promotion-requests` | any authenticated user | All `PromotionRequest`s for this version, newest first |
| `GET /v1/promotion-requests` | any authenticated user | Phase 5. The reviewer queue - every `PromotionRequest`, optionally filtered by `?status=`, enriched with agent/version/requester/decider display names (a display join, not new logic) |
| `GET /v1/promotion-requests/{promotion_request_id}` | any authenticated user | The request plus its `PromotionDecision`, if one exists (`decision: null` while pending) |
| `POST /v1/promotion-requests/{promotion_request_id}/approve` | Reviewer, Admin - never the requester | Body: `{"comment": "..." (optional)}`. `201` with the created `PromotionDecision`. Re-checks freshness live at decision time; `409` if no longer eligible (no production mutation happens), if the request was already decided, or if the cited gate results no longer all pass (defense-in-depth; expected unreachable since gate results are immutable) |
| `POST /v1/promotion-requests/{promotion_request_id}/reject` | Reviewer, Admin - never the requester | Body: `{"comment": "..." (optional)}`. `201` with the created `PromotionDecision`. Never blocked by staleness - the cited `AgentVersion` stays `candidate`/`retired`, unchanged |
| `GET /v1/agents/{agent_id}/promotion-history` | any authenticated user | Every `PromotionRequest` (with its decision, if any) across every `AgentVersion` this `Agent` has ever had, newest first - answers "why is this exact version in production right now?" without reconstructing intent from mutable tables |

Rollback is not a separate endpoint - it's an ordinary `POST .../promotion-requests` against an old, `retired` `AgentVersion`, gated identically (see [`evaluation-and-promotion.md`](evaluation-and-promotion.md#promotion-lifecycle)).

## Internal (Cloud Tasks push target)

| Method & path | Auth | Notes |
|---|---|---|
| `POST /internal/tasks/evaluations/{reference_id}` | none at the application layer - Cloud Run's own IAM authenticates the push in production | Not for direct use; the real Cloud Tasks receiver target (`app/services/job_dispatch.py::CloudTasksDispatcher`). See `docs/gcp-architecture.md` |

## Error conventions

| Status | Meaning |
|---|---|
| `401` | Missing/invalid/expired token, or the authenticated email has no matching platform `User` |
| `403` | Authenticated, but the role/team doesn't permit this action (`app/services/permissions.py`) |
| `404` | Referenced entity (agent, version, skill, tool, grant, team) doesn't exist |
| `409` | A uniqueness or state constraint would be violated (duplicate name/version/label, duplicate active grant, already-revoked grant) |
| `422` | Well-formed request, invalid content (manifest references something unresolvable, incompatible framework) |

Every `4xx` above is a real, distinct `DomainError` subclass (`app/services/errors.py`) caught by a single set of FastAPI exception handlers (`app/main.py`) - service functions never construct HTTP responses directly, keeping the service layer testable without a running API.
