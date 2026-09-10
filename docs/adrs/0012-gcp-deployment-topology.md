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
