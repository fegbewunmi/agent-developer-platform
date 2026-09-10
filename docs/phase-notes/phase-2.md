# Phase 2 Notes: Agent, Version, Skill, and MCP Registries

Status: complete, pending review. Do not proceed to evaluation/promotion/frontend work until this phase is reviewed.

## Implementation summary

Built the write flows (not generic CRUD) for `Agent`, `AgentVersion`, `Skill`, `SkillVersion`, `MCPServer`, `MCPTool`, and `AgentCapabilityGrant` on top of Phase 1's schema, auth, and permission matrix - no schema change was needed for the core tables (Phase 1's design held), one new migration added a constraint Phase 1's schema didn't yet need (see "Schema/API additions"). Every write goes through a service-layer function (`app/services/`) that checks permissions, validates, writes the domain row(s) and an `AuditEvent` in one transaction, and commits once. API routers are thin translators from HTTP to service calls and back (`docs/api-reference.md`).

The two required live workflows both work end-to-end against the real database and a real running server: creating a real `AgentVersion` for `incident-investigator` with three pinned skill versions and inspecting its manifest; and granting/revoking real Incident Operations MCP capabilities with a live role boundary and intact history. See "Live verification" below.

## APIs added

25 new endpoints across four routers (`app/api/agents.py`, `skills.py`, `mcp.py`, `capability_grants.py`), full list with required roles in `docs/api-reference.md`. Summary: agent/version create+read, skill/skill-version create+read plus a reverse lookup (which agent versions pin a given skill version), MCP server/tool registration + health-check, capability grant/revoke + effective-access listing. No `PATCH`/`PUT` route exists anywhere - verified by test (`test_no_mutation_route_exists_for_agent_versions`, `test_no_mutation_route_exists_for_skill_versions`), not just by omission.

## Version/immutability behavior

