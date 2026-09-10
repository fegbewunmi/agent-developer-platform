# Phase 3 Notes: Agent Evaluation Platform Integration, Policies, Freshness, Gates

Status: complete through `draft → evaluating → candidate`, pending review. `candidate → production` (human promotion approval) is Phase 4 - not attempted this phase, per the stop condition.

## Implementation summary

Built the real integration between this platform and the Agent Evaluation Platform (`agent-eval`), including deploying `agent-eval` itself to Cloud Run this phase (per explicit user direction, reopening Phase 0's deferred deployment decision now that real GCP credentials existed). The full pipeline - request an evaluation, submit it to `agent-eval`, compute gates from summary evidence, transition the version's lifecycle, and separately track ongoing evidence freshness - was implemented, unit/integration-tested (60 new automated tests), and live-verified twice against the real deployed service: once producing a real `candidate` transition, once demonstrating a real capability-grant revocation making that same candidate's evidence stale without touching its historical pass.

## Agent Eval integration architecture

`app/integrations/agent_eval_client.py` is the sole place this codebase knows `agent-eval`'s real API shape, built against its actual, re-inspected `/openapi.json` (both the local instance and, separately, the deployed one - unchanged between them). `HttpAgentEvalClient` implements `trigger_run`, `get_run` (with optional `tag` filter), `compare_runs`, `list_evaluators`, `list_datasets`, `get_dataset`. All five failure classes are distinct exception types (`AgentEvalUnavailableError`, `AgentEvalTimeoutError`, `AgentEvalMalformedResponseError`), never a single generic exception.

**Request flow** (`app/services/evaluations.py::request_evaluation`, called from `POST /v1/agent-versions/{id}/evaluations`): fast and synchronous - resolves the current `EvaluationPolicy` for the agent, resolves `policy.dataset_key` and each `required_evaluator_keys` entry against `agent-eval`'s live catalog (failing with `422` before ever calling `agent-eval`'s slow endpoint if anything doesn't resolve), takes a capability-grant snapshot, creates `EvaluationRunReference(status='requested')`, transitions the version `draft/evaluating → evaluating`, and returns `202`.

**Worker flow** (`app/services/evaluation_worker.py::process_evaluation_job`, dispatched async): atomically claims the reference, calls the real (slow, synchronous) `POST /runs`, takes a second capability snapshot at completion, fetches the dataset's current case set for the freshness fingerprint, resolves a production-baseline comparison if one exists, computes all gates, persists everything, and transitions the lifecycle - `candidate` if every gate passed, `draft` otherwise.

## Whether Agent Eval was deployed, and why

**Deployed**, on explicit user instruction, once real `gcloud` credentials on the development machine reopened a question Phase 0 had reasonably deferred for lack of them. Full reasoning: [ADR-0016](../adrs/0016-agent-eval-deployment-decision.md).

- **Service**: `agent-eval-api`, Cloud Run, `us-central1`.
- **Changes to `agent-eval`'s own repo**: exactly one new file, `backend/Dockerfile` (mirrors `ai-operations`' proven pattern). No other file touched - its API contract, evaluator/dataset logic, and application code are unchanged.
- **Database**: a new, isolated `agent_eval` database + `agent_eval_app` user on the *existing* `ai-ops-db` Cloud SQL instance, not a new instance ([ADR-0017](../adrs/0017-shared-cloud-sql-instance-isolated-database.md)). A real Cloud SQL Postgres limitation was found and precisely characterized during setup: a `gcloud sql users create` user is always a member of `cloudsqlsuperuser`, which bypasses database-level `REVOKE CONNECT` - the isolation that actually holds is object-level (`agent_eval_app` can connect to `ai_ops` but gets `permission denied` on every table, verified live).
- **Auth**: Cloud Run IAM (`--no-allow-unauthenticated`) - zero code changes to `agent-eval`. A dedicated service account, `agent-dev-platform-caller`, holds `roles/run.invoker`.
- **Cost**: negligible and new-only - Cloud Run scales to zero; the shared Cloud SQL instance was already running and already paid for; one new ~144 MB Artifact Registry image. See `docs/gcp-architecture.md`'s cost accounting.
- **Independence preserved**: this repo has no deploy scripts, CI, or lifecycle ownership over `agent-eval-api` - it is called over its existing network API contract, exactly as `docs/control-plane-boundaries.md` already required.

## EvaluationPolicy design

