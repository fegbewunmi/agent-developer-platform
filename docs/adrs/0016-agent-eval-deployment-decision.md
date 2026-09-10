# 0016. Deploy Agent Evaluation Platform to Cloud Run now, as an independently owned service

Status: Accepted

## Context

ADR-0005 (Phase 0) deferred `agent-eval`'s deployment, reasoning that a real end-to-end Phase 3 proof was achievable locally without it. Phase 3 reopened this question because real `gcloud` credentials existed on the development machine (project `ai-ops-center-eb26`) - a fact absent at Phase 0's writing - and the user explicitly directed deployment: "Deploy agent-eval to Cloud Run now and use the deployed service for the Phase 3 integration... Keep Agent Eval as an independently owned service. Do not merge its deployment lifecycle into the Agent Developer Platform."

## Decision

Deployed `agent-eval` to Cloud Run as `agent-eval-api` (`us-central1`), with the smallest set of changes that made cloud-hosted execution possible:

- **One new file added to `agent-eval`'s own repo**: `backend/Dockerfile`, mirroring `ai-operations/backend/Dockerfile`'s proven pattern exactly (`python:3.12-slim` matching `agent-eval`'s own `requires-python`, `libpq-dev`/`gcc` for `psycopg`, `uvicorn --host 0.0.0.0 --port 8080`). No other file in `agent-eval` was touched - its application code, API contract, and evaluator/dataset logic are unchanged.
- **Database**: reused the existing `ai-ops-db` Cloud SQL instance (already running, already paid for) rather than provisioning a new instance - see [ADR-0017](0017-shared-cloud-sql-instance-isolated-database.md) for why this preserves the service boundary despite sharing physical infrastructure.
- **Auth**: Cloud Run's own IAM (`--no-allow-unauthenticated` + `roles/run.invoker` granted to a dedicated `agent-dev-platform-caller` service account) - zero application-code changes to `agent-eval` itself. See `docs/gcp-architecture.md`'s service-to-service auth section.
- **Ownership**: `agent-eval-api` is deployed, versioned, and redeployed independently of this platform - this repo has no deploy scripts or CI wiring for it, and never will. The relationship is purely: this platform's `HttpAgentEvalClient` calls `agent-eval-api`'s existing, unmodified API contract over the network, exactly as `docs/control-plane-boundaries.md` already requires.

## Alternatives considered

- **Continue deferring deployment** (ADR-0005's original position). Superseded by explicit user direction once real GCP credentials made deployment practical without material new cost (see `docs/gcp-architecture.md`'s cost accounting) - the local-only proof from Phase 0 was a reasonable position given the facts available then, not a mistake being corrected.
- **Provision a new, separate Cloud SQL instance for `agent-eval`.** Rejected as unnecessary cost for a service whose data volume is small (`agent_eval` database on the shared instance is a few dozen rows) - see ADR-0017.
- **Fold `agent-eval`'s deployment into this platform's own future Cloud Run rollout** (Phase 6). Rejected - explicitly contrary to the user's instruction to keep the deployment lifecycle independent, and contrary to `docs/control-plane-boundaries.md`'s foundational separation between the control plane and the evaluation plane.

## Consequences

`agent-eval-api` is now a real, independently deployed, IAM-authenticated Cloud Run service - live-verified for health, authenticated-request behavior, Cloud SQL connectivity, and two real evaluation runs against real target agents (`docs/phase-notes/phase-3.md`). This platform's Phase 3 integration was wired directly to it and proven with two full real workflows (a passing evaluation reaching `candidate`, and a capability-grant revocation making that same version's evidence stale) - not a local stand-in. Future changes to `agent-eval`'s deployment (redeploys, scaling, region changes) are entirely that repo's own concern; this platform only depends on its public API contract remaining stable, per the existing integration contract in `docs/evaluation-and-promotion.md`.
