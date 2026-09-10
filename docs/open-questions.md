# Open Questions

Design questions deliberately left unresolved rather than guessed at. Each names what would resolve it.

1. **Should `Environment` become a first-class entity?** Currently only `MCPServer.environment` needs the concept, represented as a plain field, matching how both `ai-operations` and `agent-eval` treat environment today (a string, not a modeled entity). Revisit if a real staging environment for this platform itself, or multi-environment MCP topologies, materialize.

2. **Should evidence-freshness rules relax for rollback?** A rollback (`retired → production`) is modeled as an ordinary `PromotionRequest` for an old immutable version, gated the same way as any other promotion — including fresh evaluation evidence. But the evaluation that originally justified that version may be old, and re-running it against a currently-broken production incident is awkward timing. Options: allow a rollback-specific gate exception (weakens the "gates are hard blockers" guarantee) vs. requiring a fresh run even under incident pressure (safer, slower). Leaning toward keeping gates hard even for rollback and revisiting only if Phase 6's live drill shows this is operationally painful.

3. **Should an Admin emergency-override path exist for failed gates?** Deliberately not built in this design (see [ADR-0008](adrs/0008-automated-gates-vs-human-approval.md)) — a credible "if it's in production, it passed gates" guarantee is worth more than flexibility until there's a concrete incident showing the guarantee is too rigid. If Orion Commerce hits a real case where this blocks a legitimate emergency fix, design an override that's loud (a distinct audit event type, visible everywhere) rather than a quiet bypass.

4. **Should `agent-eval` gain an async run API upstream?** This platform's Cloud Tasks wrapper around `POST /runs` (`evaluation-and-promotion.md`) exists specifically because that endpoint is synchronous by `agent-eval`'s own explicit MVP choice (its ADR-0005). The workaround is sound but adds latency and an extra moving part. Out of scope for this repo to build (non-goal: don't rebuild the Agent Evaluation Platform), but worth raising with that platform's owners as a dependency request.

5. **Should MCP server health gate new capability grants, not just surface a warning?** Current design treats availability and authorization as independent (`mcp-governance.md`) — an unhealthy server doesn't block new grants. Revisit if this proves to let ungoverned drift accumulate in practice.

6. **Should `ApprovalPolicy` become a dynamic, per-team-configurable entity?** MVP hardcodes the approval matrix in `auth-and-approval-model.md` rather than modeling it as editable data, per the brief's explicit warning against enterprise-IAM complexity. Revisit only if a second organization/tenant with genuinely different rules is a real, not hypothetical, requirement.

7. **Should roles be per-team rather than global?** See the reasoning in `auth-and-approval-model.md` — deferred because the current four-team seed org doesn't need it. Revisit at real multi-team scale.

8. **How should this platform authenticate its calls *to* `ai-operations` and `agent-eval`, given neither has any auth today?** Not something this platform can solve unilaterally (fixing their auth is out of scope). For now, calls are unauthenticated network requests, same as any other caller of those systems today — flagged here as a real, inherited risk, not silently assumed away.

9. **Does the Incident Operations MCP server's `create_ticket` confirm-gate need to become server-enforced before this platform's `requires_approval` declaration means anything operationally?** This platform's design is honest that it currently doesn't (`mcp-governance.md`) — but the gap is worth raising with `ai-operations`' owners rather than treated as permanently acceptable.

10. **Should case-level evaluation data ever be cached locally for offline/resilience reasons?** Current design always reads through to `agent-eval` for case-level detail (`control-plane-boundaries.md`) — deliberately, to avoid a second source of truth. Revisit only if `agent-eval` availability becomes an operational problem in practice.
