# Phase 5 Notes: Developer-Facing Frontend and Product Workflows

Status: complete. A real Next.js (App Router) UI over the entire backend built in Phases 1-4, live-verified against the real dev Postgres database and the real deployed `agent-eval-api` Cloud Run service - not mocked data, not a design prototype. Deployment (this platform's own backend/frontend to Cloud Run) not started, per the stop condition.

## Pages built

- **`/login`** - real dev-login flow (see "Auth integration" below), not a stub.
- **`/overview`** - the dashboard: six live counts, a "Needs Attention" list (pending review, blocked promotions, stale candidate/production evidence, unhealthy MCP), and a recent-activity feed.
- **`/agents`** - catalog: name, team, production version, a per-stage version-count rollup, representative-vs-live distinction.
- **`/agents/[agentId]`** - identity, full version history with real per-version stage, promotion history (why the current production version is actually in production), recent activity.
- **`/agents/[agentId]/versions/[versionId]`** - the core reproducibility surface: configuration (framework/model/manifest), pinned skills, MCP access (classification, approval requirement, grant status, revoked grants), evaluation (status, gate results, request-evaluation form with live polling), freshness & eligibility, and the promotion/rollback request flow.
- **`/skills`**, **`/skills/[skillId]`** - registry and detail, with exact-pinning reverse lookup (which `AgentVersion`s pin each `SkillVersion`).
- **`/mcp`**, **`/mcp/[serverId]`** - registry and detail, with a live health-check button and, per tool, which `AgentVersion`s hold a grant (active and revoked, shown distinctly).
- **`/promotions`** - the reviewer queue (`?status=pending` default, with Approved/Rejected/All tabs).
- **`/promotions/[requestId]`** - the review/decision page: full request context, gate results, "eligible when requested" vs "eligible now"/"eligible when reviewed", capabilities, approve/reject actions.
- **`/activity`** - the global audit feed, filterable by entity type.

## Major UX decisions

- **Server-first architecture, one proxy for interactivity.** Every page's initial data comes from a Server Component calling the backend directly (server-to-server, no CORS needed at all - a real, deliberate simplification over adding CORS middleware to the backend). Mutations are Server Actions (`'use server'`). The one exception is `app/api/proxy/[...path]/route.ts`, a same-origin proxy used only where a client component genuinely needs to call the backend itself (evaluation-status polling, the MCP health-check button) - it reads the JWT from the httpOnly cookie server-side and attaches it, so the token never reaches browser JS even there. See `docs/frontend-architecture.md` for the full request-flow diagram.
- **No client-state framework.** Redux/Zustand/React Query were all considered and rejected - nothing in this UI needs a client-side cache kept in sync across components; `useState`/`useActionState`/`useTransition`, scoped per-component, covered every real interaction (forms, polling, mode-switching UI).
- **The freshness distinction gets deliberate, repeated visual treatment.** "Evaluation: Passed" and "Current eligibility: Stale" are always two separate facts, never collapsed - live-verified: a real historically-passing evaluation's stale reasons (with real before/after capability-grant hashes) render without ever turning the evaluation itself red. The promotion review page extends this to three snapshots: eligible when requested (frozen), eligible now (live, for a pending request) or eligible when reviewed (frozen, once decided).
- **Gate results are never blended.** Each renders its own criterion/required/observed/pass-fail row - live-verified against a real failing gate (`completion rate >= 1.000`, observed `0.857...`, real reason text) and a real passing set.
- **Representative vs. live agents stay visually distinguishable but not apologetic** - a plain `Badge` ("Representative demo" / "Live integration"), not a warning banner or muted styling.
- **Dark, console-style visual system** (see `app/globals.css`) - a small, deliberate token set (bg/border/text tiers, one accent, four semantic status colors), no per-card accent colors, no gradients.

## New API requirements discovered

All additive, all display aggregations over existing Phase 1-4 service-layer logic, not new domain rules (see `docs/api-reference.md`'s Phase 5 entries and `docs/frontend-architecture.md`'s "frontend/backend boundary" section):

- `GET /v1/dashboard/summary` - counts + structured "Needs Attention" items + recent activity.
- `GET /v1/audit-events` - a global, filterable audit feed (previously only queryable indirectly via other entities' payloads).
- `GET /v1/promotion-requests` - a global, status-filterable list (the reviewer queue) - neither `list_promotion_requests_for_version` nor `list_promotion_history_for_agent` answered "what's pending across every Agent."
- `GET /v1/mcp-tools/{id}/grants` - which `AgentVersion`s hold a grant for a tool, mirroring the Skills side's existing reverse lookup.
- `GET /v1/agents` / `GET /v1/agents/{id}` enriched with `production_version_id`/`production_version_label`/`stage_counts` - avoids an N+1 query per row in the catalog table.
- `POST /v1/dev-login`, `GET /v1/dev-login/users` - a browser-usable version of the Phase 1 dev-login script, sharing its exact signing logic (`backend/app/auth/dev_tokens.py`, extracted this phase).

## Permission behavior

`frontend/lib/permissions.ts` mirrors `backend/app/services/permissions.py`'s decision functions exactly, used only to decide what to render. The backend remains the sole authority - proven live, not just asserted: a reviewer's approval attempt against a request that had gone stale after filing was correctly rejected with a real `409` from the backend, rendered inline in the approval form, even though the UI had already shown the "Approve" button (the UI's own freshness read was itself correct at render time; the backend's live re-check at decision time is what actually caught it - exactly the scenario the two-snapshot freshness model exists for). Self-approval prevention is enforced the same way: the review page shows "You cannot approve your own request" instead of the Approve/Reject buttons when the signed-in user is the requester, but this is UI convenience only - the backend's `can_decide_promotion` check (and, behind that, the DB trigger from Phase 1) is what actually prevents it.

## Evaluation/promotion flows - live-verified, not just built

See "Live verification" below for the full transcript. In summary: a real evaluation was requested and completed against the real deployed `agent-eval-api`'s registered stub-agent target, with live gate rendering; a real promotion was requested, reviewed by a different user, and approved, producing a real production transition visible immediately on the agent's page; a real stale-blocked approval attempt was correctly rejected with the backend's real error message rendered in the UI, with no production mutation.

## Bugs discovered

1. **A real performance bug: sequential live freshness checks made the dashboard take 25-47 seconds to load.** `GET /v1/dashboard/summary` was originally written to call `check_freshness` once per candidate/pending-request/production version, one at a time, each making two real HTTP calls to the deployed `agent-eval-api`. Fixed to run every check concurrently (`asyncio.gather`), each with its **own** `AsyncSession` rather than sharing the request's session (`AsyncSession` isn't safe for concurrent use from multiple coroutines at once - sharing one would have risked "another operation is in progress" errors, not just been slow). Brought the endpoint down to ~10 seconds for the same ~9 checks - still real network latency against a real Cloud Run service, not eliminated, but no longer accidentally serialized.
2. **The dev backend was initially pointed at the wrong `agent-eval` instance.** A separate, unrelated local project (`agent-eval`'s own dev server, from prior work) happened to already be running on port 8000 - this platform's backend's *default* `AGENT_EVAL_BASE_URL` also points at `127.0.0.1:8000`, so early live-verification runs were silently talking to a local instance with none of the real registered datasets/agents, producing misleading "could not reach agent-eval to verify current dataset identity" freshness results. Fixed by running this platform's backend on a different port (8010) with `AGENT_EVAL_BASE_URL`/`AGENT_EVAL_AUDIENCE`/`AGENT_EVAL_IMPERSONATE_SERVICE_ACCOUNT` explicitly pointed at the real deployed `agent-eval-api` - the same real integration Phase 3/4 verification used. A real operational lesson (documented here, not just fixed silently): this platform's own default config is a real local-dev default, not automatically "the real thing," and needs to be pointed deliberately at deployed dependencies for genuine live verification.
3. **Next.js 16 renamed `middleware.ts` to `proxy.ts`.** Caught immediately from the dev server's own deprecation warning (the framework's `AGENTS.md` file explicitly warns about exactly this kind of breaking rename) - migrated before writing any code that depended on the old convention.
4. **A real dependency-resolution issue, not a code bug**: `@vitejs/plugin-react@6.1.1` requires `vite@^8.0.0`, but Node's module resolution was silently falling back to an unrelated, incompatible `vite@7.3.1` installed in the user's home directory `node_modules` (found via Node's directory-walk-up resolution, since this project's own `node_modules` had no local `vite` at all until pinned explicitly). Fixed by adding `vite@8` as an explicit local devDependency.
5. **Server Action modules can't be imported into a plain Vitest bundle** - `EvaluationSection.tsx`/`PromotionSection.tsx`/`ReviewActions.tsx` import `actions.ts` (`'use server'`), which imports `lib/api.ts` (`server-only`) - `server-only` genuinely throws when loaded outside a real Next.js server context, which a Vitest+`@vitejs/plugin-react` bundle is not. Fixed by mocking the `./actions` module in the relevant test files - since the tests exercise pure display sub-components (`GateRow`, `FreshnessDisplay`) or UI-only state (`ReviewActions`' mode-switching), never the actual server call, the mock is honest, not a workaround hiding real coverage.

