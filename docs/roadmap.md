# Roadmap

The brief's suggested phase structure held up against the architecture — no restructuring was needed, only sequencing details filled in from what Phase 0 research found (e.g. auth has to land in Phase 1, not later, since nothing can be attributed to a real user without it).

Every implementation phase below ends with: automated tests, real/live verification where applicable, bugs discovered, architecture/ADR changes if any, phase notes (`docs/phase-notes/phase-N.md`), README/docs updates, and a commit.

## Phase 0 — Architecture and documentation *(this phase)*

Inspect `ai-operations`, `agent-eval`, `doc-qa`; design domain model, service boundaries, lifecycle, GCP architecture, ADRs, diagrams. No application code. **Stop and review before Phase 1.**

## Phase 1 — Core domain, persistence, seed organization

- Postgres schema + Alembic migrations for every entity in `domain-model.md`.
- `User`/`Team` + Identity Platform JWT verification (auth has to exist before any "who did this" field means anything).
- `scripts/seed_orion_commerce.py` — the four teams, four users, three agents (one real integration reference, two representative) from `product-overview.md`.
- DB-level enforcement: manifest immutability, `UNIQUE (agent_id) WHERE stage='production'`.

## Phase 2 — Agent / version / skill / MCP registries

- CRUD for `Agent`, `AgentVersion` (manifest validation against JSON Schema, per `agent-manifest.md`), `Skill`, `SkillVersion`.
- `MCPServer`/`MCPTool` registry, seeded from the real Incident Operations MCP tools.
- `AgentCapabilityGrant` create/revoke, with the read-vs-write authority split from `auth-and-approval-model.md`.
- Cloud Scheduler health-check job for `MCPServer.health_status`.

## Phase 3 — Agent Evaluation Platform integration + policy/gates

- `EvaluationPolicy` CRUD (Admin-only).
- Cloud Tasks worker wrapping `agent-eval`'s synchronous `POST /runs`.
- `EvaluationRunReference` + `EvaluationGateResult` computation, freshness re-checks.
- First real end-to-end call against the live `agent-eval` service for the `incident-investigator` agent.

## Phase 4 — Promotion lifecycle, approvals, audit trail

- Full state machine from `evaluation-and-promotion.md`, `PromotionRequest`/`PromotionDecision`, self-approval rejection, concurrent-promotion handling.
- Transactional `AuditEvent` writes + Pub/Sub outbox publication.
- Rollback path (`retired → production` via a normal `PromotionRequest`).

## Phase 5 — Frontend / product workflows

- Dashboard, agent catalog, agent/version detail, manifest viewer, skills registry, MCP registry, evaluation status + regression detail, promotion request/review, audit timeline — the full surface list from the brief.
- Dashboard seed content: production agents, candidate versions, blocked promotions, stale evaluations, unhealthy MCP integrations, recent activity.

## Phase 6 — Real end-to-end verification + deployment/observability polish

- Full successful lifecycle demonstrated against the real `incident-investigator` agent and real `agent-eval` run: create version → attach real skill versions + MCP capabilities → evaluate → gates pass → promote → audit trail reconstructs why.
- Full blocked lifecycle demonstrated: a regression or threshold failure blocks promotion with a UI that explains exactly which criteria failed.
- Cloud Run deployment, Cloud Trace spans across the async evaluation flow, dashboards in Cloud Monitoring.

See [`open-questions.md`](open-questions.md) for what could reshape this sequence (e.g. if `agent-eval` gains an async run API upstream, Phase 3's Cloud Tasks wrapper simplifies).
