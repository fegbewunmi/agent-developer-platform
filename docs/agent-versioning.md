# Agent Versioning

## The core rule

**"Production agent" means a specific immutable `AgentVersion` whose `AgentVersionLifecycle.stage` is currently `production` - never a mutable `Agent` object with `status = production`, and never a mutable `stage` field living on the immutable version row itself.** See [The stage vs. content split](#the-stage-vs-content-split) below for why lifecycle state is deliberately a separate table.

`Agent` is a name and an owner. `AgentVersion` is everything that determines behavior, frozen at creation. This directly answers the brief's guiding question - "what exact model, prompt/config, skill versions, and MCP tools does it use?" - with a single row lookup instead of reconstructing history from logs, env vars, or someone's memory.

## Why this needed to be a deliberate decision, not an assumption

Neither `ai-operations` nor `agent-eval` gave us this for free:

- `ai-operations` has **no per-run version concept at all**. Model name and temperature are read from a process-global `Settings` singleton at call time, independently in six different node files. There is no field anywhere that says "this investigation ran against this model/prompt/config." If this platform copied that pattern, it would have nothing to version.
- `agent-eval` does have a real `AgentVersion` table (`agent_id`, `version_label`, `config` JSONB, `description`) and treats it as immutable by convention - but `version_label` is free text with no enforced format, and there's no manifest structure, no skill/tool pinning, and no CRUD API to create one (rows are seeded via script).

So this platform's `AgentVersion` is a genuinely new capability for Orion Commerce, not a wrapper around something that already exists - which is exactly why it needs a precise, defensible definition rather than an implied one.

## What must be pinned to reproduce a version

Everything needed to answer "what exactly was this" without consulting any other system:

- `framework` (e.g. `langgraph`) and `runtime` metadata
- `model.provider`, `model.name`, `model.params` (e.g. temperature)
- `prompt` reference (a content hash or a pointer into the owning team's prompt store - this platform stores the reference, not prompt text, since prompt authoring stays with the agent's own team)
- `source_ref` - the git commit/tag the agent's code was built from
- `skills[]` - exact `SkillVersion`s, via the immutable `AgentVersionSkill` join (see [`skills-and-capabilities.md`](skills-and-capabilities.md))
- `mcp.tools[]` - the MCP tools the version was *built to use* (declared intent - see below for why this is distinct from live authorization)
- `evaluation.policy` - which `EvaluationPolicy` gates this version's promotion
- free-form `config` for framework-specific settings that don't warrant a first-class field

This is exactly the [`agent-manifest.md`](agent-manifest.md) structure, stored as the `AgentVersion.manifest` JSONB column plus a `content_hash`.

## What immutability actually means here

Once `AgentVersion.manifest` is written, **nothing on the `AgentVersion` row ever changes** - not one field, not a timestamp, nothing. This is stronger than "manifest is frozen, one field is exempt": it's an unconditional rule, enforced at the database level by revoking `UPDATE` entirely for the application role on that table, not by a trigger that allow-lists which columns may change. An unconditional rule is easier to reason about and impossible to accidentally weaken later by adding "just one more" mutable column. See [ADR-0002](adrs/0002-immutable-versioned-artifacts.md).

## The stage vs. content split

Lifecycle stage - `draft`/`evaluating`/`candidate`/`production`/`retired` - is genuinely mutable: a version *will* move through these over its life, and that's the entire point of the promotion lifecycle in [`evaluation-and-promotion.md`](evaluation-and-promotion.md). Putting a mutable `stage` column directly on `AgentVersion`, as Phase 0's first draft of this doc did, would have made "immutable" mean "immutable except for the one field that changes the most" - a real tension worth resolving deliberately rather than leaving implicit.

**Resolution: stage is not part of the version's identity at all - it's control-plane metadata *about* the version, tracked in a separate table, `AgentVersionLifecycle`** (`agent_version_id, agent_id, stage, entered_at, entered_by` - one row per `AgentVersion`, updated in place on each transition; full schema in [`domain-model.md`](domain-model.md)). This mirrors a distinction worth naming explicitly: **`AgentVersion` answers "what is this build," and `AgentVersionLifecycle` answers "where is this build allowed to run right now."** The first question has exactly one true answer forever. The second has an answer that legitimately changes.

**Why stage transitions never compromise reproducibility.** Reproducibility is a property of `AgentVersion.manifest` alone - the model, prompt reference, skill pins, and declared MCP tools. None of that is touched by a stage transition; `AgentVersionLifecycle.stage` moving from `candidate` to `production` doesn't read, write, or reference `manifest` at all, it's a different row in a different table pointing at the same immutable `AgentVersion.id`. Two engineers asking "what does `incident-investigator@4.2.0` consist of" at any two points in its life - the moment it was created, or a year after it was retired - get byte-identical answers from `AgentVersion`, regardless of how many times `AgentVersionLifecycle` changed in between. The single-production-version constraint (`UNIQUE (agent_id) WHERE stage='production'`) lives on `AgentVersionLifecycle`, not `AgentVersion`, for the same reason: it's a constraint about current control-plane state, not about content.

A consequence worth stating explicitly: **`AgentCapabilityGrant` follows the identical pattern, one layer over.** The manifest's `mcp.tools[]` is a frozen declaration of intent; the live grant table is the actual, revocable authorization - a second example of "immutable content" and "mutable control-plane state about that content" being deliberately separate tables rather than one row trying to be both. See [`mcp-governance.md`](mcp-governance.md) and the capability-revocation scenario in [`failure-modes.md`](failure-modes.md).

## SkillVersion applies the same reasoning

A `Skill` (e.g. `telemetry-investigation`) is a name and an owner; a `SkillVersion` (e.g. `telemetry-investigation@2.1`) is immutable once published, with its own `input_contract`/`output_contract`/`implementation_ref`. Agents pin exact `SkillVersion`s rather than a mutable "latest" pointer, for the same reproducibility reason that drives `AgentVersion` - see [ADR-0002](adrs/0002-immutable-versioned-artifacts.md), which covers both together since the tradeoff is identical.

## What creating a new version looks like operationally

Because content is frozen, "fixing" a version is never an edit - it's creating a new `AgentVersion` (e.g. `4.2.1`) with a fresh `AgentVersionLifecycle` row starting at `draft`. There is no in-place patch path anywhere in the design. This is a deliberate constraint, not an oversight: it's what makes an audit trail (`audit-model.md`) and a promotion history genuinely trustworthy - a given `AgentVersion.id` can never mean two different things at two different times.
