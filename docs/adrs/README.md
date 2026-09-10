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

## Template

New ADRs start from [`template.md`](template.md).