## Tests

**Backend**: 178 passing (170 from Phase 4 + 8 new - `tests/test_phase5_api.py` covering the new read endpoints: agent-list enrichment, audit-event filtering, the reviewer queue's context enrichment, the MCP-tool-grants reverse lookup, and dashboard-summary shape/auth).

**Frontend**: 55 passing (Vitest + React Testing Library), across 6 files:
- `lib/permissions.test.ts` (15) - every role/team/self-approval combination for all five permission functions.
- `components/Badge.test.tsx` (14) - every stage/health/classification/run-status/promotion-status/pass-fail/eligibility badge state.
- `app/.../PromotionSection.test.tsx` (6) - the freshness distinction: passed-but-stale never renders as failed, every stale reason renders individually.
- `app/.../EvaluationSection.test.tsx` (4) - gate-result rendering, including a real failing-gate shape.
- `components/ActivityFeed.test.tsx` (7) - event-type-to-label mapping including `promotion.rollback` (rendered as an ordinary event, not a special one), empty state, unmapped-event fallback.
- `app/.../ReviewActions.test.tsx` (4) - approve/reject mode-switching UI.

No end-to-end (Playwright/Cypress) suite was added - full page-level and cross-page flow correctness was instead proven via the live browser verification below, against the real running stack, which is a stronger proof for this project's actual risk (real backend integration behavior, real auth, real freshness computation) than a mocked E2E suite would have been for the same time investment.

## Live verification

Performed against the real dev Postgres database, the real deployed `agent-eval-api` Cloud Run service, and a real running `next dev` server, driven through an actual Chrome browser - not simulated.

1. **Browse agents** - the real catalog (seeded representative agents, the real `incident-investigator`, and the Phase 4 live-demo agents), with accurate production-version/lifecycle-stage rollups.
2. **Inspect Incident Investigator** - real production/version configuration, real pinned skills (`telemetry-investigation@2.1`, correctly showing `incident-investigator@4.2.0` as a pinning version via the reverse lookup), and its real, *organically* stale candidacy (capability grants genuinely drifted since Phase 3's own live verification - not staged for this demo).
3. **Inspect MCP capabilities** - the real `incident-operations` server, its four real tools including `create_ticket` (Write, human-approval-required, rendered distinctly from the three read-only tools), and a live health-check button that made a real HTTP call and updated `last_health_check_at`.
4. **Run a real evaluation** - submitted against the real deployed `agent-eval-api`'s registered `stub-agent` target from a draft version's page; completed in seconds with real gate results rendered immediately, including a genuine failing gate (`completion rate >= 1.000`, observed `0.857142857142857`) from an earlier real run, rendered exactly per the brief's required/observed/failed format.
5. **View individual gates** - confirmed no blended score anywhere; every gate type (capability-snapshot consistency, regression count, completion rate, evaluator version) renders as its own row.
6. **Request a production promotion** - a genuinely fresh candidate (`currently_eligible: true`, confirmed live) was requested for promotion by Maya Chen (builder) with a real reason, via the live form.
7. **Sign in as a different reviewer** - signed out, signed in as Priya Shah (reviewer), confirmed the review page correctly showed both `Approve`/`Reject` (not blocked, since Priya wasn't the requester).
8. **Approve** - approved with a comment; the decision recorded "Eligible when reviewed: Eligible", "Decided by Priya Shah".
9. **See the production transition** - the agent's page immediately reflected the new production version, the previous one auto-retired, and a real `agent_version.promoted`/`agent_version.retired` pair in the live activity feed timestamped seconds earlier.
10. **Inspect audit/promotion history** - the agent detail page's promotion history table showed every request (approved, rejected, pending, and the earlier rollback from Phase 4) in order, each with real requester/decider names and timestamps.

**Blocked/stale path**, demonstrated twice, both live:
- A request that was fresh at filing time went stale (a real new capability grant added afterward) before a different reviewer (Jordan Brooks) attempted approval - the backend correctly rejected it with a real `409` ("...no longer eligible for approval: dataset_changed, capability_grants_changed"), rendered inline in the approval form, with the request left `pending` and the version's lifecycle stage unchanged - no production mutation, confirmed both visually and via a direct backend check.
- `incident-investigator@4.2.0`'s real, organic staleness (see #2 above) was shown on its own page with the full "genuinely passed... evidence has simply drifted" explanatory treatment, never rendered as a retroactive failure.

## Next step

Phase 6 (deployment/observability polish, final end-to-end verification) per `docs/roadmap.md` - not started, per this phase's stop condition. This platform's own backend and frontend remain undeployed (dev-only, real database/integrations); `agent-eval` (Phase 3) is the only real Cloud Run deployment in play so far.
