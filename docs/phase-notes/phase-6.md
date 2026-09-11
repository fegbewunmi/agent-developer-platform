# Phase 6 Notes: Production-Style Deployment, Operational Verification, Observability, and Final Project Closure

Status: complete. Every service in `docs/gcp-architecture.md` is real and deployed in `ai-ops-center-eb26`; every mechanism Phase 3-5 built but could only partially verify locally (Cloud Tasks delivery, Pub/Sub outbox durability, real production JWT auth, real MCP health checking) is now closed end-to-end against the actual deployed system. No new product features were added beyond the smallest real fixes a genuine deployment/operational issue required (see "Bugs found" - the MCP `connection_ref` update endpoint and the Secret Manager `DATABASE_URL` fix are the two cases where this happened).

## Deployed topology

| Service | URL / identifier |
|---|---|
| `agent-platform-api` (backend, FastAPI) | `https://agent-platform-api-159087954477.us-central1.run.app` |
| `agent-platform-web` (frontend, Next.js standalone) | `https://agent-platform-web-159087954477.us-central1.run.app` |
| `agent-eval-api` (external, Phase 3) | `https://agent-eval-api-159087954477.us-central1.run.app` |
| `ai-ops-api` (external, pre-existing) | `https://ai-ops-api-159087954477.us-central1.run.app` |
| Cloud SQL database | `agent_dev_platform` on the shared `ai-ops-db` instance (`ai-ops-center-eb26:us-central1:ai-ops-db`) |
| Service accounts | `agent-platform-api`, `agent-platform-web`, `agent-platform-tasks` (all new this phase, least-privilege, one per role) |
| Images | `us-central1-docker.pkg.dev/ai-ops-center-eb26/ai-ops-images/agent-platform-{api,web}:v1-v3`, built via Cloud Build (no local Docker daemon needed) |

Both Cloud Run services are deployed `--allow-unauthenticated`. This is a deliberate deviation from a plan to use Cloud Run ingress IAM to protect the API's internal task-receiver endpoints - see ADR-0021 for why that plan was architecturally impossible once discovered live (ingress IAM is enforced per-service, not per-path, and the same service must accept both public user JWTs and Cloud Tasks/Scheduler pushes on the same `Authorization` header). Internal endpoints are protected instead by real application-level OIDC verification.

**Difference from the original architecture** (see updated `docs/gcp-architecture.md` and the Phase 6 addendum to ADR-0012): the planned topology assumed `ai-operations`' Cloud SQL connection used a VPC connector. Direct inspection of the live `ai-ops-api` service found it uses Cloud Run's built-in `--add-cloudsql-instances` Unix-socket connector instead, with no VPC network at all - this platform was deployed the same way. Everything else matched the plan.

## Authentication

Real production auth path: Google Identity Platform, Email/Password provider (required a one-time `identityPlatform:initializeAuth` project init call before its config was modifiable - not anticipated, a genuine first-use step). Four real user accounts were created via the Admin REST API with the exact seeded Orion Commerce emails (`maya.chen@...`, `jordan.brooks@...`, `priya.shah@...`, `alex.rivera@...`).

The single strongest result of this phase's auth work: **the Phase 1 `RemoteJWKSProvider` / `verify_id_token` code required zero changes** to verify real Identity-Platform-issued tokens. A real token's `iss` (`https://securetoken.google.com/ai-ops-center-eb26`) and `aud` (`ai-ops-center-eb26`) were confirmed against the unmodified Phase 1 verification path before ever deploying anything - "do not weaken the Phase 1 JWT validation" was satisfied by construction, not by inspection.

`dev-login` remains available locally (`GET /v1/dev-login/users` returns real seeded users) and is correctly unavailable in the deployed environment (`404`, not an error) - `frontend/app/login/page.tsx`'s `getDevLoginState()` distinguishes "network unreachable" from "route genuinely doesn't exist here" from "dev users exist," and renders `PasswordLoginForm` (real Identity Platform sign-in, `app/api/auth/login-password/route.ts`) whenever dev-login isn't available. Live-verified via the actual browser: signing in as Alex Rivera through the real password form produced a real session, correct role (`Admin`) badge, and correctly rendered real dashboard data.

