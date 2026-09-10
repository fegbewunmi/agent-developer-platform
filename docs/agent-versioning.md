# Agent Versioning

## The core rule

**"Production agent" means a specific immutable `AgentVersion` currently occupying the `production` stage — never a mutable `Agent` object with `status = production`.**

`Agent` is a name and an owner. `AgentVersion` is everything that determines behavior, frozen at creation. This directly answers the brief's guiding question — "what exact model, prompt/config, skill versions, and MCP tools does it use?" — with a single row lookup instead of reconstructing history from logs, env vars, or someone's memory.

## Why this needed to be a deliberate decision, not an assumption

Neither `ai-operations` nor `agent-eval` gave us this for free:

- `ai-operations` has **no per-run version concept at all**. Model name and temperature are read from a process-global `Settings` singleton at call time, independently in six different node files. There is no field anywhere that says "this investigation ran against this model/prompt/config." If this platform copied that pattern, it would have nothing to version.
- `agent-eval` does have a real `AgentVersion` table (`agent_id`, `version_label`, `config` JSONB, `description`) and treats it as immutable by convention — but `version_label` is free text with no enforced format, and there's no manifest structure, no skill/tool pinning, and no CRUD API to create one (rows are seeded via script).

So this platform's `AgentVersion` is a genuinely new capability for Orion Commerce, not a wrapper around something that already exists — which is exactly why it needs a precise, defensible definition rather than an implied one.

## What must be pinned to reproduce a version

Everything needed to answer "what exactly was this" without consulting any other system:

- `framework` (e.g. `langgraph`) and `runtime` metadata
- `model.provider`, `model.name`, `model.params` (e.g. temperature)
- `prompt` reference (a content hash or a pointer into the owning team's prompt store — this platform stores the reference, not prompt text, since prompt authoring stays with the agent's own team)
- `source_ref` — the git commit/tag the agent's code was built from
- `skills[]` — exact `SkillVersion`s, via the immutable `AgentVersionSkill` join (see [`skills-and-capabilities.md`](skills-and-capabilities.md))
- `mcp.tools[]` — the MCP tools the version was *built to use* (declared intent — see below for why this is distinct from live authorization)
- `evaluation.policy` — which `EvaluationPolicy` gates this version's promotion
- free-form `config` for framework-specific settings that don't warrant a first-class field

This is exactly the [`agent-manifest.md`](agent-manifest.md) structure, stored as the `AgentVersion.manifest` JSONB column plus a `content_hash`.

## What immutability actually means here

Once `AgentVersion.manifest` is written, no field in it may change. The **only** mutable attribute on the row is `stage` (its position in the lifecycle — see [`evaluation-and-promotion.md`](evaluation-and-promotion.md)), plus the timestamps that record stage transitions (`promoted_at`, `retired_at`). Enforced at the database level (a trigger or check rejecting any `UPDATE` that changes `manifest` or `content_hash`), not just in application code — see [ADR-0002](adrs/0002-immutable-versioned-artifacts.md).

A consequence worth stating explicitly: **`AgentCapabilityGrant` is not part of this immutability guarantee.** The manifest's `mcp.tools[]` is a frozen declaration of intent; the live grant table is the actual, revocable authorization. A grant can be revoked after the version is created — the manifest stays truthful about what the version *was built for*, while the grant table stays truthful about what it's *currently allowed to do*. See [`mcp-governance.md`](mcp-governance.md) and the capability-revocation scenario in [`failure-modes.md`](failure-modes.md).

## SkillVersion applies the same reasoning

A `Skill` (e.g. `telemetry-investigation`) is a name and an owner; a `SkillVersion` (e.g. `telemetry-investigation@2.1`) is immutable once published, with its own `input_contract`/`output_contract`/`implementation_ref`. Agents pin exact `SkillVersion`s rather than a mutable "latest" pointer, for the same reproducibility reason that drives `AgentVersion` — see [ADR-0002](adrs/0002-immutable-versioned-artifacts.md), which covers both together since the tradeoff is identical.

## What creating a new version looks like operationally

Because content is frozen, "fixing" a version is never an edit — it's creating a new `AgentVersion` (e.g. `4.2.1`) that starts back at `draft`. There is no in-place patch path anywhere in the design. This is a deliberate constraint, not an oversight: it's what makes an audit trail (`audit-model.md`) and a promotion history genuinely trustworthy — a given `AgentVersion.id` can never mean two different things at two different times.
