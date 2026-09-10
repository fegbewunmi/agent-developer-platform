# Evaluation Integration and Promotion Lifecycle

**Status: Phase 3 implemented and live-verified through `draft → evaluating → candidate`. `candidate → production` (human approval) is Phase 4 - not built yet.**

## The integration contract with Agent Evaluation Platform

`agent-eval` remains the only place evaluators execute, datasets live, and regressions are computed. This platform never re-implements any of that (see [`control-plane-boundaries.md`](control-plane-boundaries.md)). It integrates against `agent-eval`'s real, re-inspected API, implemented in `app/integrations/agent_eval_client.py`:

- **Trigger**: `POST /runs` with `agent_version_id`, `dataset_id`, `evaluator_ids[]`, `triggered_by`, `timeout_seconds` → `RunSummaryResponse` (`dimension_stats[]`, `case_runs[]`, `dataset_snapshot_hash`, `status`).
- **Re-fetch a run**: `GET /runs/{run_id}` (same shape), with an optional `?tag=` filter used by the `zero_failures_for_tag` gate.
- **Compare two runs**: `GET /runs/compare?run_a_id&run_b_id` → `regressions[]`/`improvements[]` (per case/dimension `passed` transitions), `evaluator_version_mismatches[]`, `dataset_drift_detected` - used for the `max_new_regressions` gate.
- **Catalog reads**: `GET /evaluators`, `GET /datasets`, `GET /datasets/{id}` (the latter includes each case's `id`/`key`/`tags`, but never its `input`/`expected` content - see "The dataset-fingerprint limitation" below).
- **Case-level detail**: `GET /runs/{run_id}/cases/{case_run_id}` exists on `agent-eval` but this platform never calls it - only summary evidence (`dimension_stats`, case-completion counts) is stored locally; deep inspection stays a link-out to `agent-eval` for humans.

`agent-eval` is now deployed to Cloud Run (`agent-eval-api`, IAM-authenticated) - see [ADR-0016](adrs/0016-agent-eval-deployment-decision.md) and [`gcp-architecture.md`](gcp-architecture.md). `HttpAgentEvalClient` sends no `Authorization` header at all against an unauthenticated local instance, and a real Google-signed ID token (`google.oauth2.id_token`/`google.auth.impersonated_credentials`) against the deployed one - live-verified both ways (`docs/phase-notes/phase-3.md`).

### The problem this contract has to work around: `POST /runs` is synchronous

Confirmed still true against the real deployed service: a 3-case `incident-investigator` run took ~3.5–4 minutes end to end (real LangGraph + Vertex AI Gemini calls). This platform's API layer must never make this call synchronously from a user-facing request handler.

**Resolution, as actually implemented**: `POST /v1/agent-versions/{id}/evaluations` (`app/api/evaluations.py`) does none of the slow work itself - it resolves the dataset/evaluator identities (fast, local-catalog lookups), creates `EvaluationRunReference(status='requested')`, transitions the version to `evaluating`, and returns `202` immediately. The actual `POST /runs` call happens in `app/services/evaluation_worker.py::process_evaluation_job`, dispatched via `app/services/job_dispatch.py`. See "Async dispatch: what's real and what isn't" below for exactly which half of this is production-shaped and which half is a documented test/dev stand-in.

### Async dispatch: what's real and what isn't

Two implementations of the same `JobDispatcher` interface exist, and this phase used both for different purposes - conflating them would be exactly the "do not pretend a local in-process call is Cloud Tasks" mistake the brief warned against:

- **`LocalSyncDispatcher`** (`app/services/job_dispatch.py`) - fires the worker via `asyncio.create_task`, non-blocking but **not durable**: no retry on failure, no persistence across a process restart, no delivery guarantee. This is what every automated test and both live demos this phase actually ran against (`docs/phase-notes/phase-3.md`).
- **`CloudTasksDispatcher`** - the real production implementation, using `google-cloud-tasks` to create a genuine HTTP task targeting `POST /internal/tasks/evaluations/{id}` (`app/api/tasks.py`), OIDC-authenticated the same way Cloud Tasks → Cloud Run push auth normally works. Live-verified this phase as far as **task creation** goes: a real queue (`evaluation-jobs`, `us-central1`) was created, a real task was enqueued, and `gcloud tasks list` independently confirmed Cloud Tasks made real delivery attempts (and correctly retried) against a deliberately-unreachable placeholder target. **Not** verified as far as delivery-to-a-live-receiver, because that receiver is this platform's own API, which isn't deployed to Cloud Run yet (Phase 6, `docs/roadmap.md`). This is a real, current, named gap - not a historical one.

`app/dependencies.py::get_job_dispatcher` selects between them via `settings.job_dispatch_mode` (`"local"` default, `"cloud_tasks"` when configured with a real queue/target).

### Diagram: evaluation sequence

```mermaid
sequenceDiagram
    participant B as Builder
    participant API as Developer Platform API
    participant D as JobDispatcher (local or Cloud Tasks)
    participant W as Evaluation Worker
    participant AE as Agent Evaluation Platform

    B->>API: POST .../evaluations {external_agent_version_id}
    API->>API: resolve dataset_id/evaluator_ids from current EvaluationPolicy
    API->>API: create EvaluationRunReference(status=requested)\n+ capability_grant_snapshot_hash
    API->>API: stage: draft/evaluating -> evaluating
    API-->>B: 202 Accepted (reference id)
    API->>D: dispatch_evaluation_job(reference_id)
    D->>W: process_evaluation_job(reference_id)
    W->>W: claim reference (status requested -> dispatched, atomic)
    W->>AE: POST /runs (agent_version_id, dataset_id, evaluator_ids)
    Note over AE: blocks for full run duration (confirmed live: ~4 min for a 3-case real run)
    AE-->>W: RunSummaryResponse (dimension_stats, status=completed)
    W->>W: take completion-time capability snapshot
    W->>AE: GET /datasets/{id} (case set fingerprint)
    W->>AE: GET /runs/compare (if a production baseline exists)
    W->>W: compute EvaluationGateResult[] against the policy pinned at request time
    W->>W: stage: evaluating -> candidate (all gates pass) or draft (any gate fails)
    W->>W: write evaluation.completed + (if candidate) agent_version.became_candidate audit events
    B->>API: GET .../evaluations/{id}, GET .../gates
    API->>AE: (human, out of band) deeper case inspection via agent-eval's own UI/API
```

## The evaluation policy / gate model

`agent-eval` has **no policy or gate concept at all** - reconfirmed against the deployed service in Phase 3: no `Policy`/`Gate`/`ThresholdSet` entity, `GET /runs/compare` remains informational. Gating is entirely this platform's responsibility (`app/services/gates.py`), computed once per completed run and persisted as one `EvaluationGateResult` row per criterion - never a blended score.

`EvaluationPolicy` is **fully immutable** as of Phase 3 (DB-level `UPDATE`/`DELETE` revoked, matching `AgentVersion`/`SkillVersion` - [ADR-0015](adrs/0015-evaluation-policy-immutability.md)):

- `thresholds` - `{"<dimension>": {"min_mean": <float>}, ...}` - one `min_dimension_score` gate per entry.
- `required_evaluator_keys` - `{"<evaluator_key>": "<required_version>", ...}` - one `required_evaluator_version` gate per entry, checked against what was *actually submitted* to `agent-eval` at request time (not re-fetched live - that's freshness's job, below).
- `max_new_regressions` (int, default `0`) - one `max_new_regressions` gate, comparing against the current production version's most recent completed evaluation on the same dataset. **Trivially passes** with no baseline if no production version exists yet for the agent - confirmed both in tests and live (Phase 3's real `incident-investigator` demo had no baseline and passed this gate with reason "no production baseline evaluation exists yet").
- `zero_failure_tags` (list of case tags) - one `zero_failures_for_tag` gate per tag, `0` rows if the list is empty (no criterion configured, no gate to check).
- `min_completion_rate` (default `1.0`) - one `min_completion_rate` gate, computed from `case_runs[].status`.
- **`capability_snapshot_consistency`** (always computed, not policy-configurable) - compares the capability-grant snapshot hash taken at evaluation-*request* time against a fresh one taken at *completion* time, catching "capability grants changed while evaluation was running" ([`failure-modes.md`](failure-modes.md)). Live-verified as a real failure trigger in `tests/test_evaluation_worker.py`.
- `dataset_key` - resolves to a real `agent-eval` dataset by name at request time; not itself a gate, but the input to the dataset-identity freshness check below.