No new automated frontend tests were added for the login route/form specifically - consistent with this codebase's existing convention (established Phase 5) of not unit-testing Next.js Route Handlers or Server Actions that need a real server runtime context to execute meaningfully; these were verified live instead, the same bar Phase 5 applied to its own Server Actions.

## Service-to-service authentication (this platform → agent-eval-api)

Real, deployed: `agent-platform-api`'s own attached service account, via Application Default Credentials resolved through the Cloud Run metadata server - no impersonation, no key file. Required one IAM grant: `roles/run.invoker` on `agent-eval-api` for `agent-platform-api@ai-ops-center-eb26.iam.gserviceaccount.com`. `HttpAgentEvalClient`'s existing branch (impersonation only when explicitly configured, ADC otherwise) needed no code change - it was already written to support exactly this path.

## Cloud Tasks - the gap Phase 3 left, now closed

Phase 3 proved task *creation*. This phase proved creation → authenticated delivery → receiver processing → gate computation → lifecycle update, end to end, against a real evaluation:

- A real `EvaluationRunReference` was created via the deployed API; the request automatically dispatched a real Cloud Task (`JOB_DISPATCH_MODE=cloud_tasks`).
- Confirmed via the API and via Cloud Logging that the real Cloud Tasks queue delivered the push, the receiver (`POST /internal/tasks/evaluations/{id}`) processed it, called the real deployed `agent-eval-api`, and the reference reached `status: completed` with real gate results - all within ~1 second of the original request, no manual intervention.
- **Duplicate delivery**: the same reference was replayed twice, manually, with a real OIDC token minted for the `agent-platform-tasks` service account. Both replays returned `204` without re-processing; Cloud Logging confirmed the atomic-claim skip path fired both times (`"evaluation job already claimed or terminal - skipping duplicate delivery"`) - genuine idempotency proof, not just unit-test coverage of the same logic.
- **Failed-task behavior**: an evaluation targeting a nonexistent `external_agent_version_id` was submitted. The real `agent-eval-api` genuinely rejected it (`400`); the worker correctly recorded `status: failed` with the real upstream error message, and - critically - the push endpoint still returned `204`, so Cloud Tasks does **not** retry a legitimate application-level evaluation failure forever. Confirmed via Cloud Logging (`"evaluation job failed"` warning, immediately followed by a `204` in the HTTP request log).
- **Retry configuration**: the `evaluation-jobs` queue's real retry policy (`maxAttempts: 100`, exponential backoff up to 3600s) is Cloud Tasks' own default - left unchanged, matching "do not overbuild." A live transport-level 5xx retry was not deliberately induced against the shared Cloud Run service (would have required artificially breaking a real request path); the exception-path code that returns 500 on unhandled persistence failure is covered by `tests/test_evaluation_worker.py` instead.
- Cloud Tasks' receiver authentication is real application-level OIDC verification (`app/auth/cloud_tasks.py`), not Cloud Run ingress IAM - see ADR-0021 for the full reasoning behind that deviation from the original plan.

**A real client-side debugging detour worth recording**: the first manual duplicate-delivery attempt, using default `curl` (HTTP/2), returned a Google-front-end-branded `400` HTML error page - not from this application at all. Retrying with `curl --http1.1` and then with Python's `httpx` both worked cleanly and reached the app. This was a curl/HTTP2-negotiation quirk against Cloud Run's front end when carrying an impersonated-service-account bearer token, not an application bug - moving to `httpx` for all subsequent manual verification calls avoided it entirely.

## Pub/Sub outbox - durability closed

Phase 4/5 only ever attempted publish once, immediately after commit. This phase added the retry half explicitly required by the brief: `sweep_unpublished_outbox_events` (`app/services/event_publisher.py`) re-attempts `publish()` for every `OutboxEvent` row with `published_at IS NULL`, exposed as `POST /internal/tasks/outbox/sweep`, protected by the same application-level OIDC verification as the Cloud Tasks receiver. Deliberately **not** a generic retry platform: no backoff schedule, no max-attempt tracking, no dead-letter table - just "try again," matching the actual failure mode in play (a transient Pub/Sub hiccup) per the brief's "do not overbuild" instruction.

