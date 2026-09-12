# Phase 8 Notes: Product Correction and Real Source Provenance

Status: complete. Two user-directed corrections in sequence, both requested after Phase 7's closure, neither part of the original six-phase plan.

## What happened, in order

1. **An architecture-correction request**: the user identified that Orion's promotion workflow let a human "invent" an `AgentVersion` with no proof it corresponded to a real build. The first response proposed extending Orion into a real deployment platform - candidate Cloud Run revisions, a `DeploymentProvider` abstraction, real production traffic shifts, deployment-drift reconciliation.
2. **A correction of that correction**: the user reviewed the proposal and redirected it before any code was written. Orion should stay a registry/review platform - publish, discover, evaluate, review, govern - and fix the *provenance* gap specifically, without becoming a second deployment system. This is [ADR-0023](../adrs/0023-registry-not-deployment-platform.md).
3. Implementation proceeded against the corrected direction only. The withdrawn deployment-platform proposal was never built - no `DeploymentProvider`, no candidate Cloud Run revisions, no traffic management code exists anywhere in this repo.

## Terminology correction

The real, specific problem: `AgentVersionLifecycle.stage`'s `production` value literally claimed Orion managed deployment/traffic, which it never has. Renamed in place via `ALTER TYPE stage RENAME VALUE` (migration `0017`) - `candidate → evaluated`, `production → recommended`, `retired → deprecated` - a metadata-only operation with **zero data migration and zero data loss**, verified live: every `AgentVersion`/`PromotionRequest` row from every phase of this project (real historical approvals, rejections, rollbacks, stale-blocks) was confirmed to render correctly under the new vocabulary after migrating the real deployed database, with the partial unique index's predicate (`WHERE stage='recommended'`) updating automatically.

Deliberately **not** renamed: `PromotionRequest`/`PromotionDecision` classes, tables, the `/v1/promotion-requests` route family, and audit `event_type` string constants. "Promotion" doesn't itself imply deployment the way "production" did - see [ADR-0023](../adrs/0023-registry-not-deployment-platform.md) for the full reasoning behind this scoping decision.

Backend and frontend copy updated to match throughout (dashboard counts, activity-feed labels, nav "Promotions" → "Reviews", API response field names like `production_version_id` → `recommended_version_id`).

## Real source provenance

The actual gap: `manifest.source.git_ref` was already a documented, parsed field (`AgentVersion.source_ref`) but completely unvalidated free text - typed dozens of times this session with no verification against anything real.

**Domain model** (migration `0018`, both additive/nullable, zero impact on existing rows): `Agent.requires_ci_provenance` (bool, default false) and `AgentVersion.provenance` (JSONB: `git_repo`, `git_commit_sha`, `git_ref`, `image_digest`, `publisher`, `published_at`, `agent_eval_agent_version_id`).

**Enforcement** (`app/services/agents.py::create_agent_version`): an Agent with `requires_ci_provenance=True` rejects manual creation outright - `PermissionDeniedError`, before any role/team check even runs. Provenance is *stored* whenever a real CI caller supplies it (regardless of the flag), but only *required* when the flag is set - discarding a true, verified fact just because the flag happened to be off would have thrown away real data for no reason (a bug found live during the first real pipeline run, fixed the same session). Publication is idempotent by commit SHA: a CI retry for the same commit returns the existing version, never a duplicate, even if the manifest content differs on retry (tested live).

## CI machine identity ([ADR-0024](../adrs/0024-ci-publishing-machine-identity.md))

A dedicated service account, `agent-platform-ci-publisher`, verified via a real Google-signed OIDC token (`app/auth/ci_publisher.py`, the same mechanism already proven for Cloud Tasks/Scheduler) - never a downloaded key. Workload Identity Federation trusts GitHub's own OIDC issuer, scoped by an attribute condition to exactly the `fegbewunmi` account and, on the IAM binding itself, to exactly the `fegbewunmi/ai-operations-center` repository - no other repo, even under the same account, can impersonate this identity.

`POST /internal/ci/agents/{agent_id}/versions` (`app/api/ci_publish.py`) is the only route this identity may call. Live-verified, layered: a real minted token for this SA successfully published a real version; a real human Identity Platform JWT was independently rejected by the same endpoint (`401` - different signing infrastructure entirely); a real human JWT was rejected attempting manual creation via the ordinary human route for the now-locked agent (`403`).

## The real, live GitHub Actions pipeline

A real workflow, `.github/workflows/publish-to-orion.yml`, added to `ai-operations`:

```
push to main (or workflow_dispatch)
  -> checkout, install, run real unit tests (the same suite/exclusions ai-operations' own README documents)
  -> authenticate via Workload Identity Federation (google-github-actions/auth@v2)
  -> mint a real OIDC token, audience = Orion's backend, as agent-platform-ci-publisher
  -> POST real provenance (github.repository, github.sha, github.ref_name) to Orion
```

