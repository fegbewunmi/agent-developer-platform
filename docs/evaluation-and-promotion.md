# Evaluation Integration and Promotion Lifecycle

## The integration contract with Agent Evaluation Platform

`agent-eval` remains the only place evaluators execute, datasets live, and regressions are computed. This platform never re-implements any of that (see [`control-plane-boundaries.md`](control-plane-boundaries.md)). It integrates against `agent-eval`'s real, inspected API:

- **Trigger**: `POST /runs` on `agent-eval`, with `agent_version_id`, `dataset_id`, `evaluator_ids[]`.
- **Read results**: `GET /runs/{run_id}` → `dimension_stats[]` (mean score, pass/fail counts per dimension); `GET /runs/compare?run_a_id&run_b_id` → `regressions[]`/`improvements[]`, `evaluator_version_mismatches[]`, `dataset_drift_detected`.
- **Case-level detail**: `GET /runs/{run_id}/cases/{case_run_id}` — this platform links out to it for humans; it never stores case-level data itself.

### The problem this contract has to work around: `POST /runs` is synchronous

Inspection of `agent-eval/backend/app/api/runs.py` confirmed `POST /runs` blocks in-request until the entire run completes — there is no async job/status-polling pattern (an explicit MVP choice in `agent-eval`'s own ADR-0005). `ai-operations`' own eval runner comments note real per-case latency of 60–75 seconds; a full dataset run can run many minutes. This platform's control-plane API must never make this call synchronously from a user-facing request handler — doing so would tie up an API worker and a browser request for the full run duration.

**Resolution**: the platform never calls `POST /runs` directly from the API layer. Requesting an evaluation creates an `EvaluationRunReference(status='requested')` row and enqueues a **Cloud Tasks** job. A worker executes the (still-blocking) `POST /runs` call out-of-band, then writes the response back onto the `EvaluationRunReference` (`external_run_id`, `dataset_snapshot_hash`, `evaluator_versions`, `status='completed'`) and computes `EvaluationGateResult`s. See [`gcp-architecture.md`](gcp-architecture.md) and [ADR-0005](adrs/0005-agent-eval-as-external-source-of-truth.md).

This is a real limitation in a system this platform depends on but does not own fixing (`agent-eval`'s non-goals here explicitly exclude rebuilding it) — noted as a dependency risk in [`open-questions.md`](open-questions.md), not silently worked around as if it weren't real.

### Prerequisite: agent-eval must actually be reachable from this platform's cloud environment

Everything above describes the **intended, deployed** architecture — a Cloud Run/Cloud Tasks control plane calling a Cloud-Run-hosted `agent-eval` over an authenticated network path. That target state does not exist yet, and Phase 1–2 implementation work does not depend on it existing. Inspection confirmed, and it bears repeating precisely here rather than only in the GCP architecture doc: `agent-eval/infra/` today contains only a `docker-compose.yml` running a bare Postgres container — no Cloud Run service, no Dockerfile for its own backend/frontend, nothing deployed. It runs on a developer's machine, reachable only at `localhost`. It also has no authentication of any kind (`docs/auth-and-approval-model.md`).

This means the Cloud Tasks integration in this section is **not implementable as real cloud-to-cloud traffic** until two things are independently true, neither of which this repo controls unilaterally:

1. **`agent-eval` is deployed** to a reachable environment (Cloud Run, matching this platform's own topology, is the natural choice, but that's `agent-eval`'s decision to make).
2. **Service-to-service authentication exists between the two platforms** — today neither side has any identity to present or verify, so even a reachable `agent-eval` would be an open, unauthenticated endpoint on the network, which is not an acceptable way to trigger evaluation runs from a production control plane.

These two conditions are an **explicit prerequisite for the phase that implements the real Cloud Tasks → agent-eval integration** (Phase 3, `docs/roadmap.md`), not an assumption baked silently into the architecture. Until both are met, Phase 3's implementation targets a local/dev `agent-eval` instance over an unauthenticated connection — acceptable for development and for proving the integration shape works, explicitly **not** representative of a production-safe deployment, and the phase's own report must say so rather than imply otherwise. See [ADR-0005](adrs/0005-agent-eval-as-external-source-of-truth.md) and [`open-questions.md`](open-questions.md) #4.

### Diagram: evaluation sequence

```mermaid
sequenceDiagram
    participant B as Builder
    participant API as Developer Platform API
    participant CT as Cloud Tasks
    participant AE as Agent Evaluation Platform

    B->>API: Request evaluation for AgentVersion
    API->>API: create EvaluationRunReference(status=requested)
    API->>CT: enqueue run-evaluation task
    API-->>B: 202 Accepted (reference id)
    CT->>AE: POST /runs (agent_version_id, dataset_id, evaluator_ids)
    Note over AE: blocks for full run duration (agent-eval ADR-0005)
    AE-->>CT: RunSummaryResponse (dimension_stats, status=completed)
    CT->>API: write back external_run_id, dataset_snapshot_hash,\nevaluator_versions, status=completed
    API->>API: compute EvaluationGateResult[] against EvaluationPolicy
    API->>API: publish evaluation.completed (Pub/Sub)
    B->>API: view results
    API->>AE: GET /runs/{id}/cases/{case_id} (link-out for detail)
```

## The evaluation policy / gate model

`agent-eval` has **no policy or gate concept at all** — confirmed by inspection: no `Policy`/`Gate`/`ThresholdSet` entity, thresholds live only as opaque per-evaluator `config` JSONB, and `GET /runs/compare` is explicitly informational, consumed by nothing. Gating is entirely this platform's responsibility to build, which is exactly the gap the brief identifies (*"do not collapse evaluation results into one opaque quality score"*).

`EvaluationPolicy` (versioned, immutable per `(name, version)` — same pattern as `agent-eval`'s own `Evaluator` versioning):

- `required_evaluator_keys[]` — which evaluators must have run
- `thresholds` — e.g. `{"grounding": {"min_mean": 0.85}, "task_correctness": {"min_mean": 0.90}}`
- `zero_new_regressions: true` — compares against the current `production` version's most recent evaluation for the same `Agent`
- `dataset_key` — which dataset this policy expects

At promotion-request time (not run-request time — see freshness below), the platform computes one `EvaluationGateResult` row per criterion:

| Criterion example | Expected | Actual (from agent-eval) | Passed |
|---|---|---|---|
| `grounding >= 0.85` | 0.85 | 0.91 | true |
| `zero_new_regressions` | 0 | 0 | true |
| `evaluator_versions_match_policy` | matches policy | 1 mismatch found | **false** |
| `dataset_snapshot_current` | current hash | stale | **false** |

A `PromotionRequest` cannot reach `candidate`/`production` if any gate fails. Gates are **hard blockers with no override** in this MVP — see [ADR-0008](adrs/0008-automated-gates-vs-human-approval.md) for why an emergency-override path was deliberately deferred rather than built speculatively.

## Evidence freshness

Freshness is re-checked **live, at promotion-request time**, not frozen at evaluation-run time — because the run itself might be minutes or days old by the time promotion is requested, and both the dataset and the evaluator catalog in `agent-eval` are mutable:

- Dataset: re-fetch `agent-eval`'s current dataset snapshot hash and compare to the one recorded on the `EvaluationRunReference`. Mismatch → `dataset_snapshot_current` gate fails.
- Evaluators: re-fetch `GET /evaluators`, compare versions to what's recorded. Mismatch → `evaluator_versions_match_policy` gate fails.
- Policy: gates are always computed against whichever `EvaluationPolicy` is current for the `Agent` at promotion-request time — if the policy changed since the evaluation ran, the run is simply re-graded against the new policy, and likely fails a threshold it used to pass. The `EvaluationPolicy.id` used is recorded on the `PromotionRequest` for audit, so "which policy actually gated this" is always answerable even after the policy is superseded.

See the full enumeration of stale-evidence and unavailable-dependency scenarios in [`failure-modes.md`](failure-modes.md).

## Promotion lifecycle

```
draft → evaluating → candidate → production → retired
```

### Diagram: promotion state machine

```mermaid
stateDiagram-v2
    [*] --> draft: AgentVersion created
    draft --> evaluating: Builder requests evaluation run
    evaluating --> evaluating: re-run requested\n(e.g. after infra flakiness)
    evaluating --> candidate: automated — all gates pass
    evaluating --> draft: automated — gate(s) fail\n(fix requires a new AgentVersion,\nnot editing this one)
    candidate --> production: PromotionRequest approved\n(Reviewer/Admin, not requester)
    candidate --> retired: abandoned
    draft --> retired: abandoned
    production --> retired: automatic on supersession,\nor manual retirement
    retired --> production: rollback = a new PromotionRequest\nfor this old immutable version
```

### Legal transitions and who can request them

| Transition | Trigger | Who can request | Evidence required |
|---|---|---|---|
| `draft → evaluating` | Request an evaluation run | Builder, Reviewer, Admin | none |
| `evaluating → candidate` | Automated | System (gate evaluator) | all `EvaluationGateResult`s pass |
| `evaluating → draft` | Automated | System | any gate fails |
| `candidate → production` | `PromotionRequest` approved | Requested by Builder/Reviewer/Admin; approved by Reviewer/Admin **who is not the requester** | fresh, passing gate results cited on the request |
| `candidate → retired` | Abandon | Builder (own team), Reviewer, Admin | none |
| `production → retired` | Retire or superseded | Admin, Reviewer (manual); automatic on a new promotion to `production` for the same `Agent` | none |
| `retired → production` | Rollback | Same as `candidate → production` — a rollback **is** a `PromotionRequest`, not a special transition | see [`open-questions.md`](open-questions.md) on whether freshness rules relax for rollback |

### Only one production version per Agent

Enforced with a database-level partial unique index on the lifecycle table: `UNIQUE (agent_id) WHERE stage = 'production'` on `AgentVersionLifecycle`, not on `AgentVersion` itself — stage lives there, not on the immutable version row (see [`agent-versioning.md`](agent-versioning.md#the-stage-vs-content-split)). Promoting a new version to `production` and retiring the previous one happen in a single serializable transaction, both as `UPDATE`s to `AgentVersionLifecycle` rows — see the concurrent-promotion scenario in [`failure-modes.md`](failure-modes.md) for how two simultaneous promotion attempts are resolved.

### What a PromotionRequest captures

`agent_version_id, from_stage, to_stage, requested_by, requested_at, evaluation_run_reference_id, status, reason`, resolved by exactly one `PromotionDecision(decision, decided_by, decided_at, comment)`. Together these make "why did this version reach production" answerable from the `PromotionRequest`/`PromotionDecision`/`EvaluationGateResult`/`EvaluationPolicy` chain alone, without needing to reconstruct anything from `agent-eval` after the fact (though the link to `agent-eval`'s detailed run view is preserved for anyone who wants to go deeper).

### Diagram: promotion sequence

```mermaid
sequenceDiagram
    participant Bu as Builder
    participant API as Developer Platform API
    participant Rv as Reviewer

    Bu->>API: POST /promotions (agent_version_id, to_stage=production)
    API->>API: re-check evidence freshness (dataset hash, evaluator versions)
    alt gates fail or evidence stale
        API-->>Bu: 409 — blocked, with explicit reasons per failed criterion
    else gates pass
        API->>API: create PromotionRequest(status=pending)
        API-->>Bu: 201 Accepted
        Rv->>API: GET /promotions/{id} (review evidence + gate results)
        Rv->>API: POST /promotions/{id}/decision (approve)
        API->>API: reject if decided_by == requested_by
        API->>API: transaction: set AgentVersionLifecycle.stage=production,\nretire previous production version's lifecycle row,\nwrite PromotionDecision
        API->>API: publish promotion.approved, agent_version.promoted (Pub/Sub)
        API-->>Rv: 200 OK
    end
```