A Cloud Scheduler job, `agent-platform-outbox-sweep`, calls this endpoint every 5 minutes, OIDC-authenticated as `agent-platform-tasks`. **Live-verified as real delivery, not just a successful `publish()` return**: a fresh promotion was approved, and its `OutboxEvent` was pulled from a real (temporary) Pub/Sub subscription (`phase6-verify-sub`, created and deleted this phase) - the decoded message body matched the real promotion exactly (`entity_id`, `promotion_request_id`, `previous_production_agent_version_id`). The Scheduler job itself was confirmed firing via real `200` responses in Cloud Run's request logs, both from manual `jobs run` triggers and its natural 5-minute cadence.

No real Pub/Sub *subscriber service* exists yet - the same named, open gap as Phase 4/5 documented. The outbox now durably retries publish; nothing downstream currently consumes what's published.

## Database

All 16 Alembic migrations were applied to a brand-new Cloud SQL database (`agent_dev_platform`) and the resulting grant structure was diffed against local dev's - identical (`information_schema.role_table_grants`, `\dp`). Runtime role is `agent_platform_app`, a dedicated least-privilege role (not `postgres`) - migrations themselves run as `postgres`, matching this project's existing shared-instance convention (ADR-0017). Admin/migration access uses the Cloud SQL Auth Proxy over a local TCP tunnel; the deployed app uses Cloud Run's built-in `--add-cloudsql-instances` Unix-socket connector.

**No-self-approval was live-verified under the deployed runtime role and real Identity-Platform-authenticated user, not just via the existing automated suite**: a real reviewer (Jordan Brooks) requested a real promotion, then attempted to approve his own request through the deployed API - correctly rejected (`403 not authorized to decide this promotion request`). Other invariants (`AgentVersion`/`SkillVersion`/`EvaluationPolicy` immutability, one-production-version-per-Agent, `PromotionDecision` immutability, `AuditEvent` insert-only) were exercised structurally by every real create/promote/approve/reject call made this phase against the deployed database and passed without incident; concurrent-production-promotion enforcement specifically continues to rely on the existing automated test suite (`tests/test_promotions.py`) rather than a live-induced race against the shared deployed database, a reasonable judgment call given the enforcement mechanism itself (a DB-level partial unique index, applied identically by the same migration this phase proved reproducible) does not change based on which environment runs it.

## MCP integration - a real gap found and fixed

The registered `incident-operations` MCP server's `connection_ref` was still `http://127.0.0.1:8080` - a local-dev placeholder, unreachable from Cloud Run. This is exactly the "real deployment issue requiring the smallest possible change" the brief anticipated: there was no update path for `connection_ref` at all (only create-time registration), so a minimal, admin-only `PATCH /v1/mcp-servers/{id}/connection` endpoint was added (`app/services/mcp.py::update_mcp_server_connection`, same authorization/audit pattern as registration; 1 new test file addition, `test_update_connection_ref_admin_only`).

Repointed to `ai-ops-api`'s real deployed URL (its `/health` endpoint, already used this way in local dev where `ai-ops-api` also runs on `127.0.0.1:8080`) and triggered a real health check: `health_status: "healthy"`, live-verified through the actual browser (`/mcp` page). Registry data, tool classification (`read`/`write`), and approval metadata (`requires_approval`) were all already real from Phase 2 and required no change. Authorization was confirmed both ways: Admin (Alex Rivera) succeeded; a Builder (Maya Chen) was correctly rejected (`403 only Admins may update MCP server registration`).

**Known gap, explicitly not closed this phase**: ADR-0011 originally anticipated Cloud Scheduler driving periodic MCP health checks. That was not built - `check_server_health` remains callable on demand (via the UI button or API) but nothing calls it on a schedule. Left as a named limitation rather than adding a second Scheduler job speculatively; the brief's Cloud Tasks/Pub/Sub durability requirements were the ones with an explicit "must close this gap" instruction, MCP health-check scheduling was not.

## Observability

