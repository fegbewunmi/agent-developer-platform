# Skills and Capabilities

## Skill → SkillVersion → attached to AgentVersion

A `Skill` is a reusable capability identity (e.g. `telemetry-investigation`), owned by a team. A `SkillVersion` (e.g. `telemetry-investigation@2.1`) is one immutable, published definition of that capability, with enough metadata to understand it without reading its implementation:

- `name`, `version`, `owner` (a `User`)
- `purpose` — a short description of what it does
- `input_contract` / `output_contract` — enough to understand the interface, not a full schema registry
- `implementation_ref` — a pointer to the code/config that implements it (e.g. a git ref into the owning agent's repo, such as `ai-operations/backend/app/graph/nodes/telemetry.py`)
- `compatible_frameworks[]` — e.g. `["langgraph"]`, so an `AgentVersion` creation can reject an incompatible pin

`SkillVersion` publication is a one-way action (`skill_version.published` audit event) — there is no edit endpoint, only "publish a new version."

## Agents pin exact SkillVersions

`AgentVersionSkill(agent_version_id, skill_version_id)` is written once, at `AgentVersion` creation, and never modified afterward — it's part of what makes the version's manifest reproducible (see [`agent-versioning.md`](agent-versioning.md)). An agent does **not** dynamically resolve "whatever `telemetry-investigation` currently points to" at runtime; it resolves to the exact version pinned when it was built. This mirrors `agent-eval`'s own evaluator-versioning discipline (`Evaluator` rows are unique on `(key, version)`, never edited in place) — the same pattern, applied to skills.

## Where skills come from today

`ai-operations` doesn't have a `Skill`/`SkillVersion` concept at all — its specialist behavior (telemetry, deployment, knowledge investigation) is implemented as LangGraph nodes with hardcoded logic, not registered capabilities. Modeling the Incident Investigator's three specialists as seeded `SkillVersion`s (`telemetry-investigation@2.1`, `deployment-analysis@1.3`, `knowledge-search@3.0`) is this platform introducing the concept, not reflecting something that already existed — flagged here so it isn't mistaken for an existing integration the way the MCP tools are.

## Diagram: version-skill-capability relationship

```mermaid
flowchart TB
    subgraph Immutable["Frozen at AgentVersion creation"]
        AV["AgentVersion\nincident-investigator@4.2.0"]
        SV1["SkillVersion\ntelemetry-investigation@2.1"]
        SV2["SkillVersion\ndeployment-analysis@1.3"]
        SV3["SkillVersion\nknowledge-search@3.0"]
        AV -- "AgentVersionSkill\n(immutable pin)" --> SV1
        AV -- "AgentVersionSkill\n(immutable pin)" --> SV2
        AV -- "AgentVersionSkill\n(immutable pin)" --> SV3
    end

    subgraph Mutable["Live, revocable"]
        AV -- "AgentCapabilityGrant\n(can be revoked)" --> T1["MCPTool: get_investigation_status\n(read)"]
        AV -- "AgentCapabilityGrant\n(can be revoked)" --> T2["MCPTool: search_documents\n(read)"]
        AV -- "AgentCapabilityGrant\n(can be revoked)" --> T3["MCPTool: create_ticket\n(write, requires_approval)"]
    end
```

The two halves of this diagram have different mutability rules on purpose: skill pins are part of what a version *is* and can never change; capability grants are part of what a version is *currently allowed to do* and can change out from under it. See [`mcp-governance.md`](mcp-governance.md) and [ADR-0004](adrs/0004-mcp-capability-grant-model.md).

## Compatibility checks

At `AgentVersion` creation, each pinned `SkillVersion.compatible_frameworks[]` must include the manifest's `agent.framework`. This is a cheap, static check — not a runtime guarantee that the skill actually works, which remains the owning team's responsibility (this platform doesn't execute anything, per [`control-plane-boundaries.md`](control-plane-boundaries.md)).
