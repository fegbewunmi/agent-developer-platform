# Phase 9 Notes: Shared Agent & Skill Developer Experience

Status: complete. Triggered by direct product feedback after Phase 8 shipped: the backend had real provenance, real terminology, and a real registry data model, but the actual UI still looked and felt like a governance/evaluation dashboard - a developer could not answer basic reuse questions ("who else uses this skill," "is there a newer version," "what happens if I adopt it") from any page. This phase closes that gap between the domain model and the actual product experience.

## The architecture review, and what it found

Per the brief's explicit "report before coding" requirement, the phase began with an audit of what already existed vs. what needed only exposure vs. what needed genuine new domain work. The finding, confirmed correct by implementation: **most of the work was exposing relationships that already existed** (the skill-consumer reverse lookup, `AgentVersion.provenance`, `Agent.requires_ci_provenance`) - not new domain modeling. The two real gaps were narrow: a `SkillVersion` had no "recommended" concept or review workflow at all, and no dependency/impact query existed anywhere.

## SkillVersion review: a separate model, not a `PromotionRequest` reuse

The instinctive first move - reuse `PromotionRequest`/`PromotionDecision` for skill review - doesn't work: that table has hard, `NOT NULL` foreign keys into the AgentVersion evaluation-gate pipeline (`evaluation_run_reference_id`, `evaluation_policy_id`), and a `SkillVersion` has no automated evaluator or `agent-eval` integration at all. Forcing it through would mean either fabricating fake evaluation rows or weakening a currently-hard, proven constraint. See [ADR-0025](../adrs/0025-skill-review-as-a-separate-model.md).

Built instead: `SkillVersionLifecycle` (`published → recommended → deprecated` - a new, narrower enum, not a reuse of `Stage`) and `SkillReviewRequest`/`SkillReviewDecision`, structurally parallel to the Agent side's proven pattern but with every evaluation-specific field removed. Same guarantees, reused as independent mechanisms rather than shared: a DB trigger blocking self-approval (`fn_reject_self_approval_skill_review`), a partial unique index enforcing one `recommended` version per `Skill`, and fully immutable decisions. A `SkillVersion` is `published` immediately at creation; becoming `recommended` requires an independent Reviewer/Admin to approve a request - never automatic, and never grantable by the Builder who published it. Migration `0019_skill_review.py`.

## Dependency and impact analysis - no new tables

`app/services/skills.py::get_skill_impact` is a pure read aggregation over tables that already existed (`SkillVersion`, `AgentVersionSkill`, `AgentVersion`, `AgentVersionLifecycle`, `Agent`) - confirming the architecture review's prediction that this needed no new domain modeling. Two deliberately separate views, per explicit user refinement to the original proposal:

- **`current_impact`**: each Agent's single most recent, non-`deprecated` `AgentVersion`, if it still pins an older `SkillVersion` than the latest one published - one row per Agent, the "who's affected right now" view, prominent in the UI.
- **`historical_consumers`**: every `AgentVersion` that has ever pinned an older version, unfiltered - kept in a separate "All consumers / history" panel so it never drowns out the actionable view with archaeological sediment.

Publishing a newer `SkillVersion` never touches an existing, immutable `AgentVersion`'s pin - adopting it always means publishing a new `AgentVersion`. The impact view is visibility, not migration.

## One-click evaluation - resolution moved server-side

The concrete UX complaint that triggered closer scrutiny of the whole product experience: the evaluation-request form had a raw text field labeled "agent-eval AgentVersion ID" with no way for a normal user to know what to type - discovered live when a real attempt to type a literal string into it produced a `422`. `POST /v1/agent-versions/{id}/evaluations`'s `external_agent_version_id` is now optional; when omitted, `app/services/evaluations.py::_resolve_external_agent_version_id` resolves it from the version's own `provenance.agent_eval_agent_version_id` (set once at CI-publish time). Missing target now raises a real, actionable message - *"This version has not been registered with Agent Eval"* - not a raw foreign-ID validation error. The frontend's `EvaluationSection.tsx` dropped the visible ID field entirely for the normal case; a collapsed "Advanced: specify a target manually" disclosure remains for the one case with no known target (a manually-created version with no CI provenance), matching the brief's "unless in an advanced/debug view."

## Provenance and CI-managed publishing, made visible

