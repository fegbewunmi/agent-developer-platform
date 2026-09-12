# Roadmap

The brief's suggested phase structure held up against the architecture - no restructuring was needed, only sequencing details filled in from what Phase 0 research found (e.g. auth has to land in Phase 1, not later, since nothing can be attributed to a real user without it).

Every implementation phase below ends with: automated tests, real/live verification where applicable, bugs discovered, architecture/ADR changes if any, phase notes (`docs/phase-notes/phase-N.md`), README/docs updates, and a commit.

## Phase 0 - Architecture and documentation *(this phase)*

Inspect `ai-operations`, `agent-eval`, `doc-qa`; design domain model, service boundaries, lifecycle, GCP architecture, ADRs, diagrams. No application code. **Stop and review before Phase 1.**

## Phase 1 - Core domain, persistence, seed organization

- Postgres schema + Alembic migrations for every entity in `domain-model.md`.
- `User`/`Team` + Identity Platform JWT verification (auth has to exist before any "who did this" field means anything).
- `scripts/seed_orion_commerce.py` - the four teams, four users, three agents (one real integration reference, two representative) from `product-overview.md`.
- DB-level enforcement: manifest immutability, `UNIQUE (agent_id) WHERE stage='production'`.

## Phase 2 - Agent / version / skill / MCP registries *(complete, see `docs/phase-notes/phase-2.md`)*

- Write flows (not generic CRUD) for `Agent`, `AgentVersion` (manifest validation and resolution, per `agent-manifest.md`), `Skill`, `SkillVersion`, `MCPServer`, `MCPTool`, `AgentCapabilityGrant` - all through a permission-checked, audited service layer.
- `MCPServer`/`MCPTool` registry, seeded from the real Incident Operations MCP tools (explicit registration, not discovery - `docs/mcp-governance.md`).
- `AgentCapabilityGrant` grant/revoke, with the read-vs-write authority split from `auth-and-approval-model.md`; DB-level partial-unique-index backstop against duplicate active grants.
- Real HTTP health checks against the live `ai-operations` backend, triggered on demand. **Phase 6 update**: `connection_ref` was found pointing at a local-dev placeholder in the deployed environment and repointed at `ai-ops-api`'s real Cloud Run URL, with a real live health check confirming `healthy`; a periodic Cloud Scheduler-triggered version of the same call was *not* built (deliberately left as a named gap, not required by the Phase 6 brief) - see `docs/mcp-governance.md` and `docs/phase-notes/phase-6.md`.
- **Known gap carried forward to Phase 3:** `agent-manifest.md` says `evaluation.policy` "must resolve to an existing `EvaluationPolicy`," but that registry doesn't exist until Phase 3. Phase 2's manifest validation (`app/services/manifest.py`) only checks the key is present with a non-empty string value - real resolution is Phase 3's job, once `EvaluationPolicy` CRUD exists.

## Phase 3 - Agent Evaluation Platform integration + policy/gates *(complete, see `docs/phase-notes/phase-3.md`)*

`agent-eval` was deployed to Cloud Run this phase (`agent-eval-api`, [ADR-0016](adrs/0016-agent-eval-deployment-decision.md)), resolving Phase 0's deferred deployment prerequisite - both real live workflows below ran against it, not a local stand-in.

