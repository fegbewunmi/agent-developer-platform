# 0010. Global RBAC with four roles, introduced fresh

Status: Accepted

## Context

Inspection confirmed none of the three existing systems have any authentication or authorization: `ai-operations` has no auth middleware anywhere and its own `docs/09-security.md` is explicitly "Status: Not started"; `agent-eval`'s CORS config comments "internal tool with no auth yet"; `doc-qa` has none. This platform cannot inherit an identity model from any upstream system - it is the first of the four that actually needs one, since it's the one making decisions (who can promote, who can grant a write-capable tool) that matter if gotten wrong.

## Decision

Identity Platform / Firebase Auth issues a JWT verified on every API request. Four global roles - Viewer, Builder, Reviewer, Admin - with a fixed permission matrix (`docs/auth-and-approval-model.md`), not a dynamic policy engine. `Team` ownership on `Agent`/`Skill`/`MCPServer` scopes *what* a Builder can act on; the *role* itself is global rather than per-team.

## Alternatives considered

- **Per-team roles** (a user could be Builder on one team, Viewer on another). Rejected for MVP - real complexity (role-per-(user,team) rows, scoped queries everywhere) for a distinction the seeded four-team org doesn't need, since every seeded user already has one natural home team. Tracked in `docs/open-questions.md` #7 for revisit at real scale.
- **Reuse whatever identity mechanism `ai-operations` or `agent-eval` eventually adopt**, to keep a single identity provider across all Orion Commerce systems. Rejected as a blocking dependency - neither system has committed to one yet, and this platform's need is immediate; adopting Identity Platform independently doesn't preclude later federation if those systems converge on something.

## Consequences

Calls this platform makes *to* `ai-operations` and `agent-eval` remain unauthenticated network requests, because those systems have nothing to authenticate against - this platform's new auth model only governs access to itself, not trust between systems (`docs/open-questions.md` #8). A future federated identity effort across all Orion Commerce systems would need to reconcile this platform's user model with whatever those systems eventually adopt.
