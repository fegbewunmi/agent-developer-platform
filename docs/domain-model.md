# Domain Model

This model was built by starting from the brief's proposed entity list, then testing each one against what the three inspected systems actually do. Entities that duplicated something a real system already owns were cut or reduced to a reference. See [`adrs/0002-immutable-versioned-artifacts.md`](adrs/0002-immutable-versioned-artifacts.md) and [`adrs/0004-mcp-capability-grant-model.md`](adrs/0004-mcp-capability-grant-model.md) for the reasoning behind the two trickiest parts of this model.

## Entities

### User
`id, name, email, team_id, role, created_at`
Role is one of Viewer/Builder/Reviewer/Admin (global, not per-team — see [`auth-and-approval-model.md`](auth-and-approval-model.md) for why per-team roles were considered and rejected for MVP).

### Team
`id, name, slack_channel?`
Owns agents, skills, and MCP server registrations. Mirrors the `service_ownership` pattern already used in `ai-operations` (team_name, slack_channel), reused for consistency rather than invented fresh.

### Agent
`id, name (unique), team_id, description, created_at`
The long-lived logical identity. Holds no mutable "current config" — see [`agent-versioning.md`](agent-versioning.md). Analogous to `agent-eval`'s `agents` table (`id, name, description, adapter_key`), minus `adapter_key`, which is an execution-plane concern this platform doesn't need.