- `EvaluationPolicy` CRUD (Admin-only), fully immutable at the DB level ([ADR-0015](adrs/0015-evaluation-policy-immutability.md)).
- `app/services/manifest.py`'s `evaluation.policy` resolution remains a presence-only check (the Phase 2 gap noted here previously) - closing it fully would mean validating against a *specific* policy version at manifest-creation time, which conflicts with policies being resolved by *name* (always "current for this agent") rather than pinned per-version; left as-is deliberately, not revisited this phase.
- Async dispatch implemented via two `JobDispatcher` implementations - `LocalSyncDispatcher` (used throughout this phase's tests and live demos) and a real `CloudTasksDispatcher` (proven to create/enqueue genuine tasks against a real queue; delivery-to-a-live-receiver fully closed and live-verified in Phase 6, including duplicate-delivery idempotency and failed-task behavior). See [`evaluation-and-promotion.md`](evaluation-and-promotion.md#async-dispatch-whats-real-and-what-isnt).
- `EvaluationRunReference` + `EvaluationGateResult` computation (11 gate types across 6 gate categories), freshness re-checks with explicit stale reasons.
- `EvaluationRunReference.capability_grant_snapshot_hash`, per [ADR-0014](adrs/0014-capability-grant-reproducibility.md) - implemented, and live-verified as a real trigger for both a mid-run consistency gate and a post-pass freshness finding.
- `draft → evaluating → candidate` lifecycle automation, live-verified against the real `incident-investigator` agent: a real ~4-minute evaluation on the deployed `agent-eval-api`, 11/11 gates passed, real `candidate` transition.
- **Known, named gap carried forward**: `dataset_case_set_fingerprint` (the dataset-freshness proxy) cannot detect a dataset case's content changing in place - only structural changes (added/removed/renamed/re-tagged cases) - because `agent-eval`'s real API never exposes case content outside of a run response. See `docs/open-questions.md`.

## Phase 4 - Promotion lifecycle, approvals, audit trail *(complete, see `docs/phase-notes/phase-4.md`)*

`PromotionRequest`/`PromotionDecision` tables and the no-self-approval DB trigger already existed and were unit-tested (Phase 1) - Phase 4 built the service/API layer that actually uses them.

- `candidate → production` request/decision service and API (`app/services/promotions.py`), built on top of Phase 3's `check_freshness` - a `PromotionRequest` is rejected outright, per [ADR-0008](adrs/0008-automated-gates-vs-human-approval.md), if `currently_eligible` is false at request time, and freshness is re-checked live a **second** time at decision time ([ADR-0018](adrs/0018-promotion-request-immutability.md)).
- Concurrent-promotion handling exercising the DB constraint that's been in place since Phase 1 - via a per-Agent `pg_advisory_xact_lock`, live-verified with a real two-session concurrency test ([ADR-0007](adrs/0007-promotion-state-machine.md)'s Phase 4 update).
- Pub/Sub outbox publication - `OutboxEvent` (transactional outbox) + a real `agent-platform-events` topic, live-verified with a real publish and a real confirmed delivery ([ADR-0020](adrs/0020-promotion-lifecycle-event-outbox.md)). Scoped to `agent_version.promoted` only this phase, not the full audit-event catalog.
- Rollback path (`retired → production` via a normal `PromotionRequest`) - live-verified end-to-end: a real `v2` promotion superseded a real `v1`, then `v1` was promoted again from `retired`, with full history preserved throughout.
- **Known, named gap carried forward**: a standalone manual `candidate/draft → retired` "abandon" action was not built - out of the brief's actual Phase 4 scope, and not needed for any of this phase's required demonstrations (the only path to `retired` is automatic supersession). See [`evaluation-and-promotion.md`](evaluation-and-promotion.md) for detail.

## Phase 5 - Frontend / product workflows *(complete, see `docs/phase-notes/phase-5.md`)*

- Next.js (App Router) developer-facing UI: dashboard, agent catalog, agent/version detail, manifest viewer, skills registry, MCP registry, evaluation status + gate detail, promotion request/review, audit timeline - the full surface list from the brief. See [`frontend-architecture.md`](frontend-architecture.md).
- Dashboard "Needs Attention": pending-my-review, blocked promotions, stale candidate/production evidence, unhealthy MCP integrations, recent activity - all real, live-computed backend state (`GET /v1/dashboard/summary`), no invented warnings.
- Real Phase 1 auth integration (dev-login flow minting a genuine, backend-verified JWT - never a frontend-only mock); backend authorization remains the sole source of truth, proven live by a real `409` when a stale-blocked approval was attempted through the UI.
- A handful of new backend read endpoints (global audit events, the global promotion-request reviewer queue, the MCP-tool-grants reverse lookup, the dashboard summary, enriched `Agent` responses) - each a display aggregation over existing Phase 1-4 service functions, not new domain logic.
- **Known gap carried forward**: no automated end-to-end (Playwright/Cypress) test suite - page-level and full-flow correctness (login → browse → evaluate → promote → approve → production transition → stale-block) was proven via real live browser verification against the running backend/database/deployed `agent-eval-api` instead, documented with a full transcript in the phase notes; unit/component tests (Vitest + React Testing Library) cover permission logic, freshness/gate rendering, and the approve/reject UI in isolation.