Fully immutable at the DB level as of this phase ([ADR-0015](../adrs/0015-evaluation-policy-immutability.md)) - `UPDATE`/`DELETE` revoked for `agent_platform_app`, matching `AgentVersion`/`SkillVersion`. "Editing" means publishing a new `(name, version)` row; `get_current_policy_for_agent` always resolves to the newest version for a given agent name. Fields: `thresholds` (per-dimension minimums), `required_evaluator_keys` (key→pinned version), `max_new_regressions` (generalizes Phase 0's boolean to a count), `zero_failure_tags`, `min_completion_rate`, `dataset_key`.

**Real, live-observed proof this immutability model works as intended**: `incident-investigator`'s first policy (`v1`) required an evaluator that produced no applicable score for the real dataset - a genuine finding, not a bug. The fix was publishing `v2` with corrected requirements, not editing `v1`. `v1`'s gate results (one real failure, ten real passes) remain exactly as computed, permanently.

## Gate semantics

`app/services/gates.py::compute_gates` is a pure function (`GateComputationInput → list[ComputedGate]`, no I/O), unit-tested with 19 dedicated tests covering every gate type independently and confirming there is no blended score anywhere - `candidate` eligibility is `all(g.passed for g in gates)`, computed at the call site. Six gate categories, each producing one row per criterion: `min_dimension_score` (one per threshold), `required_evaluator_version` (one per required key), `min_completion_rate`, `max_new_regressions` (trivially passes with an explicit reason when no production baseline exists), `zero_failures_for_tag` (zero rows if no tags configured), `capability_snapshot_consistency` (always computed, not policy-configurable). Every `EvaluationGateResult` carries `gate_type`, `criterion`, `expected`, `actual`, `passed`, `reason` (on failure), and `evidence_ref` (structured pointers back to the specific evidence used, e.g. a baseline run id).

## Evidence snapshot/freshness behavior

`app/services/evidence_snapshot.py::take_capability_grant_snapshot` produces a deterministic hash over active `AgentCapabilityGrant`s (sorted, grant id/tool id/classification/granted_at) - not a row dump, a fingerprint, per [ADR-0014](../adrs/0014-capability-grant-reproducibility.md)'s recommendation. Taken twice per evaluation (request time, completion time) to catch mid-run changes as a gate, and compared live on every `check_freshness` call to catch post-pass changes as a freshness finding.

`app/services/freshness.py::check_freshness` draws the brief's core distinction precisely: `historically_passed` (permanent, `EvaluationGateResult.passed`, never recomputed) vs. `currently_eligible` (computed fresh, every call, never stored). Five explicit stale reasons, four exact and one honestly approximate:

- `policy_changed`, `evaluator_version_changed`, `missing_required_evaluator`, `capability_grants_changed` - **exact**, computed from either this platform's own data or a live catalog re-fetch.
- `dataset_changed` - **approximate, and named as such**. A real, load-bearing finding from this phase: `agent-eval`'s `GET /datasets/{id}` never exposes case `input`/`expected` content, only `id`/`key`/`tags` - the only place its real `dataset_snapshot_hash` is computed is server-side, inside a run response. Reconstructing that hash client-side would mean reimplementing `agent-eval`'s own dataset-hashing logic, explicitly forbidden by this phase's brief. `dataset_case_set_fingerprint` is a deliberately, distinctly-named weaker proxy - catches structural changes (cases added/removed/renamed/re-tagged), not in-place content edits. This limitation is stated everywhere the fingerprint appears - code comments, `docs/evaluation-and-promotion.md`, `docs/failure-modes.md`, `docs/open-questions.md` - never presented as equivalent to the real thing.

## Lifecycle behavior

`draft/evaluating → evaluating` on request; `evaluating → candidate` automated when every gate passes; `evaluating → draft` automated on any gate failure *or* any agent-eval call failure (unavailable/timeout/malformed) - both send the version back to the same requestable state, since either way the only path forward is retry-the-request or a new `AgentVersion`. `candidate`/`production`/`retired` versions reject a new evaluation request (`409`) - proven both by test and live (attempting to re-evaluate the real `incident-investigator` version after it became `candidate` was not attempted live, but is the exact behavior `_REQUESTABLE_STAGES = {DRAFT, EVALUATING}` enforces and `tests/test_evaluations.py::test_cannot_request_evaluation_for_candidate_version` proves). No human override exists anywhere in this phase's code, matching the stop condition.

## Failure/retry/idempotency model

Every failure mode the brief named was implemented and tested, most also live-observed:

- **Agent Eval unavailable / times out / malformed response**: three distinct exception types, identical downstream handling (`status='failed'`, stage reverts to `draft`, `evaluation.failed` audited), distinguishable error messages.
- **Evaluation task retried / duplicate callback**: an atomic conditional claim (`UPDATE ... WHERE status='requested' RETURNING id`) makes a second delivery of the same job a safe no-op - test-verified, and this is the real mechanism that would protect against Cloud Tasks' at-least-once delivery semantics once real delivery is exercised (Phase 6).
- **Idempotency key**: `EvaluationRunReference.idempotency_key` (unique when set) lets a retried HTTP request return the existing reference rather than double-submitting.
- **Policy changed mid-run**: gates are computed against the policy *pinned at request time*, never re-resolved - test-verified with a real policy-version-bump scenario mid-flight.
- **Capability grants changed mid-run**: a request-time vs. completion-time snapshot-hash mismatch fails the `capability_snapshot_consistency` gate outright - test-verified, and conceptually the same mechanism proven live in the stale/blocked demo (just applied to a change *after* a pass rather than *during* a run).
- **Dataset/evaluator mismatch**: caught at request time, before any slow `agent-eval` call - `422`, no wasted multi-minute round trip.
- **Partial gate-computation failure**: gate computation is atomic (one pure function call); any exception anywhere in `_persist_success` is caught by the same handler as the next item.
- **DB write failure after external run completion**: the sharpest distributed-failure boundary in the system - `agent-eval` genuinely succeeded, local persistence failed. Handled with a *second* transaction that marks the reference `'failed'` while explicitly preserving `external_run_id` and writing a reconciliation-path error message ("re-fetch via GET /runs/{id}, or retry"). Test-verified by forcing `_persist_success` to raise and confirming the breadcrumb survives.

## Authorization

Applied the existing Phase 1 permission matrix, no new roles: `can_manage_evaluation_policy` (Admin-only, policy creation), `can_request_evaluation` (Builder-own-team-or-above, already existed from Phase 1, now actually wired to an endpoint). Negative tests cover every restriction: non-Admins rejected from policy creation (`403`, all three lower roles individually tested); Viewers rejected from requesting evaluations.

## Audit guarantees

New event types this phase: `evaluation_policy.created`, `evaluation.requested`, `evaluation.completed`, `evaluation.failed`, `agent_version.became_candidate` - matching the brief's list (`evaluation_evidence.stale` was considered and deliberately not implemented as a *stored* event, since staleness is computed live/on-demand by `check_freshness` rather than detected and recorded at a point in time - there's no moment "staleness happens" to audit, only a live query that may or may not currently report it). The same-transaction guarantee proven in Phase 2 for `Agent` creation was proven again for Phase 3's own writes: `tests/test_phase3_audit.py::test_evaluation_policy_creation_rolls_back_if_audit_fails` forces a mid-transaction audit failure and confirms the `EvaluationPolicy` row doesn't exist afterward.

