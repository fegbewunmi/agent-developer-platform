# 0003. Manifest representation and storage

Status: Accepted

## Context

The manifest (`docs/agent-manifest.md`) is the reproducible definition of an `AgentVersion` — model, prompt reference, skills, MCP tools, evaluation policy, config. It needs to be queryable (e.g. "which versions use skill X"), transactionally consistent with the row that owns it, and human-editable/reviewable as YAML in the UI.

## Decision

Store as YAML at the API boundary (author/display format), parsed and persisted as JSONB in the same Postgres row as `AgentVersion` (`manifest` column), with a `content_hash` (SHA-256 over canonicalized JSON) computed at write time. Validated against a JSON Schema before acceptance — every `skills[]`/`mcp.tools[]`/`evaluation.policy` reference must resolve to an existing row, or the write is rejected outright.

## Alternatives considered

- **Cloud Storage object per manifest, DB holds a pointer.** Rejected for current scale — manifests are a few KB of structured config, not large artifacts; object storage would separate the manifest from the transaction that creates the version (the write-once guarantee in ADR-0002 gets harder to enforce across two systems), and would complicate the "query which versions use skill X" case for no offsetting benefit. Revisit only if manifests grow to embed large content, which the design deliberately avoids (prompt text and implementation code stay as external references, not embedded content — see `docs/agent-manifest.md`).
- **A dedicated binary/protobuf manifest schema.** Rejected — none of the three inspected systems use anything beyond JSON/YAML-over-HTTP; adding codegen machinery buys schema strictness this JSON-Schema-at-write-time approach already gets more cheaply.

## Consequences

Manifest queries (e.g. "list versions using skill X@2.1") are ordinary JSONB/relational queries via the `AgentVersionSkill` join table, not a document-store scan — cheap and consistent with the rest of the schema. If a future requirement genuinely needs large embedded artifacts per version, this decision will need revisiting alongside a real use case, not preemptively.
