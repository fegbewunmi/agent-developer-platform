# 0002. Immutable AgentVersions and SkillVersions

Status: Accepted

## Context

Combined into one ADR because the tradeoff is identical for both entities: reproducibility requires that "version X" always means the same thing. `agent-eval` already treats its own `AgentVersion.config` as immutable by convention (never edited in place after creation) and versions its `Evaluator` rows the same way (`(key, version)` unique, new row for any meaningful change) — this platform generalizes a pattern that already exists in a sibling system rather than inventing one from nothing. `ai-operations`, by contrast, has no version concept to learn from at all — model/prompt config is global and mutable, which is precisely the failure mode immutability prevents.

## Decision

`AgentVersion.manifest` and `content_hash` are write-once, enforced at the database level (not just application code) — no UPDATE path exists that can change them. The only mutable field on `AgentVersion` is `stage` (and its transition timestamps). `SkillVersion` follows the same rule: publication is one-way, no edit endpoint. "Fixing" either always means creating a new version, never patching an existing one.

## Alternatives considered

- **Application-level immutability only** (no DB enforcement, just "the API doesn't expose an edit endpoint"). Rejected — a future migration script, admin tool, or bug could silently mutate a version, breaking every downstream guarantee (manifest-in-audit-trail correctness, gate-result-to-policy linkage). A DB constraint is one line of defense that can't be accidentally bypassed by future code.
- **Mutable `AgentVersion` with a separate immutable "snapshot" taken at promotion time.** Rejected — this reintroduces exactly the ambiguity the brief warns about ("a mutable Agent object with `status=production`"), just one level down; it would mean an `AgentVersion` could look different depending on when you looked at it before promotion.

## Consequences

Every "fix" is a new row, which is the entire point — but it does mean the version count grows faster than a mutable model would, and any UI needs to make "create version 4.2.1" a fast, low-friction action rather than something that feels like a big deal, or builders will be tempted to route around it.
