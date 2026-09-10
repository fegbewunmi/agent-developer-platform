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
- Real HTTP health checks against the live `ai-operations` backend, triggered on demand (a periodic Cloud Scheduler-triggered version of the same call remains the Phase 6 deployment target, not built this phase - see `docs/mcp-governance.md`).
- **Known gap carried forward to Phase 3:** `agent-manifest.md` says `evaluation.policy` "must resolve to an existing `EvaluationPolicy`," but that registry doesn't exist until Phase 3. Phase 2's manifest validation (`app/services/manifest.py`) only checks the key is present with a non-empty string value - real resolution is Phase 3's job, once `EvaluationPolicy` CRUD exists.

## Phase 3 - Agent Evaluation Platform integration + policy/gates

**Explicit prerequisite, outside this repo's unilateral control:** `agent-eval` must be deployed somewhere reachable from this platform's environment (Cloud Run is the natural target, matching this platform's own topology), and some form of service-to-service authentication must exist between the two - today `agent-eval` has neither (`agent-eval/infra/` is a bare local Postgres `docker-compose.yml`, and neither system authenticates any caller). See [`evaluation-and-promotion.md`](evaluation-and-promotion.md#prerequisite-agent-eval-must-actually-be-reachable-from-this-platforms-cloud-environment). If these aren't in place when Phase 3 starts, Phase 3 proceeds against a local/dev `agent-eval` instance over an unauthenticated connection to prove the integration shape, and the phase report must say so explicitly rather than imply a production-safe integration was demonstrated.

- `EvaluationPolicy` CRUD (Admin-only).
- Once `EvaluationPolicy` exists, tighten `app/services/manifest.py` to actually resolve `evaluation.policy` against it, closing the Phase 2 gap noted above.
- Cloud Tasks worker wrapping `agent-eval`'s synchronous `POST /runs`.
- `EvaluationRunReference` + `EvaluationGateResult` computation, freshness re-checks.
- `EvaluationRunReference.capability_grant_snapshot_hash`, per [ADR-0014](adrs/0014-capability-grant-reproducibility.md) - a hash over the active `AgentCapabilityGrant` set at evaluation-request time, mirroring the existing `dataset_snapshot_hash` pattern.
- First end-to-end call against `agent-eval` for the `incident-investigator` agent - real cloud-to-cloud traffic if the prerequisite above is met by then, otherwise local/dev traffic with that limitation stated plainly in the phase report.

## Phase 4 - Promotion lifecycle, approvals, audit trail

- Full state machine from `evaluation-and-promotion.md`, `PromotionRequest`/`PromotionDecision`, self-approval rejection, concurrent-promotion handling.
- Transactional `AuditEvent` writes + Pub/Sub outbox publication.
- Rollback path (`retired → production` via a normal `PromotionRequest`).

## Phase 5 - Frontend / product workflows

- Dashboard, agent catalog, agent/version detail, manifest viewer, skills registry, MCP registry, evaluation status + regression detail, promotion request/review, audit timeline - the full surface list from the brief.
- Dashboard seed content: production agents, candidate versions, blocked promotions, stale evaluations, unhealthy MCP integrations, recent activity.

## Phase 6 - Real end-to-end verification + deployment/observability polish

- Full successful lifecycle demonstrated against the real `incident-investigator` agent and real `agent-eval` run: create version → attach real skill versions + MCP capabilities → evaluate → gates pass → promote → audit trail reconstructs why.
- Full blocked lifecycle demonstrated: a regression or threshold failure blocks promotion with a UI that explains exactly which criteria failed.
- Cloud Run deployment, Cloud Trace spans across the async evaluation flow, dashboards in Cloud Monitoring.

See [`open-questions.md`](open-questions.md) for what could reshape this sequence (e.g. if `agent-eval` gains an async run API upstream, Phase 3's Cloud Tasks wrapper simplifies).