Phase 8 stored real CI provenance (`git_repo`, `git_commit_sha`, `git_ref`, `publisher`, `published_at`) but never displayed it. `AgentVersion` detail now has a "Published from GitHub" panel showing all of it for any version that has it; `Agent` detail now shows a "Version publishing" panel branching on `requires_ci_provenance` - "CI managed, no manual create-version flow" vs. "Manual / representative," with an explanation either way. (No manual "create AgentVersion" UI existed anywhere in the frontend before this phase, so there was nothing to actually disable - this closes the *explanatory* gap, not a UI lockout that didn't exist.)

## Skills catalog and detail pages, reworked

`GET /v1/skills` gained `search`/`owner_team_id`/`framework` query params and a per-skill aggregation (`recommended_version_id`/`label`, `version_count`, `consuming_agent_version_count`) via the same single-query-rollup pattern `agents.py::get_catalog_overview` already used - no new pattern invented. The catalog page now shows a real recommended-version badge, version count, owner, and consumer count per card, with a search/filter form.

The skill detail page replaced the old "Pinned by 4.3.0" badge (a raw version label, no agent name, answering nothing) with real consumer relationships - agent name and version, linked - via an enriched reverse lookup (`GET /v1/skill-versions/{id}/agent-versions` now returns `agent_name`). Each `SkillVersion` card shows its real stage badge and an inline review action (request/approve/reject, permission-gated the same way the Agent side is). A prominent "New version available" panel surfaces `current_impact` when a newer version exists with older consumers still active; a separate "All consumers / history" panel below it carries the unfiltered record.

## Overview: from governance dashboard to developer registry

`GET /v1/dashboard/summary` gained `ecosystem` (Agent/Skill/publishing-team counts, pending skill reviews) and `updates` (skills with a newer version than current consumers are on, reusing `get_skill_impact`; CI-published AgentVersions still awaiting their first evaluation) - both suppressed entirely for demo actors, same containment reasoning as the existing `recent_activity` suppression (Phase 7). The Overview page now leads with a "Developer ecosystem" stat row before the existing governance counts, and a new "Updates" panel above "Needs attention."

## Making the shared-skill story real, not just prettier UI

Before this phase, `release-risk-agent` (real, seeded representative data) had **zero AgentVersions** - confirmed by reading `scripts/seed_orion_commerce.py` directly during the architecture review. The "two agents share a skill" story literally didn't exist in any seeded data. Two real fixes, not fabricated data:

1. **`ai-operations`' real CI pipeline was publishing an empty skill list** (`"skills": []` in `publish-to-orion.yml`) despite the agent's real LangGraph graph genuinely having `telemetry.py`/`deployment.py`/`knowledge.py` nodes matching the seeded `SkillVersion`s exactly. Fixed at the source - the manifest now declares `["telemetry-investigation@2.1", "deployment-analysis@1.3", "knowledge-search@3.0"]`. A real commit, pushed, triggered a real GitHub Actions run (`3484aec`), which published a genuine new `incident-investigator` `AgentVersion` (`ci-3484aec9e980`) with real skill pins - confirmed live by querying the production database directly.
2. **`scripts/seed_orion_commerce.py::seed_shared_skill_story`** (new, idempotent) publishes `deployment-analysis@1.4` (no consumers, deliberately), creates `release-risk-agent`'s first real `AgentVersion` (`2.0.0`, pinning `deployment-analysis@1.3`), and files a real `SkillReviewRequest` (Maya Chen, Builder) approved by a real, independent Reviewer (Jordan Brooks) - making `1.3` genuinely `recommended` through the actual review flow, not a lifecycle row silently set by the script. The function checks `Agent.requires_ci_provenance` before attempting a manual `incident-investigator` version and correctly no-ops in production (where it's `true`) - the real CI-published fix above is what actually supplies that agent's pin there; a pre-existing historical `4.3.0` version (created 2026-09-11, before this phase) turned out to already carry the same pin, discovered live rather than assumed.

Final, real production state, confirmed by direct query:

```
deployment-analysis
├── 1.3  RECOMMENDED
│   ├── incident-investigator  4.3.0            (historical, pre-existing)
│   ├── incident-investigator  ci-3484aec9e980   (real, CI-published this phase)
│   └── release-risk-agent     2.0.0             (new, this phase)
└── 1.4  PUBLISHED, no consumers
```

## Tests

**Backend**: 220 passing (207 carried in from Phase 8 + 13 new - `tests/test_skill_reviews.py` (8: lifecycle default state, request→approve, self-approval block including a DB-trigger-level defense-in-depth proof, supersession/one-recommended-per-skill, duplicate-pending-request conflict, reject-then-re-request, and the current-vs-historical impact split), `tests/test_skill_reviews_api.py` (3: HTTP-layer request/approve flow, self-approval `403` over HTTP, the impact endpoint), and two in `tests/test_evaluations.py` (server-side provenance resolution, and the meaningful-422-with-no-target case) plus one extended assertion each in `tests/test_skills_registry.py` and `tests/test_phase5_api.py`).

**Frontend**: 60 passing (55 carried in + 5 new - `canRequestSkillReview`/`canDecideSkillReview` permission unit tests, mirroring the existing Agent-promotion permission tests exactly).

## Deployment

Migration `0019` applied to both local dev/test and the real production Cloud SQL database (via the Cloud SQL Auth Proxy, admin credentials from Secret Manager - the same pattern as every prior phase's real migration). Backend deployed as `agent-platform-api` revision from image `v11`; frontend as `agent-platform-web` revision from image `v7`. The `ai-operations` workflow fix was committed and pushed directly (small, single-file, in-scope for the real provenance/composition story this phase is about).

## Known limitations

- `get_skill_impact`'s `current_impact` considers each Agent's single most recent non-deprecated `AgentVersion` - an Agent with two live, divergent version lines (not a pattern this system currently supports or any real Agent uses) would only show its newest. Matches every real Agent's actual usage today; revisit if that assumption stops holding.
- The skill review queue has no dedicated cross-skill page yet (unlike the Agent promotion queue's `/promotions`) - pending reviews are visible inline per skill version and counted on the Overview page, but a reviewer wanting "every pending skill review across the whole registry in one list" must use `GET /v1/skill-review-requests` directly today. A small, real gap, not a silent one - worth adding if real usage shows reviewers need it.
- `ecosystem`/`updates` on the dashboard iterate every `Skill` computing impact on each request - fine at current scale (a handful of skills), not yet optimized the way `dashboard.py`'s freshness checks were concurrency-optimized in Phase 5; revisit if the skill catalog grows large enough for this to matter.