A version becomes `candidate` only if **every** gate for that run passed - `all(g.passed for g in computed_gates)`, computed once, right when the run completes (`app/services/evaluation_worker.py::_persist_success`). Gates are **hard blockers with no override**, per [ADR-0008](adrs/0008-automated-gates-vs-human-approval.md) - unchanged in Phase 3.

**Live-verified, real example** (`docs/phase-notes/phase-3.md`): `incident-investigator`'s first real policy (`v1`) required an evaluator (`final_output_contains_keywords`) that turned out to produce no applicable score for the real dataset's case shape - a genuine `min_dimension_score` gate failure, not a bug, correctly blocking `candidate`. Because policies are immutable, the fix was publishing `v2` with a corrected `required_evaluator_keys`, not editing `v1` - and re-running against it produced 11/11 passing gates and a real `candidate` transition.

## Evidence freshness

`app/services/freshness.py::check_freshness` draws the exact distinction the brief calls for: **"evaluation passed at the time"** (a permanent historical fact - `EvaluationGateResult.passed`, never recomputed) vs. **"evidence is still valid for promotion now"** (computed live, every call, never stored). A version can be `stage=candidate` while `currently_eligible=false`.

Computed live against the most recent evaluation run whose gates all passed:

| Stale reason | How it's detected | Precision |
|---|---|---|
| `capability_grants_changed` | Re-take the capability-grant snapshot now; compare hash to the one stored on the passing run reference | Exact - this platform's own data |
| `evaluator_version_changed` | Re-fetch `GET /evaluators` now; compare each required evaluator's current version to what was recorded at request time | Exact - live catalog read |
| `missing_required_evaluator` | A required evaluator key no longer exists in the live catalog at all | Exact |
| `policy_changed` | Compare the passing run's `evaluation_policy_id` to whatever `get_current_policy_for_agent` resolves to now | Exact - this platform's own data |
| `dataset_changed` | See "The dataset-fingerprint limitation" below | **Approximate, and named as such** |