`AgentVersion` creation validates and resolves the full manifest in one call (`app/services/manifest.py`): required top-level keys, skill references resolved to real `SkillVersion` rows (with a framework-compatibility check), MCP tool references resolved to real `MCPTool` rows on a declared server, and a `content_hash` computed over the canonicalized manifest. The `AgentVersion` row, its `AgentVersionSkill` pins, and its initial `AgentVersionLifecycle(stage=draft)` row are written in one transaction. `AgentVersion` itself remains fully immutable at the database level (Phase 1's `REVOKE UPDATE/DELETE` on the `agent_platform_app` role) - Phase 2 added no exception to that.

**Resolved design question - attachment timing:** no draft composition phase exists. Skills are pinned exactly once, atomically with version creation, per the manifest supplied in that single request. See `docs/skills-and-capabilities.md#attachment-timing-no-draft-composition-phase` for the full reasoning, which follows directly from ADR-0002 rather than inventing a new rule.

## Skill versioning behavior

`SkillVersion` publication is one-way (no edit endpoint, immutable at the DB level like `AgentVersion`). An `AgentVersion`'s manifest must reference skills as `name@version` and that exact pair must already exist and be framework-compatible - there is no "latest" resolution anywhere in the write path. Verified by test: duplicate `SkillVersion` is `409`; an unknown skill or an incompatible-framework skill in a manifest is `422`; the reverse lookup (`GET /v1/skill-versions/{id}/agent-versions`) correctly returns only versions that actually pin that exact skill version.

## MCP registry behavior

Registration is Admin-only and explicit - re-inspected `ai-operations/mcp_server/server.py` and confirmed (via the live backend's own `GET /openapi.json`) there is no introspection endpoint to poll, so no discovery mechanism was built; the four real tools (`get_investigation_status`, `search_documents`, `get_incident_history`, `create_ticket`) are registered via `scripts/seed_orion_commerce.py` calling the same API endpoint an Admin would, with names/classifications/`requires_approval` values read directly from source, not invented. `docs/mcp-governance.md` documents this decision and why discovery wasn't practical.

Health checks are real HTTP calls (`GET {connection_ref}/health`), not simulated - live-verified against the actual running `ai-operations` backend (`http://127.0.0.1:8080`), returning `healthy`. Tested against both a real local server (via Python's `http.server` in a background thread) and a genuinely unreachable address, proving both the `healthy` and `unavailable` paths against real sockets, not mocks.

**The three-layer authorization/approval/execution distinction was preserved, not re-litigated** - `docs/mcp-governance.md`'s precise breakdown (a real code-level gate in the MCP tool function; a prompt-convention decision about *when* to set `confirm=True`; a completely ungated backend endpoint as a second bypass path) is unchanged and still describes the real, current state of `ai-operations` (confirmed unchanged via `git log` on the relevant files during this phase).

## Capability grant/revocation semantics

Grant authority scales with risk, enforced server-side and tested negatively: a `Builder` can grant read-classified tools for their own team only; granting a write-capable or `requires_approval` tool requires Reviewer or Admin, full stop - a `Builder` attempting one gets `403` (live-verified, not just unit-tested). Revocation is Reviewer/Admin only, sets `revoked_by`/`revoked_at` on the existing row (never deletes or edits history), and a DB partial unique index (migration `0009`) backstops the API's own duplicate-active-grant check.

**Real design correction found this phase:** Phase 0's `mcp-governance.md` described a Builder-requests/Reviewer-approves two-step flow for write-capable grants. Building the actual endpoint showed this was never load-bearing - nothing in the domain model names a request entity for grants, and the live-verification flow this phase was built to prove is a direct grant by an already-authorized actor. Corrected in `docs/mcp-governance.md` rather than silently implementing the more complex version or silently deviating without a note.

**The reproducibility tradeoff, answered explicitly** (full reasoning in [ADR-0014](../adrs/0014-capability-grant-reproducibility.md)):
- A revoked capability never appears differently in the historical manifest - the manifest never showed live authorization in the first place, only declared intent, and it's immutable regardless.
- "Reproduce this version" has two different valid meanings - reproduce the *build* (fully answered by the manifest, unconditionally) vs. reproduce the *authorized runtime behavior at a past moment* (answered by querying `AgentCapabilityGrant.granted_at`/`revoked_at`, not the manifest).
- Yes, evaluations should record a capability-grant snapshot/hash, following the existing `dataset_snapshot_hash` pattern - not built this phase (no `EvaluationRunReference` yet), tracked as a named Phase 3 requirement rather than silently deferred.

## Authorization behavior

Every write endpoint enforces the Phase 1 permission matrix via `app/services/permissions.py`, with negative tests for all four roles on every write operation that has a restriction: agent/skill creation (Builder-own-team-or-above, Viewer forbidden, cross-team Builder forbidden), MCP server/tool registration (Admin-only, Viewer/Builder/Reviewer all forbidden), capability grant (read: Builder-own-team-or-above; write/approval-required: Reviewer/Admin only, Builder forbidden), capability revoke (Reviewer/Admin only, Builder forbidden). No new roles were added.

## Audit guarantees

Every write emits at least one `AuditEvent` in the same transaction as the domain change (`app/services/audit.py::record_audit_event`, called mid-transaction, never separately committed). Event types implemented: `agent.created`, `agent_version.created`, `skill.created`, `skill_version.published`, `mcp_server.registered`, `mcp_tool.registered`, `capability.granted`, `capability.revoked` - matching the brief's list exactly (using `mcp_tool.registered` per the brief's own "registered or discovered, depending on the chosen model" - registered, since discovery wasn't practical). The transactional guarantee is proven, not just asserted: `tests/test_audit_transaction.py` monkeypatches the audit-recording call to raise mid-transaction and confirms the domain row (an `Agent`) does not exist after rollback.

## Tests

**82 passed** (up from Phase 1's 47; 35 new). New files: `test_agents_registry.py`, `test_skills_registry.py`, `test_mcp_registry.py`, `test_capability_grants.py`, `test_audit_transaction.py`; extended `test_immutability.py` with the Phase 2 partial-unique-index invariant, tested through the real restricted `agent_platform_app` role exactly as Phase 1 established. Coverage matches every item on the Phase 2 test list: registry creation/read, immutable version behavior (including the no-PATCH-route check), exact skill-version pinning + incompatible-framework rejection, permission enforcement (positive and negative for all four roles), grant/revoke behavior (including re-grant-after-revoke creating a new row), DB constraints (immutability, single-production-version carried from Phase 1, duplicate-active-grant), audit event creation, transaction rollback on audit failure, representative-vs-real agent metadata, and MCP tool classification/approval metadata.

## Bugs discovered

1. **Two API routers were never registered in `main.py`.** `skills.versions_router` (the `/v1/skill-versions/...` routes) was omitted entirely on first wiring - caught immediately by checking the live OpenAPI schema before writing a single test, not by a test itself. A reminder that "the app imports without error" is not the same as "every route exists."
2. **A real, live bug: timezone-naive vs. timezone-aware datetime binding.** `MCPServer.last_health_check_at` and `AgentCapabilityGrant.revoked_at` were declared as bare `Mapped[datetime | None]` with no explicit column type. SQLAlchemy inferred a timezone-naive bind type for the ORM layer even though the actual Postgres columns were correctly `timestamptz` (the migrations were right; only the ORM model's client-side type inference was wrong) - the first live call that set one of these fields from Python (`datetime.now(timezone.utc)`) failed with `asyncpg.exceptions.DataError: can't subtract offset-naive and offset-aware datetimes`. Root-caused and fixed by introducing a shared `UTCDateTime` type (`app/models/types.py`) and applying it to every timestamp column across all six model files - including two Phase 1 columns (`EvaluationRunReference.completed_at`/`fetched_at`) that hadn't hit the bug yet only because nothing sets them until Phase 3. This is exactly the kind of bug automated tests with mocked time wouldn't have caught; it only surfaced by actually running a real request against real Postgres.
3. **A real design gap, not a bug: the request/approve capability-grant workflow described in Phase 0's docs was never actually specified anywhere in the domain model**, and building the real endpoint forced the question. See "Capability grant/revocation semantics" above and the correction in `docs/mcp-governance.md`.

## Architecture/ADR changes

- **New: [ADR-0014](../adrs/0014-capability-grant-reproducibility.md)** - the capability-grant reproducibility tradeoff, answered explicitly per the brief's three questions, with a named (not silent) Phase 3 requirement.
- **`docs/mcp-governance.md` corrected**: removed the two-step request/approve grant workflow that was never actually built or specified as an entity; documented the real discovery-not-practical finding and the real health-check mechanism; fixed the registered-name inconsistency (`trace-incidents` is the MCP process's own internal name; `incident-operations` is what this platform registers it as, matching `agent-manifest.md`'s example).
- **`docs/skills-and-capabilities.md` extended**: confirmed and explained the no-draft-composition-phase decision.
- **`docs/roadmap.md` updated**: Phase 2 marked complete; the `evaluation.policy` validation relaxation and the `capability_grant_snapshot_hash` addition both named as explicit Phase 3 carry-forward items, not silent gaps.
- **`docs/api-reference.md` added.**

## Live verification

Real Postgres, a real running `uvicorn` process against the dev database (connected as the actual restricted `agent_platform_app` role), real RS256 tokens for the real seeded users, and the real live `ai-operations` backend on port 8080 (unrelated to this session, already running, used as-is).

1. **Builder flow**: Maya Chen (Builder, AI Platform) created a real `AgentVersion` (`incident-investigator@4.2.0`) via `POST /v1/agents/{id}/versions`, using the exact manifest shape from `docs/agent-manifest.md`'s example, with all three real skill versions (`telemetry-investigation@2.1`, `deployment-analysis@1.3`, `knowledge-search@3.0`) pinned. Confirmed via `GET /v1/agent-versions/{id}` (`stage: draft`, three `pinned_skill_version_ids`) and `GET /v1/agent-versions/{id}/manifest` (full manifest + `content_hash`).
2. **Grant/revoke flow**: confirmed Maya could grant a read tool (`get_investigation_status`) but was rejected (`403`) attempting to grant the write tool (`create_ticket`); confirmed Jordan Brooks (Reviewer, SRE) could grant `create_ticket`; listed effective access (2 active grants); Jordan revoked the `create_ticket` grant (`200`, `revoked_by`/`revoked_at` populated); confirmed effective access dropped to 1 while `?include_revoked=true` still showed both grants, one marked revoked.
3. **Real MCP health check**: `POST /v1/mcp-servers/{id}/health-check` against the registered `incident-operations` server (`connection_ref: http://127.0.0.1:8080`) returned `healthy` from a genuine `GET http://127.0.0.1:8080/health` call to the live `ai-operations` backend.
4. **Audit trail cross-check**: queried `audit_events` directly and confirmed the exact sequence (`agent_version.created`, two `capability.granted`, one `capability.revoked`) matching the live actions, in order, with correct timestamps.
5. Cleanly shut down both ad hoc processes (the verification `uvicorn` instance and its local JWKS HTTP server) afterward; the already-running `ai-operations`/`agent-eval` processes were left untouched.

## Next step

Stopping here per instruction. Not beginning Agent Evaluation Platform integration, evaluation policies, promotion gates, promotion lifecycle, or frontend work until this phase is reviewed.
