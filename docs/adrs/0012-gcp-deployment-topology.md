# 0012. GCP deployment topology matches ai-operations' proven pattern

Status: Accepted

## Context

`ai-operations` is not a hypothetical GCP deployment - it's live, on Cloud Run, with Cloud SQL behind a VPC connector, Secret Manager for `DATABASE_URL`, Artifact Registry for images, and Vertex AI access via ADC/service-account IAM rather than API keys (confirmed by inspection of its README/`docs/08-deployment.md` and the live Cloud Run URL). `agent-eval` targets the same general shape (FastAPI + Postgres) but has no actual deployment yet - only a local `docker-compose.yml` for Postgres.

## Decision

This platform's topology (`docs/gcp-architecture.md`) reuses `ai-operations`' proven pattern directly: Cloud Run for both frontend and API, Cloud SQL Postgres behind a VPC connector, Secret Manager for credentials, Cloud Logging/Monitoring/Trace for observability with OpenTelemetry instrumentation matching `ai-operations`' existing approach.

## Alternatives considered

- **Design a novel topology optimized for this platform's specific traffic shape** (e.g. separate read replicas, a caching layer). Rejected as premature - this is a low-QPS internal control-plane tool for a handful of engineering teams; `ai-operations`' pattern is already proven at a comparable or larger scale (it serves an actual investigation workload), and optimizing further now would be solving a scale problem that doesn't exist yet.
- **GKE**, for more deployment flexibility. Explicit non-goal in the brief; Cloud Run's request-based scaling is a strictly better fit for a stateless CRUD+orchestration API with bursty, low-volume traffic.

## Consequences

Orion Commerce engineers moving between this platform and `ai-operations` find a familiar deployment shape and can reuse operational knowledge (how to read Cloud Run logs, how the VPC connector is configured) rather than learning a new pattern per project.

**Phase 6 update - what actually got deployed vs. this ADR's premise**: `ai-operations`' real, live `ai-ops-api` Cloud Run service (inspected directly this phase, not just its docs) does **not** use a VPC connector for its Cloud SQL connection - it uses Cloud Run's built-in `--add-cloudsql-instances` flag (a Unix-domain-socket connection via the Cloud SQL Auth Proxy sidecar Cloud Run manages internally), the same mechanism `agent-platform-api` was deployed with. This ADR's "behind a VPC connector" description of `ai-operations`' pattern was inaccurate; the actual proven, reused pattern is the simpler `--add-cloudsql-instances` connection, which requires no VPC network configuration at all. Everything else in this ADR held: Cloud Run for both frontend (`agent-platform-web`) and API (`agent-platform-api`), Cloud SQL Postgres (a new isolated database, `agent_dev_platform`, inside the same shared `ai-ops-db` instance per ADR-0017), Secret Manager for `DATABASE_URL`, Artifact Registry (`ai-ops-images`, the existing shared repo) for both images, and structured Cloud Logging (`app/observability.py`) in place of OpenTelemetry/Trace instrumentation - see `docs/phase-notes/phase-6.md` for the explicit, reasoned decision not to add Cloud Trace this phase. Three new per-service service accounts (`agent-platform-api`, `agent-platform-web`, `agent-platform-tasks`) were created rather than reusing `ai-operations`' or `agent-eval`'s identities, matching this platform's own least-privilege posture.
