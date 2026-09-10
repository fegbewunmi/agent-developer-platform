# 0017. agent-eval shares ai-operations' Cloud SQL instance, in an isolated database

Status: Accepted

## Context

`agent-eval` needs a Postgres database reachable from Cloud Run. A new, dedicated Cloud SQL instance is real, non-trivial recurring cost (a `db-g1-small` instance runs continuously regardless of load, unlike Cloud Run which scales to zero). The existing `ai-ops-db` instance (owned by `ai-operations`, already running) had spare capacity for a second, small, structurally unrelated database.

## Decision

Created a new logical database (`agent_eval`) and a new, separate database user (`agent_eval_app`) on the existing `ai-ops-db` Cloud SQL instance - no new instance provisioned. `agent-eval`'s tables live in `agent_eval`, never in `ai_ops`; no table, schema, or row is shared between the two services' data.

**A real Cloud SQL Postgres limitation discovered during setup, and how it's actually handled:** any user created via `gcloud sql users create` on a Postgres instance is automatically added to the `cloudsqlsuperuser` role, which bypasses ordinary database-level `REVOKE CONNECT` - confirmed live: `REVOKE CONNECT ON DATABASE ai_ops FROM agent_eval_app` executed successfully but did **not** prevent `agent_eval_app` from connecting to `ai_ops`. The isolation that actually holds is **object-level**, not connection-level: `agent_eval_app` was never granted `SELECT`/`INSERT`/`UPDATE`/`DELETE` on any table in `ai_ops`, so while it can open a connection to that database, every query against `ai_ops`'s tables returns `permission denied` - verified live (`\dt` lists table names; `SELECT * FROM investigations` fails with `permission denied for table investigations`). This is a real, verified isolation guarantee, precisely characterized rather than assumed from the (misleading) intent of the `REVOKE CONNECT` statement.

## Alternatives considered

- **A dedicated Cloud SQL instance for `agent-eval`.** Rejected - real, continuous cost for a service whose actual data volume (a handful of agents/datasets/evaluators/runs) doesn't need dedicated instance-level resources; the shared-instance-isolated-database pattern gives genuine data isolation (proven above) without the added cost.
- **A shared database with agent-eval and ai-operations tables side by side, distinguished by naming convention.** Rejected outright - this is exactly the kind of implicit, convention-only boundary that erodes over time; a separate database name is a hard boundary a careless migration or query can't accidentally cross.

## Consequences

Both services' data lives on the same physical Cloud SQL instance, which means an instance-level outage or maintenance window affects both simultaneously - a real, accepted coupling, distinct from and narrower than a data or schema coupling. If `agent-eval`'s data volume or availability requirements ever diverge meaningfully from `ai-operations`', revisit toward a dedicated instance; nothing about the current schema or connection design would need to change to make that split later, since the isolation boundary (separate database, separate user, no shared grants) is already exactly where a future physical split would want it.
