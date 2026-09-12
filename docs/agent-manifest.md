# Agent Manifest

The manifest is the serialized form of everything [`agent-versioning.md`](agent-versioning.md) says must be pinned. It is stored as the `AgentVersion.manifest` JSONB column (see [ADR-0003](adrs/0003-manifest-representation-and-storage.md) for why JSONB-in-Postgres rather than Cloud Storage or a dedicated format).

## Format

YAML is the human-facing representation (shown in the UI, accepted on version creation); it is parsed and stored as JSONB, with a `content_hash` (SHA-256 over the canonicalized JSON) computed at write time.

```yaml
agent:
  name: incident-investigator
  version: 4.2.0
  framework: langgraph
  runtime:
    entrypoint: backend.app.graph.graph:build_graph

model:
  provider: vertex-ai
  name: gemini-2.5-flash
  params:
    temperature: 0.1

prompt:
  ref: sha256:1f3a9c...        # content hash of the system prompt, owned by the agent's team
  source: ai-operations/backend/app/graph/nodes/planner.py

source:
  git_ref: ai-operations@a1b2c3d

skills:
  - telemetry-investigation@2.1
  - deployment-analysis@1.3
  - knowledge-search@3.0

mcp:
  servers:
    - incident-operations
  tools:
    - get_investigation_status
    - search_documents
    - create_ticket

evaluation:
  policy: incident-production-v3

promotion:
  requires_human_approval: true

config:
  max_iterations: 12
  max_tool_calls: 40
  confidence_threshold: 0.80
```

## Design choices, and what was rejected

**Considered:** a dedicated binary/protobuf manifest format for stricter schema enforcement. **Rejected:** none of the three inspected systems use anything like this (all are JSON/YAML-over-HTTP shops), and it would add a compile/codegen step for no benefit at this scale - a JSON Schema validated at write time gets the same safety with far less machinery.

**Considered:** storing the manifest in Cloud Storage as an immutable object, with the DB holding only a pointer. **Rejected for now** - manifests are small (a few KB of structured config), and Postgres JSONB already gives transactional writes, indexing (e.g. querying "which versions use skill X"), and audit-event correlation in the same transaction as the version-creation row, which a separate object store would complicate without a clear benefit at current scale. Revisit if manifests grow to include large embedded artifacts (they shouldn't - see below). See [ADR-0003](adrs/0003-manifest-representation-and-storage.md).

**`mcp.tools[]` is declared intent, not live authorization.** The manifest says what the version was built to use. The actual, revocable, currently-enforced permission is the separate `AgentCapabilityGrant` table. See [`mcp-governance.md`](mcp-governance.md). This is the single most important thing to get right when reading a manifest - never treat `mcp.tools[]` as proof an agent can currently call a tool.

**`prompt.ref` is a hash/pointer, not embedded prompt text.** Prompt authoring and storage remain the owning team's responsibility (in `ai-operations`, prompts are hardcoded Python string constants per node). Embedding full prompt text in the manifest would make this platform a second source of truth for prompt content, which [`control-plane-boundaries.md`](control-plane-boundaries.md) rules out. The manifest is enough to prove *which* prompt version was used, not to reproduce its content.

**`source.git_ref` was decorative until Phase 8, now validated for CI-integrated agents.** Through Phase 7, nothing checked this field against anything real - a human typing an `AgentVersion` into a form could put any string here. Phase 8 (ADR-0023, ADR-0024, `docs/phase-notes/phase-8.md`) added a parallel, separate `AgentVersion.provenance` column: real `git_repo`/`git_commit_sha`/`git_ref`/`image_digest` supplied by a verified CI machine identity, not by the manifest author. An `Agent` with `requires_ci_provenance=True` rejects manual `AgentVersion` creation outright, so for those agents `source.git_ref` and the enforced `provenance` block describe the same real commit by construction. For every other agent, `source.git_ref` remains exactly what it always was: a convention, not a proof.

## Validation at creation time

`POST` to create an `AgentVersion` validates the manifest against a JSON Schema before accepting it: required top-level keys (`agent`, `model`, `skills`, `mcp`, `evaluation`), every `skills[]` entry must resolve to an existing, published `SkillVersion`, every `mcp.tools[]` entry must resolve to an existing `MCPTool`, and `evaluation.policy` must resolve to an existing `EvaluationPolicy`. A manifest that references anything nonexistent is rejected outright - the platform never stores a manifest it can't fully resolve.