### AgentVersion
`id, agent_id, version_label, manifest (jsonb), content_hash, source_ref, created_by, created_at`
One immutable build. **Every column on this table is write-once.** `manifest` is the full reproducible definition (see [`agent-manifest.md`](agent-manifest.md)); `content_hash` is a SHA-256 over the canonicalized manifest, used to detect any attempt to mutate a "created" version and to give audit events a stable content reference. No `UPDATE` grant exists on this table at all for the application role — not even to an allow-listed column — which is what makes the immutability guarantee absolute rather than conventional. Notably, **`stage` is not a column on this table** — see `AgentVersionLifecycle` below and [`agent-versioning.md`](agent-versioning.md#the-stage-vs-content-split) for why.

### AgentVersionLifecycle
`agent_version_id (PK, FK), agent_id, stage, entered_at, entered_by`
The version's **current position in the promotion lifecycle** — separate control-plane metadata *about* an `AgentVersion`, not part of its immutable content. One row per `AgentVersion`, created alongside it at `stage='draft'`, and updated in place on every legal transition (`docs/evaluation-and-promotion.md`). `agent_id` is denormalized from `AgentVersion.agent_id` purely so the single-production-version constraint can live on this table: `UNIQUE (agent_id) WHERE stage='production'`. Denormalizing it isn't an immutability concern — a version's owning `Agent` never changes, so this copy is itself write-once even though the row it lives on is mutable. Full transition history is not duplicated here; it's already captured completely by `AuditEvent` (`agent_version.promoted`, `agent_version.retired`, etc. — see [`audit-model.md`](audit-model.md)), so this table only needs to hold the current pointer, not a log.

### Skill
`id, name (unique), owner_team_id, description, created_at`
A reusable capability identity, structurally identical in spirit to Agent — same reasoning for keeping mutable metadata off of it.

### SkillVersion
`id, skill_id, version, owner_user_id, purpose, input_contract, output_contract, implementation_ref, compatible_frameworks[], created_at`
Immutable once published (`skill_version.published` audit event). `implementation_ref` points at the code/config that implements it (e.g. a git ref or a LangGraph node module path) — the platform stores the pointer, not the implementation.

### AgentVersionSkill
`agent_version_id, skill_version_id`
Join table pinning exact skill versions to a version at creation time. Immutable — set once when the `AgentVersion` is created, never edited afterward (consistent with the manifest being frozen).

### MCPServer
`id, name (unique), environment, owner_team_id, connection_ref, health_status, last_health_check_at, created_at`
`connection_ref` is a pointer (e.g. the `BACKEND_URL`-style config `ai-operations/mcp_server` already uses), not a live connection. `health_status` is one of `healthy/degraded/unavailable/unknown`, refreshed by a periodic Cloud Scheduler job (see [`gcp-architecture.md`](gcp-architecture.md)) — never inferred synchronously during a user request.

### MCPTool
`id, mcp_server_id, name, description, io_schema (jsonb), classification, requires_approval, created_at`
`classification` is `read` or `write`. Modeled directly on the Incident Operations MCP server's real tools: `get_investigation_status`, `search_documents`, `get_incident_history` (`classification=read, requires_approval=false`), `create_ticket` (`classification=write, requires_approval=true`).

### AgentCapabilityGrant
`id, agent_version_id, mcp_tool_id, granted_by, granted_at, revoked_by?, revoked_at?`
**Mutable and revocable** — deliberately not part of the immutable manifest. The manifest records what an `AgentVersion` was *built to use*; a grant records what it is *currently authorized to call*. These can diverge (e.g. a grant revoked after a security incident, independent of the version's declared intent). See the capability-revocation failure mode in [`failure-modes.md`](failure-modes.md) and [ADR-0004](adrs/0004-mcp-capability-grant-model.md).

### EvaluationPolicy
`id, name, version, required_evaluator_keys (jsonb), thresholds (jsonb), zero_new_regressions, dataset_key, created_by, created_at`
Versioned and immutable per `(name, version)`, mirroring how `agent-eval` already versions its `Evaluator` rows — same pattern, applied one level up. See [`evaluation-and-promotion.md`](evaluation-and-promotion.md) for the threshold/gate structure.

### EvaluationRunReference
`id, agent_version_id, evaluation_policy_id, external_run_id, external_agent_version_id, requested_by, requested_at, status, dataset_snapshot_hash?, evaluator_versions (jsonb)?, completed_at?, fetched_at?`
A local pointer to a run that actually executed in `agent-eval`. `external_run_id` is `agent-eval`'s `evaluation_runs.id`. `dataset_snapshot_hash` and `evaluator_versions` are copied from `agent-eval`'s response once available, for freshness comparisons. This platform never stores case-level results — those stay in `agent-eval` and are linked to, not duplicated.

### EvaluationGateResult
`id, evaluation_run_reference_id, evaluation_policy_id, criterion, expected, actual, passed, evaluated_at`
The output of applying an `EvaluationPolicy` to an `EvaluationRunReference`'s fetched results. This is what makes gates explicit and inspectable instead of a black-box "quality score" — each row is one named criterion (e.g. `grounding >= 0.85`, `zero_new_regressions`, `evaluator_versions_match_policy`).

### PromotionRequest
`id, agent_version_id, from_stage, to_stage, requested_by, requested_at, evaluation_run_reference_id?, status, reason?`
`status` is `pending/approved/rejected/withdrawn`. Concurrency-safe by design — see [`failure-modes.md`](failure-modes.md).

### PromotionDecision
`id, promotion_request_id, decision, decided_by, decided_at, comment?`
`decided_by != requested_by` is enforced at write time (no self-approval, no exceptions — see [`auth-and-approval-model.md`](auth-and-approval-model.md)).

### AuditEvent
`id, event_type, entity_type, entity_id, actor, occurred_at, payload (jsonb)`
Append-only. See [`audit-model.md`](audit-model.md) for the full event catalog and the transactional-write guarantee.

## Entities considered and rejected

- **Environment** as a first-class entity — every real system inspected (`ai-operations`, `agent-eval`) represents environment as a free-text/enum setting, not a modeled entity with its own lifecycle. `MCPServer.environment` and deployment topology docs cover this without adding a table. Revisit if a second real deployment environment (e.g. staging) actually exists — currently only `MCPServer.environment` needs the concept at all. Tracked in [`open-questions.md`](open-questions.md).
- **ApprovalPolicy** as a dynamic, configurable entity — the brief's non-goals explicitly warn against enterprise-IAM complexity. MVP hardcodes the approval matrix in code (who can approve what) rather than modeling it as data. Tracked as an open question for if/when a second org needs different rules.
- **AgentManifest** as a separate entity — folded into `AgentVersion.manifest` (a JSONB column) rather than a standalone table or object-storage artifact. See [ADR-0003](adrs/0003-manifest-representation-and-storage.md).
- **Ownership** as a separate entity — folded into `owner_team_id` / `owner_user_id` columns on `Agent`, `Skill`, and `MCPServer`. A standalone ownership table would only earn its keep if ownership needed its own history/versioning, which nothing in the brief requires.
- **EvaluationGateResult as part of EvaluationRunReference** — kept as a separate table rather than JSONB columns on the run reference, specifically so gate results survive a policy edit: a `PromotionRequest` links to the exact `EvaluationGateResult` rows that were computed against the exact `EvaluationPolicy` version live at request time, even if that policy is superseded later.
- **A separate `AgentVersionStageHistory` log table** — considered alongside `AgentVersionLifecycle`, to record every past transition, not just the current one. Rejected as redundant: `AuditEvent` already records every `agent_version.promoted`/`agent_version.retired`/etc. transition with full context (who, when, why, which evaluation evidence), so a second history table would duplicate data that's already durable and queryable elsewhere, for no new capability. `AgentVersionLifecycle` only needs to answer "what stage is this version in right now," which is a single mutable row, not a log.

## Diagram: core domain relationships

```mermaid
erDiagram
    TEAM ||--o{ USER : employs
    TEAM ||--o{ AGENT : owns
    TEAM ||--o{ SKILL : owns
    TEAM ||--o{ MCPSERVER : owns

    AGENT ||--o{ AGENTVERSION : has
    AGENTVERSION ||--|| AGENTVERSIONLIFECYCLE : "current stage (mutable, 1:1)"
    AGENTVERSION }o--o{ SKILLVERSION : "pins (AgentVersionSkill, immutable)"
    SKILL ||--o{ SKILLVERSION : has

    MCPSERVER ||--o{ MCPTOOL : exposes
    AGENTVERSION }o--o{ MCPTOOL : "authorized via AgentCapabilityGrant (mutable)"

    AGENTVERSION ||--o{ EVALUATIONRUNREFERENCE : "evaluated by"
    EVALUATIONPOLICY ||--o{ EVALUATIONRUNREFERENCE : governs
    EVALUATIONRUNREFERENCE ||--o{ EVALUATIONGATERESULT : produces
    EVALUATIONPOLICY ||--o{ EVALUATIONGATERESULT : "criteria from"

    AGENTVERSION ||--o{ PROMOTIONREQUEST : subject_of
    PROMOTIONREQUEST ||--o| PROMOTIONDECISION : resolved_by
    PROMOTIONREQUEST }o--o| EVALUATIONRUNREFERENCE : cites

    USER ||--o{ AGENTVERSION : creates
    USER ||--o{ PROMOTIONREQUEST : requests
    USER ||--o{ PROMOTIONDECISION : decides
```

Summary of the relationships that are easy to get wrong:

- `AgentVersion` → `AgentVersionLifecycle` is **content vs. control-plane state about that content**, deliberately two tables, not one column that would otherwise be the sole exception to an "every column is write-once" rule. See [`agent-versioning.md`](agent-versioning.md#the-stage-vs-content-split).
- `AgentVersion` → `Skill`/`MCPTool` is **two different relationships with two different mutability rules**: `AgentVersionSkill` (immutable, pinned at creation) vs. `AgentCapabilityGrant` (mutable, revocable at any time).
- `PromotionRequest` → `EvaluationRunReference` → `EvaluationGateResult` → `EvaluationPolicy` is a chain, not a shortcut: a promotion never reads raw evaluation numbers directly, only gate results that were computed against a specific policy version.