Two real bugs found and fixed while proving this live, both fixed in the same session:

1. **CI environment gap**: `ai-operations`' own `Settings` requires `GCP_PROJECT_ID`/`DATABASE_URL` with no defaults, so even the DB-independent unit tests failed at import time in a bare GitHub Actions runner. Fixed with placeholder (non-secret) env vars in the workflow - the excluded DB-dependent tests remain excluded, matching the README's own documented split.
2. **Silent failure diagnosis**: the workflow's first version used `curl -sf`, which discards the response body on any HTTP error - a real Google-front-end 400 (later understood to be curl/HTTP2-unrelated; the actual issue was the provenance-storage bug above surfacing as a re-served stale idempotent row) was invisible in the logs. Fixed by capturing and always printing the real status code and body.

Also required, before any of this could be pushed: `ai-operations`' local checkout was 8 real, legitimate commits ahead of `origin/main` (UI/deployment fixes, inspected for secrets before pushing - none found) and one commit behind (a trivial README fix) - reconciled with a clean rebase, confirmed by the user before pushing anything.

## The `agent-eval` gap, closed

Found live while designing this: `agent-eval`'s real, live-calling capability (`IncidentInvestigatorAdapter.execute()`, making genuine HTTP calls to `AgentVersion.config.base_url`) was already proven and working - but nothing could write a new `AgentVersion` over HTTP; only `app/services/seed.py` (a direct-DB-write script) ever created one. Added the smallest fix: `POST /agents/{agent_id}/versions` (`agent-eval` commit `cdf8cf0`), idempotent by `version_label` (reusing the existing `ensure_agent_version` helper unchanged), no new auth code needed (the service is already Cloud Run IAM-protected end to end; the same `roles/run.invoker` grant Orion already holds for `POST /runs` covers this new route too, since Cloud Run IAM is per-service).

Orion's CI-publish flow now calls this automatically and best-effort (`app/integrations/agent_eval_client.py::register_agent_version` - a real failure here never blocks the real provenance publish, only the eval-target registration) whenever `settings.ci_publish_agent_eval_agent_id`/`ci_publish_target_base_url` are configured - currently scoped to the one real integrated agent, deliberately not generalized to a multi-agent mapping until a second real integration exists.

## Full live proof (real systems throughout, repeated after each fix)

A real commit to `ai-operations` → a real GitHub Actions run → real unit tests → real WIF authentication (no stored credential) → a real `POST` to Orion's deployed backend with real provenance → Orion registers a real `AgentVersion` in the real deployed `agent-eval-api` → the real agent-eval version id comes back and is stored in Orion's own immutable `provenance` block. Independently confirmed in `agent-eval`'s own catalog (`GET /agents`) that the registered version and its real `config.base_url` genuinely exist. Then, with `incident-investigator.requires_ci_provenance` flipped to `true`: a real human JWT rejected (`403`) attempting manual creation; the real CI pipeline re-run and still succeeding (`via_ci=True` bypasses the lockout by design).

## Tests

**Backend**: 207 passing (196 carried in from Phase 7 + 3 for the Stage terminology rename's touched paths + 9 for `app/auth/ci_publisher.py` and the provenance/lockout/idempotency service logic in `tests/test_ci_publish.py`, minus overlap - see that file for the full breakdown, including two route-level tests proving the agent-eval registration wiring with a fake client).

**`agent-eval`**: 60 passing (57 carried in + 3 new for the write endpoint, `tests/integration/test_api_agent_versions.py` - creation, idempotency by `version_label`, 404 for an unknown Agent).

**Frontend**: unchanged test count from Phase 7 (55); the Stage-related type/badge/copy renames were covered by updating the existing `Badge.test.tsx`/`ActivityFeed.test.tsx`/`PromotionSection.test.tsx` assertions to the new vocabulary, not new tests.

## Known limitations

- `ci_publish_agent_eval_agent_id`/`ci_publish_target_base_url` are single-agent-scoped settings, not a general per-Agent mapping - correct for "smallest credible integration" with exactly one real CI-integrated agent today; generalizing is the right move once a second one exists, not before.
- Evaluation still targets whichever URL is configured as "currently live" for `incident-investigator`, not the exact commit just published - an honest limitation stated plainly: Orion doesn't manage deployment, so it cannot bind evaluation to "the code actually running at this instant" the way a deployment-aware system could. What it *can* honestly claim, and does: this Orion `AgentVersion` corresponds to this exact real commit, and was evaluated via the real adapter against the real service as configured at evaluation time.
- No automated frontend test exists for the (unchanged from Phase 5's own established convention) CI-publish-specific UI panels, since none were added this phase - provenance display in the UI (repository/commit/publisher) is a natural next increment, not built this phase, matching "do not build UI for its own sake."
