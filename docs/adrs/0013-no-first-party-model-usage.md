# 0013. No first-party LLM/model usage in the control plane

Status: Accepted

## Context

All three inspected systems call an LLM directly: `ai-operations` uses Vertex AI Gemini for its LangGraph nodes, `agent-eval` uses Vertex AI Gemini as an LLM-as-judge evaluator, `doc-qa` uses OpenAI for embeddings/synthesis. It would be easy to assume a fourth AI-adjacent platform needs its own model dependency too - e.g. for an LLM-assisted manifest reviewer, or a natural-language audit-query feature.

## Decision

This platform makes zero LLM calls. It is pure CRUD, orchestration (Cloud Tasks/Pub/Sub), and deterministic policy evaluation over data supplied by other systems. No model provider credentials, no Vertex AI dependency, no prompt engineering surface exists anywhere in its own services.

## Alternatives considered

- **An LLM-assisted feature** (e.g. summarizing a promotion's evidence in natural language, or a chat interface over audit history). Rejected for this design - nothing in the brief's required workflows needs it, and adding one would add a model dependency, cost, and latency surface to a system whose core value is being a boring, reliable, deterministic system of record. Nothing prevents a future, clearly-scoped feature request for this; it simply isn't assumed as a default the way it might be for an "AI platform" project.

## Consequences

This platform can be reasoned about, tested, and audited without any of the non-determinism that comes with LLM calls - every gate result, every permission check, every state transition is deterministic and reproducible from stored data alone. It also means this platform has no Vertex AI IAM footprint to secure, unlike the three systems it governs.
