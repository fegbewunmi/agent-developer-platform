# 0001. Control plane separated from execution, evaluation, and tool-execution planes

Status: Accepted

## Context

Three real systems already exist and already do real work: `ai-operations` executes agents (LangGraph + Vertex AI), `agent-eval` executes evaluations (evaluators, datasets, regression comparison), and `ai-operations/mcp_server` executes MCP tool calls. It would be technically possible to fold governance directly into any of them, or to build a platform that proxies/reimplements their work "for convenience." The brief explicitly warns against this ("avoid turning the Developer Platform into the runtime for everything merely because centralizing everything seems convenient").

Concretely, inspection found: `ai-operations` has no per-run config/version pinning (model name/prompt are global process settings, not attributes of an investigation) - a real gap, but one this platform can close by adding metadata *next to* the runtime, not by becoming the runtime. `agent-eval` already has real evaluators, dataset snapshotting, and regression comparison logic - duplicating any of it would create two disagreeing sources of truth.

## Decision

The Agent Developer Platform owns only metadata: ownership, version definitions, capability grants, evaluation policy, lifecycle stage, promotion workflow, audit history. It never executes an agent, never computes an evaluation score, never executes an MCP tool call. It integrates with the three planes only through their existing (or newly added, on their side) APIs. Full boundary detailed in `docs/control-plane-boundaries.md`.

## Alternatives considered

- **Embed governance fields directly into `ai-operations`' own schema.** Rejected - couples a shared governance concern to one team's runtime, and doesn't generalize to the Customer Support or Release Risk agents, which don't share that runtime.
- **Proxy all evaluation and tool calls through this platform** (so it can enforce policy at the point of execution). Rejected - this is exactly the "second runtime" outcome the brief prohibits, and neither `agent-eval` nor `ai-operations/mcp_server` expose an interface designed to be proxied; it would require reverse-engineering internals, not integrating with a contract.

## Consequences

The platform can never claim it has *enforced* anything at the moment of execution - only that it has *declared* and *recorded* governance state, and that other systems are expected to honor it (most sharply visible in the MCP approval-vs-authorization distinction, `docs/mcp-governance.md`). This is an honest limitation, not a bug to fix later; closing it would require becoming the runtime, which is explicitly out of scope.
