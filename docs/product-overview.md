# Product Overview

## The problem

Orion Commerce has multiple engineering teams building AI agents on different frameworks (LangGraph today, potentially others later), different models, different skill libraries, and different MCP tool integrations. Each team can answer "does my agent work" for itself, but nobody can answer organization-wide questions like:

- Which agent version is currently in production?
- What exact model, prompt, skill versions, and MCP tools does it use?
- Who owns it, and who approved it for production?
- What evaluation evidence supported that promotion? Did it contain regressions?
- Which evaluation policy was used, and has the policy or dataset changed since?
- Which MCP tools can this agent access, and which of those perform writes?
- Which tool calls require human approval before they execute?
- What changed between this version and the previous production version?

Today these answers live in scattered places: environment variables, hardcoded prompt strings, Slack threads, a Cloud Run deploy command someone remembers. The Incident Investigation Platform's own research (see its `docs/`) shows this concretely - model name and prompts are process-global settings, not attributes of a specific investigation, and there is no record of what configuration produced a given run.

## What the platform is

**Orion Agent Developer Platform is an agent control plane.** It owns metadata, ownership, version definitions, capability grants, evaluation policy, lifecycle state, promotion workflow, and audit history for agents built by Orion Commerce teams. It does not own agent execution, evaluation execution, or MCP tool execution - those remain the responsibility of the systems that already do them. See [`control-plane-boundaries.md`](control-plane-boundaries.md).

The core lifecycle the platform manages:

```
create agent → create immutable version → attach capabilities → evaluate → inspect regressions → request promotion → human review → promote → audit
```

## Who uses it

Four roles, detailed in [`auth-and-approval-model.md`](auth-and-approval-model.md):

- **Viewer** - read-only access across the platform (e.g. an SRE checking what's in production during an incident).
- **Builder** - creates agents, versions, skills; attaches capabilities; requests evaluations and promotions.
- **Reviewer** - approves or rejects promotion requests and grants of write-capable/approval-required MCP tools.
- **Admin** - platform administration: evaluation policies, MCP registry, users/teams, emergency retirement.

## Orion Commerce sample organization

Seed data used consistently across docs, diagrams, and (later) the actual database seed script. **Only the Incident Investigator is a real runtime integration.** The Customer Support Agent and Release Risk Agent are representative platform data - realistic enough to exercise every workflow, but their "runtimes" are not real systems this platform calls. Every surface that displays them must visibly label them as seeded/representative, not live.

### Teams

| Team | Focus |
|---|---|
| AI Platform | Builds and owns shared agent infrastructure, the Incident Investigator, and skill libraries |
| Site Reliability Engineering | Consumes the Incident Investigator; owns incident-response MCP tooling |
| Customer Support Engineering | Owns the (seeded) Customer Support Agent |
| Developer Productivity | Owns the (seeded) Release Risk Agent and CI/CD-adjacent tooling |

### Users

| User | Team | Role |
|---|---|---|
| Maya Chen | AI Platform | Builder |
| Jordan Brooks | Site Reliability Engineering | Reviewer |
| Priya Shah | Customer Support Engineering | Reviewer |
| Alex Rivera | AI Platform | Admin |

### Agents

**Incident Investigator** - real integration. LangGraph, Vertex AI Gemini 2.5 Flash, telemetry/deployment/knowledge investigation specialists, Incident Operations MCP (`get_investigation_status`, `search_documents`, `get_incident_history`, `create_ticket`), and Agent Evaluation Platform integration (agent-eval's own `incident-investigator` fixtures at `docs/06-data-model.md`/`docs/eval` in `ai-operations`). Owned by AI Platform.

**Customer Support Agent** - seeded, representative. RAG over customer knowledge, customer lookup, order status, refund workflows. Refund issuance is modeled as a write-capable, approval-required MCP tool to exercise the governance model realistically. Owned by Customer Support Engineering.

**Release Risk Agent** - seeded, representative. Deployment analysis, repository/change metadata, CI/CD signal ingestion, release-risk recommendations. Owned by Developer Productivity.

## Evaluated and excluded: doc-qa

The Document Q&A platform (`/Users/ski/doc-qa`) was inspected as a candidate integration (per the brief's "where relevant" instruction) and excluded. It is a local-only, single-user, unauthenticated, unversioned single-document RAG demo with two plain REST endpoints (`POST /upload`, `POST /query`) and no MCP or programmatic-caller-facing interface. It has no agent identity, no environment promotion, and nothing to govern, register, or promote. Its one reusable idea - a per-claim LLM-judge faithfulness check - is noted as a technique reference in [`evaluation-and-promotion.md`](evaluation-and-promotion.md), not as an integration.

## What the platform is not

- Not a place agents run. See [`control-plane-boundaries.md`](control-plane-boundaries.md).
- Not a second evaluation system. Agent Evaluation Platform remains the only place evaluators, datasets, and regression comparisons live.
- Not a second MCP implementation. MCP servers register their tools here; the platform never proxies or re-implements tool execution.
- Not enterprise IAM. Four roles, one hardcoded permission matrix, no dynamic policy engine.