## Phase 6 - Production-style deployment, operational verification, observability *(complete, see `docs/phase-notes/phase-6.md`)*

- `agent-platform-api` and `agent-platform-web` deployed to Cloud Run; real production auth (Identity Platform, `dev-login` correctly unavailable in the deployed environment); real service-to-service auth to `agent-eval-api` via the backend's own attached service account.
- Cloud Tasks delivery closed end-to-end and live-verified: real creation → authenticated push → receiver processing → gate computation → lifecycle update, plus duplicate-delivery idempotency and failed-task (non-retried) behavior.
- Pub/Sub outbox durability closed: `sweep_unpublished_outbox_events` + a real Cloud Scheduler job (`agent-platform-outbox-sweep`, every 5 minutes), live-verified with a real pulled message.
- Cloud SQL: all 16 migrations proven reproducible against a fresh database; deployed runtime role (`agent_platform_app`) confirmed least-privilege; no-self-approval live-verified under real deployed credentials.
- MCP `connection_ref` real-deployment gap found and fixed (a new admin-only `PATCH` endpoint); live health check against the real `ai-ops-api` confirmed healthy.
- Structured JSON logging + 7 log-based Cloud Monitoring metrics; Cloud Trace deliberately not added (reasoned decision, not an oversight - see phase notes).
- Dashboard performance measured in the deployed environment (not assumed): ~650ms-1.7s, no further optimization needed - the Phase 5 concurrent-freshness-check fix had already resolved the earlier ~10s figure.
- Full documentation pass, new ADR ([0021](adrs/0021-cloud-tasks-application-level-push-auth.md)), updated diagrams, and real end-to-end verification through the actual deployed frontend covering the successful/stale/rollback/authorization-denial/failure scenarios the brief required.

This is the final *planned* phase. See [`open-questions.md`](open-questions.md) and phase-6 notes' "Known limitations" for what remains genuinely open (a real Pub/Sub subscriber service, scheduled MCP health checks, Cloud Trace) - none block calling this a complete, deployed control plane.

## Phase 7 - Public interactive demo sandbox *(complete, see `docs/phase-notes/phase-7.md`)*

Requested directly by the user after Phase 6's closure, not part of the original plan: a real, publicly reachable demo - two dedicated Identity Platform identities (`demo-builder`/`demo-reviewer`), a "Continue as demo Builder/Reviewer" one-click sign-in, and a new, additive backend authorization rule (`permissions.demo_containment_ok`, [ADR-0022](adrs/0022-public-demo-sandbox.md)) closing the one real gap the existing team-scoped checks didn't cover - Reviewer/Admin's intentional cross-team authority (ADR-0010) must not extend to a public account. Live-verified end to end (create/use a sandbox version, evaluate, promote, switch roles, approve, confirm no-self-approval, confirm the canonical Orion Commerce data was completely untouched) against the real deployed system - see phase-7 notes for the full transcript and the two real UX/isolation bugs found and fixed along the way.

## Phase 8 - Product correction: registry/review platform, not deployment; real source provenance *(complete, see `docs/phase-notes/phase-8.md`)*

Requested directly by the user, in two steps: an initial proposal to extend Orion into managing real Cloud Run candidate deployments and production traffic was reviewed and **withdrawn** before any of it was built - the corrected direction (ADR-0023) keeps Orion centered on publishing, discovery, evaluation, and review, never deployment. What shipped:

