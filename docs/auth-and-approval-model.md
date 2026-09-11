# Authorization and Approval Model

## Why this platform builds its own auth from scratch

None of the three inspected systems have any authentication or authorization. Confirmed by inspection: `ai-operations` has no middleware, no `Depends()` auth dependency, and its own `docs/09-security.md` is explicitly "Status: Not started"; `agent-eval`'s CORS config literally comments "internal tool with no auth yet"; `doc-qa` has none either. Every "who did this" field in those systems (`approved_by`, `deployed_by`, `triggered_by`) is an unauthenticated free-text string.

This platform is the first of the four to actually need real access control - it's the one making authorization and approval decisions that matter (who can promote to production, who can grant a write-capable tool). It cannot inherit an identity model from any upstream system, so it introduces one: **Identity Platform / Firebase Auth**, issuing a JWT the API verifies on every request. See [ADR-0010](adrs/0010-authorization-model.md) and [`gcp-architecture.md`](gcp-architecture.md).

A direct consequence: service-to-service calls this platform makes *to* `ai-operations` and `agent-eval` are, today, unauthenticated network calls - because those systems have nothing to authenticate against. That's a real gap in systems this platform depends on, not something this platform can fix by itself (fixing it is out of scope - see [`open-questions.md`](open-questions.md)). The platform's own auth model governs who can use *this* platform, not who those upstream systems trust.

## Roles

Four roles, global (not per-team - see below for why), matching the brief's non-goal of avoiding enterprise IAM complexity:

- **Viewer** - read-only, everywhere.
- **Builder** - creates/edits within their own team's scope; cannot approve anything.
- **Reviewer** - approves promotions and high-risk grants; still cannot approve their own requests.
- **Admin** - platform administration, plus everything Reviewer can do.

### Why global roles, not per-team roles

Per-team scoping (e.g. "Builder on AI Platform, Viewer everywhere else") was considered and rejected for MVP: with four seeded teams and a handful of users, a per-team role matrix adds real implementation complexity (role-per-(user, team) rows, scoped queries everywhere) for a distinction the current org doesn't need yet - every seeded user already has a natural single home team. `Team` ownership on `Agent`/`Skill`/`MCPServer` still constrains *which things a Builder can create/edit* (their own team's), even though the *role* itself is global. Revisit if Orion Commerce grows enough that a single global Builder role becomes too permissive - tracked in [`open-questions.md`](open-questions.md).

## Permission matrix

| Action | Viewer | Builder | Reviewer | Admin |
|---|---|---|---|---|
| View agents, versions, manifests, audit history | ✓ | ✓ | ✓ | ✓ |
| Create `Agent` | | ✓ (own team) | ✓ | ✓ |
| Create `AgentVersion` | | ✓ (own team) | ✓ | ✓ |
| Publish `SkillVersion` | | ✓ (own team) | ✓ | ✓ |
| Grant read-capable MCP tool | | ✓ (own team) | ✓ | ✓ |
| Grant write-capable / approval-required MCP tool | | request only | ✓ | ✓ |
| Revoke a capability grant | | | ✓ | ✓ |
| Request evaluation run | | ✓ (own team) | ✓ | ✓ |
| Request promotion (`candidate → production`) | | ✓ (own team) | ✓ | ✓ |
| Approve/reject a `PromotionRequest` | | | ✓* | ✓* |
| Create/edit `EvaluationPolicy` | | | | ✓ |
| Register/edit `MCPServer` / `MCPTool` | | | | ✓ |
| Manage users, teams, roles | | | | ✓ |
| Emergency retire an `AgentVersion` | | | ✓† | ✓† |

\* Never the same user who created the `PromotionRequest` - see below.
† `can_emergency_retire` exists in `app/services/permissions.py` but is not wired to any service/API action as of Phase 4 - the only way an `AgentVersion` reaches `retired` today is automatic supersession during a promotion (`app/services/promotions.py::approve_promotion`). A manual retire/abandon endpoint is a real, named gap - see [`evaluation-and-promotion.md`](evaluation-and-promotion.md)'s "Not built" note.

## No self-approval, ever

`PromotionDecision.decided_by` must not equal the corresponding `PromotionRequest.requested_by`, enforced at write time regardless of role - an Admin who requests their own promotion still cannot approve it; another Reviewer or Admin must. This closes the brief's explicit question ("can the requester approve their own production promotion?") with a hard no, not a policy convention that could be skipped under pressure.

## Grant authority scales with risk

Restated from [`mcp-governance.md`](mcp-governance.md): Builders can authorize read-only MCP tool access unilaterally; write-capable or approval-required tools require Reviewer/Admin sign-off, because that grant is what lets an agent *attempt* a write at runtime at all - the platform's one lever over blast radius before an execution-plane approval gate (which, per [`mcp-governance.md`](mcp-governance.md), may or may not be reliably enforced by the runtime itself).
