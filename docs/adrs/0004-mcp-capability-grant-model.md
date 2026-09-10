# 0004. MCP capability grant model: mutable and separate from the immutable manifest

Status: Accepted

## Context

The brief requires the platform to handle "a capability is revoked after an AgentVersion was created" as a designed failure mode, not an edge case - which is in direct tension with ADR-0002's immutability guarantee if capability grants were part of the manifest. Inspection of the real Incident Operations MCP server also surfaced a sharp, concrete example of why authorization and approval can't be the same field. Precisely (see `docs/mcp-governance.md` for the full breakdown): `create_ticket`'s MCP tool function (`ai-operations/mcp_server/server.py`) has a genuine code-level check that blocks the backend call unless `confirm=True`, but nothing verifies that value reflects real human agreement - that part is prompt convention, per the calling model's compliance with the tool's docstring - and the backend `POST /v1/tickets` endpoint (`ai-operations/backend/app/api/v1/tickets.py`) has no confirmation concept at all, so any caller reaching it directly bypasses the gate entirely. `ai-operations`' own ADR-013 reaches the same conclusion. A single "this version can use this tool" flag can't represent both "the platform authorized this" and "a human must approve each call and that approval is actually enforced," and conflating them would misrepresent what the platform actually guarantees.

## Decision

Two separate concepts: the manifest's `mcp.tools[]` is an immutable, frozen declaration of *intent* (what the version was built to use, for reproducibility and audit). `AgentCapabilityGrant` is a separate, mutable, revocable table recording *current, live authorization* - independent of the version's lifecycle stage, revocable by a Reviewer/Admin at any time, including after production promotion. `MCPTool.requires_approval` is a third, distinct concept: a governance declaration about runtime behavior the platform expects but cannot enforce, since it doesn't sit in the execution path (ADR-0001).

## Alternatives considered

- **Fold capability grants into the manifest, versioned like everything else** (revoking means creating a new `AgentVersion`). Rejected - this would force a full new immutable version for a pure security/access change, which is both operationally slow (blocking on a rebuild for a revocation) and semantically wrong (revoking access doesn't change what the version *is*, only what it's *currently allowed to do*).
- **Treat `requires_approval` as something this platform enforces directly** (e.g. by proxying calls). Rejected per ADR-0001 - the platform doesn't sit in the execution path, and pretending otherwise would misrepresent two real, currently-unenforced gaps in `ai-operations`' own MCP integration (the docstring-only confirm decision, and the ungated backend endpoint) as if either were solved.

## Consequences

A grant can be revoked after a version reaches production without creating a new version - which is exactly what's needed operationally, but means "what a version's manifest says it uses" and "what it's currently authorized to use" can diverge, and any consumer of this platform's data (including a future execution-plane integration) must be told explicitly to check live grants, not the manifest, before trusting an authorization. Documented prominently in `docs/agent-manifest.md` and `docs/mcp-governance.md` specifically because it's an easy mistake to make.