- **Terminology corrected to match**: `Stage` enum renamed in place (`candidate`/`production`/`retired` → `evaluated`/`recommended`/`deprecated`, `ALTER TYPE ... RENAME VALUE` - zero data loss, verified against every prior phase's real historical data) plus matching UI/API copy throughout, without touching the underlying state machine, invariants, or the `PromotionRequest`/`PromotionDecision` schema (ADR-0023 explains the scoping).
- **Real source provenance** (the actual gap identified): `AgentVersion.provenance` + `Agent.requires_ci_provenance` - an Agent flagged this way accepts versions *only* from a dedicated CI machine identity (`agent-platform-ci-publisher`, Workload Identity Federation, never a stored key - ADR-0024), never a human, regardless of role.
- **A complete, real, live CI pipeline** for `incident-investigator`: a real GitHub Actions workflow in `ai-operations` authenticates via WIF, runs real tests, and publishes a real commit's provenance to Orion - which in turn registers a real, live evaluation target in `agent-eval` (a new, minimal write endpoint added there, `POST /agents/{id}/versions`, closing a gap found live: agent-eval's `config.base_url` mechanism for calling a real agent endpoint already existed and was already proven, but was never reachable over HTTP).
- **`requires_ci_provenance` is now `true` on the real `incident-investigator` Agent** - live-verified: a real human JWT is rejected (`403`) attempting manual creation; the real CI pipeline still publishes successfully.

Live-verified in full, repeatedly, against the real deployed systems (not a rehearsal): a real `ai-operations` commit, through a real GitHub Actions run, real WIF-minted OIDC tokens (no stored credentials anywhere), a real Orion publish with real idempotency, a real `agent-eval` registration, and the real lockout/unlock boundary on both sides of the flag flip.

## Phase 9 - Shared Agent & Skill Developer Experience *(complete, see `docs/phase-notes/phase-9.md`)*

Requested directly by the user after reviewing Phase 8's deployed UI: the backend now had real provenance and a real registry data model, but the product still looked and behaved like a governance/evaluation dashboard - a developer couldn't answer "who else uses this skill," "is there a newer version," or "what happens if I adopt it" from any page. Architecture-reviewed first (report before coding, per the brief), then implemented:

- **SkillVersion review, as a separate model from `PromotionRequest`** (ADR-0025): `SkillVersionLifecycle` (`published`/`recommended`/`deprecated`) and `SkillReviewRequest`/`SkillReviewDecision`, structurally parallel to the Agent side (no-self-approval DB trigger, one-recommended-per-parent invariant, immutable decisions) but deliberately not built on `PromotionRequest` itself - that table's hard FKs into the AgentVersion evaluation-gate pipeline don't apply to a `SkillVersion`, which has no automated evaluator at all.
- **Dependency/impact analysis**: `GET /v1/skills/{id}/impact` - `current_impact` (each Agent's most recent version, if still on an older SkillVersion) separated from `historical_consumers` (the full unfiltered record) - built entirely from existing tables, no new domain modeling needed.
- **One-click evaluation**: `external_agent_version_id` moved from a required, user-typed field to an optional one the backend resolves itself from the version's own CI-publish provenance - closing a real UX bug found live (a raw agent-eval UUID field with no way for a user to know the value).
- **Provenance and CI-managed publishing made visible**: a "Published from GitHub" panel on AgentVersion detail, a "Version publishing" panel on Agent detail explaining CI-managed vs. manual/representative agents.
- **Skills catalog and detail pages reworked**: search/filter, recommended-version and consumer-count badges, real agent names on the consumer list (replacing a raw, meaningless version-label badge), inline review actions, and a prominent current-impact panel.
- **Overview reworked** around the registry/reuse story: a "Developer ecosystem" stat row and an "Updates" feed, alongside (not replacing) the existing governance signals.
- **The shared-skill story made real, not fabricated**: `ai-operations`' real CI pipeline was publishing an empty skill list despite genuinely having the matching LangGraph nodes - fixed at the source (one real commit, one real GitHub Actions run, one real new `AgentVersion` with real skill pins). `release-risk-agent` (representative data) went from zero AgentVersions to a real one pinning `deployment-analysis@1.3`, and that skill was made `recommended` through a real, decided `SkillReviewRequest` - not a script silently setting a lifecycle column.

Migration `0019` applied to production; backend/frontend redeployed; live-verified against the real deployed database and a real GitHub Actions run, not a rehearsal.