### The dataset-fingerprint limitation

A real, load-bearing finding from Phase 3 implementation, not a hypothetical: `GET /datasets/{id}` (agent-eval's real, re-confirmed schema) returns each case's `id`/`key`/`tags` only - **never** its `input`/`expected` content, which is what agent-eval's own `dataset_snapshot_hash` is actually computed over, server-side, only as part of a `RunSummaryResponse`. There is no standalone "give me the current dataset hash" endpoint. Reconstructing agent-eval's exact hash client-side would mean reimplementing its dataset-hashing logic, which the Phase 3 brief explicitly forbids ("do not reimplement... dataset logic").

The honest resolution: `dataset_case_set_fingerprint` (`app/services/freshness.py`) is a **distinctly-named, deliberately weaker** platform-computed proxy - a hash over sorted `{key, tags}` pairs. It reliably catches cases added, removed, renamed, or re-tagged. It **cannot** detect a case's `input`/`expected` content changing while its key stays the same. This limitation is stated everywhere the fingerprint is used (code comments, this doc, `docs/failure-modes.md`, `docs/open-questions.md`) - never presented as equivalent to agent-eval's own hash. Tracked as a named ask for `agent-eval` to expose a real current-hash endpoint (`docs/open-questions.md`).

See the full enumeration of stale-evidence and unavailable-dependency scenarios in [`failure-modes.md`](failure-modes.md).

## Promotion lifecycle

```
draft → evaluating → candidate → production → retired
```

**Implemented through `candidate` this phase.** `candidate → production` (human `PromotionRequest`/`PromotionDecision` approval) is Phase 4 scope - the tables and no-self-approval DB trigger already exist (Phase 1), but no request/decision service or API exists yet.

### Diagram: promotion state machine

```mermaid
stateDiagram-v2
    [*] --> draft: AgentVersion created
    draft --> evaluating: evaluation requested (implemented)
    evaluating --> evaluating: re-run requested\n(e.g. after infra flakiness) (implemented)
    evaluating --> candidate: automated - all gates pass (implemented, live-verified)
    evaluating --> draft: automated - gate(s) fail,\nor agent-eval unavailable/timeout/malformed response\n(implemented, live-verified: real gate failure observed)
    candidate --> production: PromotionRequest approved\n(Reviewer/Admin, not requester) - PHASE 4, NOT BUILT
    candidate --> retired: abandoned - PHASE 4
    draft --> retired: abandoned - PHASE 4
    production --> retired: automatic on supersession,\nor manual retirement - PHASE 4
    retired --> production: rollback = a new PromotionRequest\nfor this old immutable version - PHASE 4
```

### Legal transitions and who can request them

| Transition | Trigger | Who can request | Evidence required | Status |
|---|---|---|---|---|
| `draft/evaluating → evaluating` | Request an evaluation | Builder (own team), Reviewer, Admin | none | Implemented, live-verified |
| `evaluating → candidate` | Automated | System (gate evaluator) | all `EvaluationGateResult`s pass | Implemented, live-verified |
| `evaluating → draft` | Automated | System | any gate fails, or agent-eval call fails | Implemented, live-verified |
| `candidate → production` | `PromotionRequest` approved | Requested by Builder/Reviewer/Admin; approved by Reviewer/Admin **who is not the requester** | fresh, passing gate results cited on the request | **Phase 4** |
| `candidate → retired` | Abandon | Builder (own team), Reviewer, Admin | none | **Phase 4** |
| `production → retired` | Retire or superseded | Admin, Reviewer (manual); automatic on a new promotion | none | **Phase 4** |
| `retired → production` | Rollback | Same as `candidate → production` | see [`open-questions.md`](open-questions.md) | **Phase 4** |

`candidate/production/retired` versions cannot have a new evaluation requested against them (`app/services/evaluations.py::_REQUESTABLE_STAGES = {DRAFT, EVALUATING}`) - live and test-verified to return `409`. A version stuck in `candidate` that later needs re-validation goes through the ordinary route: a new `AgentVersion`.

### Only one production version per Agent

Unchanged from Phase 1/2: `UNIQUE (agent_id) WHERE stage = 'production'` on `AgentVersionLifecycle`. Not yet exercised end-to-end in Phase 3 since nothing reaches `production` until Phase 4.

## Live verification summary

Both required Phase 3 workflows were run against the real deployed `agent-eval-api` Cloud Run service, not a local stand-in - full transcript in [`docs/phase-notes/phase-3.md`](phase-notes/phase-3.md):

1. **Passing flow**: the real `incident-investigator@4.2.0` AgentVersion → real evaluation request → real ~4-minute `agent-eval` execution (LangGraph + Vertex AI Gemini) → 11/11 gates computed and passed → `stage: candidate`, `currently_eligible: true`.
2. **Stale/blocked flow**: revoked a real `AgentCapabilityGrant` on that same candidate version → the historical evaluation run's gates remain unchanged (`all_passed: true`) and `stage` remains `candidate` → but `GET .../candidacy` now reports `currently_eligible: false` with an explicit `capability_grants_changed` stale finding, including the before/after hash.

This is the "major architectural proof point" the brief called for, observed live rather than only reasoned about.