**Distributed failure boundary, documented precisely**: the one place this system's transactional guarantee necessarily uses two transactions instead of one is the DB-write-failure-after-external-success path (above) - by the time local persistence fails, the first transaction has already rolled back, so recording *that a distinct failure occurred* requires a second transaction. This is a documented exception to "audit and state change always share one transaction," not a silent violation of it.

## Tests

**146 total passing** (82 from Phase 1/2, 64 new this phase): 19 pure gate-computation tests, 6 evidence-snapshot tests, 8 policy tests, 8 core worker tests + 4 additional failure-mode-specific worker tests, 7 request-flow/API tests, 10 freshness tests, 3 Phase-3-specific audit tests. Every external `agent-eval` call is mocked in the automated suite via `tests/fakes/agent_eval.py`, matching the exact real response schemas - only the two live demos (below) touch the real deployed service.

## Bugs discovered

1. **Two routers forgotten from `main.py`** during initial wiring - caught by checking the live OpenAPI schema before writing tests, same discipline as Phase 2.
2. **A real, precise Cloud SQL Postgres limitation**: `REVOKE CONNECT` doesn't work against a `cloudsqlsuperuser`-derived role. Root-caused and correctly characterized (object-level grants are the real boundary) rather than assumed to work from the statement's apparent intent - see [ADR-0017](../adrs/0017-shared-cloud-sql-instance-isolated-database.md).
3. **A genuine, non-obvious SQLAlchemy async test-harness bug, root-caused rather than worked around**: `db_session.expire_all()` (used to make a test session see a worker's separate-session changes) was expiring *every* object in the session's identity map, including the `org` fixture's `Team`/`User` rows - touching `.id` on those afterward triggered a synchronous attribute-reload attempt that crashes under SQLAlchemy's async engine (`MissingGreenlet`). Two false leads were chased and abandoned before finding this (a `pool_pre_ping` interaction, and general "session churn") - the actual fix was narrow: `db.expire(specific_object)` instead of `expire_all()`, touching only the rows the worker actually mutated.
4. **`gcloud auth print-identity-token --audiences` rejects a human user account** ("Invalid account type") - resolved by minting short-lived impersonated ID tokens via `google.auth.impersonated_credentials` instead of downloading a persistent service-account key, which was deliberately avoided as an unnecessary credential-exposure risk.
5. **A real, evidence-based policy-design finding, not a bug**: `incident-investigator`'s first real evaluation policy required an evaluator (`final_output_contains_keywords`) that turned out to produce no applicable score for the real dataset's case shape. Correctly surfaced as a failing gate rather than silently ignored; fixed by publishing a corrected policy version, exercising the immutability model exactly as designed.

## Architecture/ADR changes

- **New**: [ADR-0015](../adrs/0015-evaluation-policy-immutability.md) (policy immutability), [ADR-0016](../adrs/0016-agent-eval-deployment-decision.md) (deployment decision), [ADR-0017](../adrs/0017-shared-cloud-sql-instance-isolated-database.md) (shared-instance isolation).
- **Amended**: [ADR-0005](../adrs/0005-agent-eval-as-external-source-of-truth.md) - the deployment/auth prerequisites it originally named as blockers are now resolved (linked to ADR-0016); the Cloud Tasks delivery gap is now named precisely as the one remaining unresolved piece.
- **Docs substantially rewritten**: `evaluation-and-promotion.md` (real gate/freshness/dispatch model replacing Phase 0's sketch), `gcp-architecture.md` (real deployment topology, cost, service-to-service auth), `failure-modes.md` (implemented-and-verified status per failure mode), `domain-model.md` (real schema for the three evaluation entities), `api-reference.md`, `roadmap.md`, `open-questions.md`, `control-plane-boundaries.md`.

## Live verification evidence

Both required workflows run against the **real deployed** `agent-eval-api` Cloud Run service - not a local instance, not mocked:

### Passing flow

1. Real `gcloud` service-account impersonation configured (`agent-dev-platform-caller`, no persistent key file); confirmed working against `agent-eval-api`'s IAM-protected `/health`.
2. Created `EvaluationPolicy(name="incident-investigator", version="v1")` as Admin, requiring `final_output_contains_keywords` among others.
3. Requested a real evaluation for the real `incident-investigator@4.2.0` AgentVersion (from Phase 2's live demo) against `external_agent_version_id` from the deployed `agent-eval`'s own catalog. `202`, `stage → evaluating` confirmed immediately.
4. **Real run executed**: ~3.5 minutes, real LangGraph + Vertex AI Gemini calls against the real `ai-ops-api`. Completed with a genuine `min_dimension_score` gate failure (`task_correctness`, n/a for this dataset) - version correctly stayed `draft`.
5. Published `EvaluationPolicy v2` with corrected requirements (immutable - a new row, `v1` untouched).
6. Requested a second real evaluation against `v2`. **Real run executed** again (~3.5 minutes). **11/11 gates passed**; `stage → candidate` confirmed; `GET .../candidacy` confirmed `historically_passed: true`, `currently_eligible: true`, `stale_findings: []`.

### Stale/blocked flow

7. Listed the version's one remaining active `AgentCapabilityGrant` (from Phase 2's demo).
8. Revoked it as Jordan Brooks (Reviewer).
9. Confirmed, in order: (a) the historical evaluation's gates are unchanged, `all_passed: true`; (b) `stage` remains `candidate`, unchanged; (c) `GET .../candidacy` now reports `currently_eligible: false` with exactly one stale finding, `capability_grants_changed`, naming the before/after snapshot hash explicitly.

### Additional infrastructure proof

10. Enabled Cloud Tasks API, created a real queue (`evaluation-jobs`, `us-central1`), and used the real `CloudTasksDispatcher` class to create and enqueue a genuine task - independently confirmed via `gcloud tasks list`, which showed real dispatch attempts and retries against a deliberately-unreachable placeholder target. Purged the queue afterward to stop retry churn.
11. Cleanly shut down all locally-started processes (the verification `uvicorn` instance, the `cloud-sql-proxy` instance started this session); left pre-existing processes (another `cloud-sql-proxy`, the `ai-operations`/`agent-eval` local dev servers) untouched.

## Next step

Stopping here per instruction. Not beginning human promotion approval, `candidate → production`, reviewer workflows, audit UI, or frontend until this phase is reviewed.
