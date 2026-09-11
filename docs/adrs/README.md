# Architecture Decision Records

ADRs for decisions with a real tradeoff - not written mechanically for every topic the brief suggested; several naturally combined because the reasoning was shared (e.g. `AgentVersion` and `SkillVersion` immutability, or manifest storage and evaluation policy freshness). See each ADR's Context for why it exists as its own record or absorbed into another.

| # | Title | Status |
|---|---|---|
| [0001](0001-control-plane-execution-plane-separation.md) | Control plane separated from execution, evaluation, and tool-execution planes | Accepted |
| [0002](0002-immutable-versioned-artifacts.md) | Immutable AgentVersions and SkillVersions | Accepted |
| [0003](0003-manifest-representation-and-storage.md) | Manifest representation and storage | Accepted |
| [0004](0004-mcp-capability-grant-model.md) | MCP capability grant model: mutable and separate from the immutable manifest | Accepted |
| [0005](0005-agent-eval-as-external-source-of-truth.md) | Agent Evaluation Platform as external source of truth, invoked asynchronously | Accepted |
| [0006](0006-evaluation-policy-and-freshness.md) | Explicit evaluation policy/gate model with live freshness checks | Accepted |
| [0007](0007-promotion-state-machine.md) | Promotion state machine and single-production-version enforcement | Accepted |
| [0008](0008-automated-gates-vs-human-approval.md) | Automated gates are hard blockers; no override in MVP | Accepted |
| [0009](0009-no-self-approval.md) | No self-approval on promotion decisions | Accepted |
| [0010](0010-authorization-model.md) | Global RBAC with four roles, introduced fresh (no upstream identity to inherit) | Accepted |
| [0011](0011-pubsub-vs-cloud-tasks.md) | Pub/Sub for event fan-out, Cloud Tasks for durable one-shot execution | Accepted |
| [0012](0012-gcp-deployment-topology.md) | GCP deployment topology matches `ai-operations`' proven pattern | Accepted |
| [0013](0013-no-first-party-model-usage.md) | No first-party LLM/model usage in the control plane | Accepted |
| [0014](0014-capability-grant-reproducibility.md) | Capability grant reproducibility: manifest vs. authorization, evaluation-time snapshot deferred to Phase 3 | Accepted |
| [0015](0015-evaluation-policy-immutability.md) | EvaluationPolicy is fully immutable, matching AgentVersion and SkillVersion | Accepted |
| [0016](0016-agent-eval-deployment-decision.md) | Deploy Agent Evaluation Platform to Cloud Run now, as an independently owned service | Accepted |
| [0017](0017-shared-cloud-sql-instance-isolated-database.md) | agent-eval shares ai-operations' Cloud SQL instance, in an isolated database | Accepted |
| [0018](0018-promotion-request-immutability.md) | PromotionRequest captures full decision context; immutable except status | Accepted |
| [0020](0020-promotion-lifecycle-event-outbox.md) | Transactional outbox for the promotion-lifecycle Pub/Sub event | Accepted |

0007's rollback/concurrency decision and 0006's freshness decision were each amended in place for Phase 4 (see their own "Phase 4 update" sections) rather than duplicated into new records - the original decisions held, Phase 4 only had to make them concrete. 0019 was not used - amending 0007 covered that ground instead of a standalone record.

## Template

New ADRs start from [`template.md`](template.md).
