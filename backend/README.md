# Agent Developer Platform - backend

FastAPI + SQLAlchemy (async) + Alembic control-plane API. See `../docs/` for the architecture this implements - this README is setup/operational only.

## Local setup

Requires a local Postgres 17 (matches `agent-eval`'s pinned version). Create the dev/test databases and the restricted runtime role once:

```sql
CREATE DATABASE agent_dev_platform_dev;
CREATE DATABASE agent_dev_platform_test;
CREATE ROLE agent_platform_app LOGIN PASSWORD 'agent_platform_app_dev';
GRANT CONNECT ON DATABASE agent_dev_platform_dev TO agent_platform_app;
GRANT CONNECT ON DATABASE agent_dev_platform_test TO agent_platform_app;
```

Install dependencies and run migrations:

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
source .venv/bin/activate
alembic upgrade head
```

`app/config.py` has working defaults for all of the above against `127.0.0.1:5432`; override via env vars or a `.env` file for anything different.

## Why two DB roles

Alembic migrations run as your privileged Postgres user (`DATABASE_URL_MIGRATIONS`). The running application connects only as `agent_platform_app` (`DATABASE_URL`) - a role that was never granted `UPDATE`/`DELETE` on `agent_versions`, `skill_versions`, or `audit_events` (migration `0008_immutability_roles.py`). This is what makes those tables' immutability a real database guarantee rather than an API convention - see `docs/adrs/0002-immutable-versioned-artifacts.md`.

## Running tests

```bash
alembic upgrade head  # against agent_dev_platform_test - see tests/conftest.py's DATABASE_URL_MIGRATIONS override
pytest -v
```

Tests connect directly as `agent_platform_app` in several places (`tests/test_immutability.py`) specifically to prove the DB-level restrictions hold for the exact role the application uses - not a superuser standing in for it.

## Running the API

```bash
uvicorn app.main:app --reload
```

Auth is real JWT verification (`app/auth/`) against Identity Platform's JWKS in production; there is no way to hit a protected endpoint without a validly signed token. See `docs/auth-and-approval-model.md`.

## Seeding the Orion Commerce sample org

```bash
python ../scripts/seed_orion_commerce.py
```

Idempotent - safe to re-run.
