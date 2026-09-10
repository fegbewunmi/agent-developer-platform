# 0002. Immutable AgentVersions and SkillVersions

Status: Accepted

## Context

Combined into one ADR because the tradeoff is identical for both entities: reproducibility requires that "version X" always means the same thing. `agent-eval` already treats its own `AgentVersion.config` as immutable by convention (never edited in place after creation) and versions its `Evaluator` rows the same way (`(key, version)` unique, new row for any meaningful change) — this platform generalizes a pattern that already exists in a sibling system rather than inventing one from nothing. `ai-operations`, by contrast, has no version concept to learn from at all — model/prompt config is global and mutable, which is precisely the failure mode immutability prevents.

## Decision

`AgentVersion` is fully immutable — every column, no exceptions, enforced at the database level by revoking `UPDATE` entirely for the application role (not just an application-level "no edit endpoint" convention, and not a trigger that allow-lists which columns may change). `SkillVersion` follows the same rule: publication is one-way, no edit endpoint. "Fixing" either always means creating a new version, never patching an existing one.

**Amendment (post-Phase-0-review):** the original version of this decision made `stage` an exception — "the only mutable field on `AgentVersion` is `stage`." Review correctly flagged that as a real tension: a table that's immutable except for its single most-frequently-changing field isn't a clean immutability guarantee, it's a guarantee with a built-in escape hatch, and every future reader would need to remember the exception. Resolved by moving `stage` off `AgentVersion` entirely, onto a new table, `AgentVersionLifecycle` (one row per version, holding `stage`/`entered_at`/`entered_by`, updated in place on each transition — see `docs/domain-model.md` and `docs/agent-versioning.md#the-stage-vs-content-split`). `AgentVersion` is now immutable with zero exceptions; lifecycle state is explicitly modeled as separate control-plane metadata *about* an immutable version, not as an attribute of the version itself. This is a genuine model correction, not a rewording — it changes the schema (a new table, a relocated constraint) and is treated as such rather than patched over in place.

## Alternatives considered

- **Application-level immutability only** (no DB enforcement, just "the API doesn't expose an edit endpoint"). Rejected — a future migration script, admin tool, or bug could silently mutate a version, breaking every downstream guarantee (manifest-in-audit-trail correctness, gate-result-to-policy linkage). A DB constraint is one line of defense that can't be accidentally bypassed by future code.
- **Mutable `AgentVersion` with a separate immutable "snapshot" taken at promotion time.** Rejected — this reintroduces exactly the ambiguity the brief warns about ("a mutable Agent object with `status=production`"), just one level down; it would mean an `AgentVersion` could look different depending on when you looked at it before promotion.

## Consequences

Every "fix" is a new row, which is the entire point — but it does mean the version count grows faster than a mutable model would, and any UI needs to make "create version 4.2.1" a fast, low-friction action rather than something that feels like a big deal, or builders will be tempted to route around it.
