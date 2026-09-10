# 0005. Agent Evaluation Platform as external source of truth, invoked asynchronously

Status: Accepted

## Context

Inspection of `agent-eval/backend/app/api/runs.py` confirmed `POST /runs` executes synchronously, in-request, until the full run completes - an explicit MVP choice documented in `agent-eval`'s own ADR-0005 (same number, different repo - coincidental). `ai-operations`' eval runner comments record real per-case latency of 60–75 seconds; a dataset-sized run can take many minutes. Calling this endpoint directly from this platform's API request handler would block an API worker and a browser request for that entire duration - unacceptable for a control-plane API expected to be responsive.

`agent-eval` also has no CRUD API to register `Agent`/`AgentVersion` rows on its side (seeded only via script) - meaning this platform must resolve/create `agent-eval`'s own `AgentVersion` identity through whatever mechanism exists (likely `GET /agents` lookup by name/label, or a coordinated addition to `agent-eval` itself, tracked as an open question) rather than assuming a clean create-on-demand flow.

## Decision

Never call `agent-eval`'s `POST /runs` synchronously from this platform's API layer. Evaluation requests create a local `EvaluationRunReference(status='requested')` and enqueue a Cloud Tasks job; a background worker makes the (still-blocking) call and writes results back asynchronously. `agent-eval` remains the only place evaluators, datasets, and regression logic execute - this platform reads its already-computed `dimension_stats`/`regressions`, and applies its own policy/threshold logic on top (see ADR-0006), never recomputing scores itself.

## Alternatives considered

- **Ask `agent-eval` to add an async job/polling API first, and block this platform's Phase 3 on that.** Rejected as a hard dependency - reasonable as a long-term ask (tracked in `docs/open-questions.md`), but this platform can work around the current synchronous API today via Cloud Tasks without requiring a coordinated change to a system outside this repo's control.
- **Poll `agent-eval` from the frontend directly, skipping the backend.** Rejected - would leak an external system's API shape into the frontend and bypass this platform's own policy/gate computation entirely.

## Consequences

Evaluation results arrive with real latency (minutes, not milliseconds) even after the API call returns instantly - the UI must show a pending state, not assume synchronous completion. If `agent-eval` never gains an async API, this Cloud Tasks wrapper is a permanent, not transitional, piece of architecture.

**Resolved in Phase 3, per [ADR-0016](0016-agent-eval-deployment-decision.md):** the two prerequisites named when this paragraph was originally written (`agent-eval` deployed somewhere reachable; an authenticated channel between the two services) are both now real. `agent-eval` is deployed to Cloud Run as `agent-eval-api`, IAM-authenticated (`--no-allow-unauthenticated` + a dedicated `agent-dev-platform-caller` service account with `roles/run.invoker`), and this platform's `HttpAgentEvalClient` was live-verified calling it with real Google-signed ID tokens - see `docs/phase-notes/phase-3.md` for the full passing-flow and stale/blocked-flow verification, both run against the real deployed service, not a local stand-in.

The one part of this ADR's target architecture **not** yet real: the Cloud Tasks dispatch mechanism itself still runs as `LocalSyncDispatcher` (in-process, non-durable - see `app/services/job_dispatch.py`) in every automated test and every live demo this phase performed, because the real `CloudTasksDispatcher`'s delivery target is this platform's *own* API, which isn't deployed to Cloud Run yet (Phase 6). `CloudTasksDispatcher` is fully implemented and was proven to genuinely create and enqueue a real Cloud Tasks task against a real queue (`evaluation-jobs`, `us-central1`) - confirmed independently via `gcloud tasks list` showing real dispatch attempts - but delivery-to-a-live-receiver remains unexercised until this platform itself is deployed. This is a real, named, and current gap, not a historical one this ADR has fully closed.
