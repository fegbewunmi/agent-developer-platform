# 0023. Orion is a registry/review platform, not a deployment platform - Stage terminology corrected accordingly

Status: Accepted

## Context

Phase 8 began with a proposal (since withdrawn) to extend Orion into managing real Cloud Run candidate deployments and production traffic shifts for `incident-investigator`. On review, that direction was corrected: Orion's actual value is publishing, discovering, versioning, evaluating, reviewing, and governing agents and reusable skills - not operating a second deployment system alongside Cloud Run/GitHub Actions/whatever CI a team already uses.

That correction exposed a real, specific problem in the existing implementation: the `Stage` enum's `production` value, and the UI/prose built around it ("promote to production," "production version," "candidate"), all describe a deployment-traffic concept Orion has never actually managed and now explicitly will not. A reviewer approving a `PromotionRequest` was never shifting real traffic - they were marking a version as the organization's recommended one. The vocabulary said otherwise, which is exactly the kind of mismatch between what code claims and what it actually does that this project's own architecture-first discipline exists to catch.

## Decision

Rename the `Stage` enum values in place (`ALTER TYPE stage RENAME VALUE`, migration `0017_stage_terminology_rename.py`) - the state machine, every invariant (one `recommended` version per Agent via the existing partial unique index, no-self-approval, hard gates, freshness/staleness), and every service function are completely unchanged:

| Old | New |
|---|---|
| `candidate` | `evaluated` |
| `production` | `recommended` |
| `retired` | `deprecated` |
| `draft`, `evaluating` | unchanged |

User-facing copy is renamed to match throughout the frontend (nav "Promotions" → "Reviews", "Production version" → "Recommended version", dashboard counts, activity-feed labels, etc.) and in backend prose (docstrings, comments, error messages, and API response field names like `production_version_id` → `recommended_version_id`).

**Scoped deliberately, not renamed:** the `PromotionRequest`/`PromotionDecision` classes, their database tables, the `/v1/promotion-requests` route family, and internal `event_type` audit-log string constants (`"promotion.requested"`, `"agent_version.promoted"`, etc.) are all left unchanged. "Promotion"/"promoted" don't themselves imply deployment the way "production" did - a version can be promoted in status/rank in any organizational sense, not just "pushed live." Renaming that whole subsystem's schema and API surface would be a large, high-risk change (every FK reference, every historical audit event's stored `event_type`, every test, every doc cross-reference) for marginal additional clarity over what the `Stage` rename alone already delivers. `AgentVersionLifecycle.stage` was the one place the code text was actually, specifically wrong.

## Alternatives considered

- **Relabel only at the API/UI boundary, keep `candidate`/`production`/`retired` as the internal enum values.** Rejected - this would leave the source code itself saying "production" everywhere a reader would need to understand the real lifecycle (service logic, tests, migrations), permanently out of sync with the documented product vocabulary. The whole point of the correction was that code and product language should agree; a display-only shim doesn't fix that, it just relocates the lie to a translation layer.
- **Also rename `PromotionRequest`/`PromotionDecision` and their tables/routes to `ReviewRequest`/`ReviewDecision`.** Rejected for this phase - a materially larger, riskier migration (breaking every FK, every historical audit `event_type` string's implicit vocabulary, every test and doc cross-reference) for a term that wasn't itself the source of the deployment-platform confusion. Worth revisiting later in isolation if "promotion" language is found to still mislead users in practice; not bundled into this correction.
- **A full enum rebuild (new type, migrate column, drop old type)** instead of `ALTER TYPE ... RENAME VALUE`. Rejected - Postgres's native rename is a metadata-only operation (confirmed live: zero rows touched, the existing partial unique index's predicate updated automatically with no index rebuild), strictly safer and faster than a rebuild for a same-cardinality, same-order rename.

## Consequences

Every existing `AgentVersion`/`AgentVersionLifecycle`/`PromotionRequest` row from every phase of this project - real historical review decisions, real rollbacks, real stale-evidence blocks - was live-verified after migrating the real deployed database to still render correctly and completely under the new vocabulary, with zero data loss and zero manual data migration (`ALTER TYPE RENAME VALUE` preserves each row's underlying value; only the label a human reads changed). Any future code touching `Stage` values must use the new names; any doc or comment describing *current* behavior must use "evaluated/recommended/deprecated," while historical phase notes describing *what was true when they were written* (Phases 1-7) are correctly left saying "candidate/production/retired," per this project's standing rule against rewriting history.