Structured JSON logging (`app/observability.py`, Cloud Logging's stdout-JSON convention, no separate client library needed) replaced plain-text logging in the deployed environment. Every async hop is correlated by `evaluation_run_reference_id`, `agent_version_id`, `promotion_request_id`, Cloud Task name/retry-count, and external `agent-eval` run ID - real log lines added to `app/api/tasks.py`, `app/services/evaluation_worker.py`, `app/services/job_dispatch.py`, `app/services/promotions.py`.

Seven log-based metrics, each mapped to a real, already-emitted log line (no invented signal, per "do not add dashboards containing meaningless vanity metrics"):

| Metric | Signal |
|---|---|
| `agent_platform_evaluation_success` / `agent_platform_evaluation_failure` | Evaluation job outcomes |
| `agent_platform_agent_eval_latency_ms` | Distribution metric, real wall-clock latency of the `agent-eval` `trigger_run` call (added this phase; live-verified at 186.6ms for one real call) |
| `agent_platform_promotion_rejected` | Reviewer rejections |
| `agent_platform_promotion_stale_blocked` | Approvals blocked by stale evidence |
| `agent_platform_outbox_publish_failure` | Rows still unpublished after a sweep retry |
| `agent_platform_cloud_task_retry` | Cloud Tasks pushes with a nonzero retry count |

**Cloud Trace: deliberately not added.** The correlation-ID-based structured logging above already answers the actual debugging need for this system's real flows, which are async (Cloud Tasks, Pub/Sub) rather than synchronous request chains Trace is built for. Adding it would mean instrumenting `agent-eval-api` and `ai-ops-api` - both independently owned services outside this project - for a marginal gain over what correlation IDs already provide. A reasoned decision not to build it, not an oversight.

## Performance

The brief flagged a previously-observed ~10-second dashboard load and asked for measurement before any change. Measured this phase, on the real deployed environment with real candidate/pending-request data present (not an empty database):

- `GET /v1/dashboard/summary` (backend, warm): 0.45-0.83s across 3 real calls.
- Full `/overview` page load (frontend SSR, real browser measurement via the Navigation Timing API): ~650ms warm, ~1.7s on a cold Cloud Run instance.

**No further optimization was made.** The ~10s figure does not reproduce; it was already resolved by a fix made during Phase 5 (`app/services/dashboard.py`'s concurrent, per-check `asyncio.gather`'d freshness checks, replacing a sequential one-call-at-a-time loop - see that module's docstring and Phase 5 notes' "Bugs discovered" #1). This phase's job was to measure the deployed reality and decide, not to assume more work was needed - measuring first showed none was.

## Final automated test count

- **Backend**: 188 passing (187 carried in from Phase 5 + 1 new test function covering the MCP connection-update endpoint, admin-only authorization, and health-status reset behavior).
- **Frontend**: 55 passing, unchanged from Phase 5 (no new unit-testable logic was added to components; the new login route/form were verified live instead, per the existing Route-Handler testing convention).

## Bugs discovered

1. **Curl/HTTP2 vs. Cloud Run's front end**: manually replaying a Cloud Tasks push with default `curl` (HTTP/2) against a URL carrying an impersonated-service-account bearer token returned a Google-front-end `400`, not an application response. Not an app bug - `curl --http1.1` and Python `httpx` both worked cleanly.
2. **`gcloud auth print-identity-token --impersonate-service-account` omits the `email` claim by default** - `app/auth/cloud_tasks.py`'s identity check (`claims.get("email")`) correctly rejected a token minted without `--include-email`, which looked like an application bug until the token was decoded and inspected directly.
3. **MCP `connection_ref` was a local-dev placeholder with no update path** - see "MCP integration" above. Fixed with a minimal, admin-only `PATCH` endpoint.
4. **`DATABASE_URL` was deployed as a plain, inlined `--set-env-vars` value** despite Secret Manager secrets (`agent-platform-db-password`, `agent-platform-db-admin-password`) already existing for this purpose - an inconsistency between "credentials exist in Secret Manager" and "the running service actually reads them from there." Fixed by consolidating the full connection string into a new secret (`agent-platform-database-url`) and redeploying with `--set-secrets` in place of the inlined env var; verified the service still connects correctly afterward.
5. **Cloud Scheduler's OIDC push requires the *Cloud Scheduler service agent* to hold `roles/iam.serviceAccountTokenCreator` on the target service account, not just the human who created the job.** The scheduler job was created successfully and appeared healthy (`state: ENABLED`), but silently never fired - `jobs run` returned success with no error, yet no request ever reached the deployed API. Diagnosed by manually minting a token for the same target identity and confirming the *endpoint* was correct, which isolated the problem to Scheduler's own delivery mechanism; fixed by granting `service-<project-number>@gcp-sa-cloudscheduler.iam.gserviceaccount.com` the `serviceAccountTokenCreator` role on `agent-platform-tasks`, after which real `200` deliveries appeared immediately.

## ADR changes

- New: [ADR-0021](../adrs/0021-cloud-tasks-application-level-push-auth.md) - Cloud Tasks/Scheduler push authentication verified in application code, not Cloud Run ingress IAM (the architecturally-necessary deviation from the original plan, discovered live).
- Updated with Phase 6 addenda: [ADR-0020](../adrs/0020-promotion-lifecycle-event-outbox.md) (the sweep/Scheduler mechanism it anticipated is now real), [ADR-0012](../adrs/0012-gcp-deployment-topology.md) (the VPC-connector premise was wrong; documents what was actually deployed).

## Known limitations (honest, as of end of Phase 6)

- No real Pub/Sub subscriber service exists downstream of `agent-platform-events` - the topic is real, delivery is durable and verified, but nothing consumes it yet.
- MCP health checks are not on a schedule - manual/on-demand only, despite ADR-0011 originally anticipating Cloud Scheduler for this.
- Cloud Trace was not implemented (reasoned decision, see "Observability").
- Cloud Run min-instances is 0 for both services (not changed) - a cold start (~1-2s extra) is possible after idle periods. Acceptable for this workload's actual traffic shape; not treated as a defect.
- Concurrent-production-promotion enforcement was not live-race-tested against the deployed database specifically this phase (relies on the existing automated suite plus the reproduced-migration guarantee that the same DB constraint is in place).

No outstanding temporary operator IAM grants remain from this phase's live verification: the `roles/iam.serviceAccountTokenCreator` binding on `agent-platform-tasks` used to mint manual verification tokens was revoked from the operator's own account once verification was complete; only the legitimate Cloud Scheduler service agent binding remains.

## Live end-to-end verification summary

All of the following were performed against the real deployed frontend, backend, database, `agent-eval-api`, Pub/Sub, and Cloud Tasks - not mocks, not a local dev server:

- **Successful path**: signed in via real Identity Platform password auth (browser) as Alex Rivera (Admin); inspected the real `incident-investigator` agent, its version history, and the `4.3.4` AgentVersion's full reproducibility view (manifest, gates, freshness); a real evaluation was requested, delivered via Cloud Tasks, executed against the real deployed `agent-eval-api`, and completed with real per-gate results; a real promotion request was submitted by Maya Chen and approved by a different reviewer (Jordan Brooks), producing a real production transition with the correct prior-version retirement, visible immediately in the UI and the audit trail.
- **Stale path**: an existing pending promotion request (`4.3.2`) shows real "eligible when requested" (Eligible) vs. "eligible now" (Stale, with the real before/after capability-grant-hash diff) side by side - the historical evaluation is never retroactively marked failed.
- **Rollback**: production moved `4.3.0 → 4.3.1 → 4.3.0 → 4.3.4` across this and prior phases' real promotion decisions, each transition visible in the agent's promotion history.
- **Authorization denials**: a Builder was rejected updating MCP `connection_ref` (`403`); a reviewer was rejected approving his own promotion request (`403`).
- **Failure verification**: duplicate Cloud Tasks delivery (idempotent no-op, proven via logs); a genuinely failed evaluation (invalid target, real `400` from `agent-eval-api`, correctly recorded as `failed` without triggering a Cloud Tasks retry); Pub/Sub outbox sweep against an already-fully-published backlog (`{"attempted":0,...}`) and against a real Cloud Scheduler-triggered delivery.

See the phase transcript for exact request/response bodies, timestamps, and Cloud Logging query results underlying each claim above.
