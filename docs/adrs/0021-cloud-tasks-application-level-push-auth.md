# 0021. Cloud Tasks push authentication is verified in application code, not Cloud Run ingress IAM

Status: Accepted

## Context

Phase 3's `app/api/tasks.py` docstring assumed Cloud Run's own per-service ingress IAM (`roles/run.invoker`, granted only to the Cloud Tasks queue's own identity) would protect `/internal/tasks/evaluations/{id}` - the same mechanism ADR-0012's deployment topology otherwise relies on for service-to-service calls. That assumption turned out to be wrong once the backend was actually deployed: `agent-platform-api` is a single Cloud Run service that serves both normal user-facing API traffic (JWT-verified per ADR-0010, in the `Authorization` header) and the Cloud Tasks push target (also delivered with an `Authorization: Bearer <OIDC token>` header). Cloud Run ingress IAM is enforced per-service, not per-path - there is no way to require IAM-level auth on `/internal/tasks/*` while leaving `/v1/*` open to any bearer-JWT-carrying user. Deploying the whole service as IAM-protected would break every real user-facing request; deploying it unauthenticated at the Cloud Run layer leaves the push endpoint with no transport-level protection at all.

## Decision

The backend is deployed `--allow-unauthenticated` (Cloud Run ingress IAM plays no role here), and `/internal/tasks/*` is protected by real application-level verification of the Cloud Tasks push token instead: `app/auth/cloud_tasks.py::verify_cloud_tasks_push` calls `google.oauth2.id_token.verify_oauth2_token` against the token in the `Authorization` header, checks the audience matches the deployed backend's own URL, and checks the token's `email` claim matches the expected Cloud Tasks queue service account (`agent-platform-tasks@...`). This is the same signature-verification mechanism Cloud Run's own ingress IAM would have used internally, just performed explicitly in-process instead of implicitly at the platform layer. The same OIDC-verification approach protects the new `/internal/tasks/outbox/sweep` endpoint (Cloud Scheduler's push, added this phase - see the Phase 6 addendum to ADR-0020).

## Alternatives considered

- **Split into two Cloud Run services** (a public API service and a private, IAM-protected internal task-receiver service). Rejected as overbuilt for this project's scope: it would duplicate the FastAPI app, its dependency wiring, and its deployment pipeline for the sake of avoiding ~40 lines of token verification, and would still need its own database connection and secrets - not a meaningfully smaller attack surface, just a second service to operate.
- **Rely on obscurity of the `/internal/tasks/*` path with no verification.** Rejected outright - the endpoint mutates real state (`process_evaluation_job`, the outbox sweep) and must not be callable by an arbitrary authenticated Orion user's JWT, which would otherwise satisfy no check at all.

## Consequences

The platform now owns real, testable authorization logic for its push endpoints (`tests/test_cloud_tasks_auth.py`) instead of depending entirely on infrastructure configuration a docstring merely asserted. Any new Cloud Tasks or Cloud Scheduler push target added later reuses `CloudTasksAuth` rather than needing its own Cloud Run service. The tradeoff made explicit here: this endpoint's security now depends on this code being correct, not on GCP IAM being correct - a real, accepted shift in trust boundary from Phase 3's (incorrect) assumption.
