# Phase 1 Notes: Core Domain, Persistence, Authentication, Seed Organization

Status: complete, pending review. Do not proceed to Phase 2 until reviewed (per the roadmap's phase discipline).

## What was implemented

- `backend/` - a FastAPI + SQLAlchemy 2.0 (async) + Alembic service, matching `ai-operations`'/`agent-eval`'s stack (`docs/architecture.md`).
- Full Postgres schema for every entity in `docs/domain-model.md` (17 tables), via 8 hand-written Alembic migrations (`backend/migrations/versions/0001`–`0008`).
- Real JWT authentication (`backend/app/auth/`) - RS256 verification against a JWKS provider, with production (`RemoteJWKSProvider`) and test (`StaticJWKSProvider`) implementations sharing the same verification code path.
- The permission matrix from `docs/auth-and-approval-model.md` as pure, unit-tested functions (`backend/app/services/permissions.py`) - not yet wired into write endpoints, since those are Phase 2+ scope.
- A minimal read-only API surface to prove the above end-to-end: `GET /health` (public), `GET /v1/me`, `GET /v1/teams`, `GET /v1/agents`.
- `scripts/seed_orion_commerce.py` - idempotent seed of the Orion Commerce sample org (Team/User/Agent only; AgentVersion/Skill/MCP seed data is Phase 2+, since it needs manifest-validation logic that doesn't exist yet).
- 47 automated tests, all passing.

**Explicitly not built** (Phase 2+ per `docs/roadmap.md`, not attempted here): any CRUD/write endpoints (create Agent, create AgentVersion, publish SkillVersion, grant/revoke capabilities, request/decide promotions), MCP registry, evaluation integration, Pub/Sub or Cloud Tasks wiring, frontend, deployment.

## Schema and invariants

17 tables (`backend/app/models/`, one file per `docs/domain-model.md` grouping), all created via migrations and verified against a real Postgres 17 instance. Two invariants are enforced as actual database constraints, not application conventions - the application connects only as a restricted role, `agent_platform_app`, that was never granted the privileges to violate them:

| Invariant | Mechanism | Verified by |
|---|---|---|
| `AgentVersion` and `SkillVersion` are fully immutable (ADR-0002) | `UPDATE`/`DELETE` revoked for `agent_platform_app` (migration `0008`) | `test_immutability.py`: `UPDATE`/`DELETE` attempts raise `psycopg.errors.InsufficientPrivilege` |
| `AuditEvent` is insert-only (`docs/audit-model.md`) | Same mechanism, same migration | Same file, same assertion |
| At most one `production` `AgentVersionLifecycle` row per `Agent` (ADR-0007) | Partial unique index `UNIQUE (agent_id) WHERE stage='production'` (migration `0002`) | A second `production` insert for the same agent raises `UniqueViolation`; a second *agent* getting its own `production` version is unaffected (both tested) |
| No self-approval on `PromotionDecision` (ADR-0009) | `BEFORE INSERT` trigger `fn_reject_self_approval` (migration `0006`), raising SQLSTATE `23514` (`CheckViolation`) when `decided_by = requested_by` | Both the rejection and the "different reviewer succeeds" case are tested |

`AgentVersion` and `AgentVersionLifecycle` are two separate tables, not one - see `docs/agent-versioning.md#the-stage-vs-content-split` and ADR-0002's amendment, both corrected during the review before this phase started.

## Auth behavior

- Verified live, end-to-end, against a real running process (not just the test suite) - see "Live/manual verification" below.
- Token verification: RS256 signature check, `exp`, `aud`, `iss` all enforced. Confirmed to reject: missing header, malformed header, expired token, wrong audience, wrong issuer, and a token signed by a *different* key than the one the JWKS provider actually holds (i.e. signature forgery, not just claim mismatch).
- A verified token resolves to a platform `User` by `email` claim; an authenticated email with no matching `User` row is rejected (401), not silently treated as anonymous.
- The permission-matrix functions (`can_create_agent`, `can_grant_mcp_tool`, `can_decide_promotion`, etc.) are implemented and unit-tested against every row of the matrix in `docs/auth-and-approval-model.md`, including the no-self-approval rule holding even for an Admin. They are not yet reachable through the API, since no write endpoints exist yet - this is a scope boundary, not a gap.

## Seeded Orion Commerce organization

4 teams, 4 users, 3 agents, matching `docs/product-overview.md` exactly (AI Platform / SRE / Customer Support Engineering / Developer Productivity; Maya Chen–Builder, Jordan Brooks–Reviewer, Priya Shah–Reviewer, Alex Rivera–Admin; `incident-investigator` real, `customer-support-agent` and `release-risk-agent` seeded/representative). Verified idempotent - running the script twice produces no duplicate rows (`test_seed.py`, and manually against the dev DB).

## Automated test results

```
47 passed in 3.31s
```

Breakdown: 3 API tests, 9 auth tests, 9 schema-invariant tests, 22 permission-matrix tests, 4 seed tests (all against a real local Postgres 17 instance - no mocks, no SQLite substitution).

## Bugs discovered

1. **SQLAlchemy `Enum()` maps Python enum members by `.name`, not `.value`, by default.** Every enum column (`role`, `stage`, `mcp_classification`, etc.) was defined as e.g. `Enum(Role, name="role")`, which tried to insert `"BUILDER"` against a Postgres enum type whose values are lowercase (`"builder"`, matching `docs/`'s conventions and the migrations). First live run of the seed script failed immediately with `invalid input value for enum role: "BUILDER"`. Fixed by adding `pg_enum()` (`backend/app/models/enums.py`), which passes `values_callable=lambda e: [m.value for m in e]` everywhere. This is a real bug that would have shipped silently if the seed script (or any insert) hadn't actually been run against a real database - pure unit tests wouldn't have caught it.
2. **`Agent` had no field to support the "seeded agents must be visibly labeled as representative" product requirement** (`docs/product-overview.md`) - see the domain-model.md update above. Caught while writing the seed script and the `GET /v1/agents` endpoint, once there was an actual place that needed to expose the distinction.
3. **pytest-asyncio's default per-test event loop conflicts with a module-level async SQLAlchemy engine.** Six tests initially failed with `RuntimeError: ... attached to a different loop` / `Event loop is closed`. Fixed by setting `asyncio_default_fixture_loop_scope = "session"` and `asyncio_default_test_loop_scope = "session"` in `pyproject.toml`, so the whole test session shares one event loop, matching how the single long-lived `engine` object in `app/db/session.py` is actually used in production (one process, one loop).
4. **Initial self-approval test asserted the wrong exception class.** The trigger raises with `ERRCODE = '23514'`, which psycopg surfaces as `CheckViolation`, not the generic `RaiseException` the test first assumed. Caught immediately by the test itself failing with a clear message; one-line fix.

No bugs were found in the immutability/single-production-version/audit-transaction design itself - every invariant from Phase 0's docs held on the first schema that implemented it as specified, once the enum bug above was fixed.

## Architecture/ADR changes

Made *before* Phase 1 implementation began, per the review that gated this phase:

- **ADR-0002 amended**: `AgentVersion` is now fully immutable with zero exceptions; `stage` moved to a new table, `AgentVersionLifecycle`. See `docs/agent-versioning.md#the-stage-vs-content-split`.
- **`docs/mcp-governance.md`, `docs/control-plane-boundaries.md`, ADR-0004 corrected**: the `create_ticket` MCP tool's confirm-gate precisely characterized as three layers (a real code-level gate in the MCP tool function; a prompt-convention decision about *when* to set `confirm=True`; a completely ungated backend endpoint as a second bypass path) rather than generalized as "not server-enforced."
- **ADR-0005, `docs/evaluation-and-promotion.md`, `docs/gcp-architecture.md`, `docs/roadmap.md` updated**: `agent-eval`'s lack of any deployment or service-to-service auth made an explicit, named prerequisite for Phase 3, not an implicit assumption.

Made *during* Phase 1 implementation, as a direct result of building against the docs:

- `domain-model.md`: added `Agent.is_representative_data` (see "Bugs discovered" #2 above).

No other schema or lifecycle decisions from Phase 0 needed to change - the domain model, immutability model, and permission matrix all held exactly as specified once implemented.

## Live/manual verification performed

Beyond the 47 automated tests (which use a `StaticJWKSProvider` test double), the following was run against **real, separately-started processes** - not the pytest harness:

1. Started the actual `uvicorn app.main:app` process against the local dev Postgres database (`agent_dev_platform_dev`), connected as the real restricted `agent_platform_app` role.
2. Generated a fresh RSA keypair and served its public JWK from a real local HTTP server, to exercise **`RemoteJWKSProvider`** - the production code path, which the automated test suite does not cover (tests only exercise `StaticJWKSProvider`). This is a genuinely different code path: it does a real `httpx.get()` over HTTP and caches the result.
3. Confirmed `GET /health` → `200`.
4. Confirmed `GET /v1/me` and `GET /v1/teams` with no `Authorization` header → `401`.
5. Minted a real RS256 token (signed by the keypair from step 2) for the seeded user `maya.chen@orioncommerce.example` and confirmed `GET /v1/me` → `200` with the correct id/name/email/team/role, `GET /v1/teams` → the 4 seeded teams, `GET /v1/agents` → the 3 seeded agents with `is_representative_data` correctly `false` for `incident-investigator` and `true` for the other two.
6. Confirmed a garbage/malformed bearer token → `401`, not a `500` - no unhandled exception path.
7. Independently re-ran `scripts/seed_orion_commerce.py` twice against the dev database directly (outside pytest) and confirmed row counts stayed at 4 teams / 4 users / 3 agents both times.
8. Cleanly shut down both ad hoc processes (uvicorn, the local JWKS HTTP server) afterward.

## Next step

Stopping here per instruction. Phase 2 (agent/version/skill/MCP registries - CRUD, manifest validation, capability grants) does not begin until this phase is reviewed.
