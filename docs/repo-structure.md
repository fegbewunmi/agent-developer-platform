# Repo Structure

Matches the sibling projects' shape (`ai-operations`, `agent-eval`) so contributors moving between repos find familiar structure. As of Phase 2, everything through `backend/app/services/` and `backend/app/api/` is real, not planned - `frontend/`, `infra/`, and `backend/app/integrations/`/`events/` remain Phase 3+ and are marked below.

```
agent-dev-platform/
├── README.md
├── docs/
│   ├── product-overview.md
│   ├── architecture.md
│   ├── domain-model.md
│   ├── control-plane-boundaries.md
│   ├── agent-versioning.md
│   ├── agent-manifest.md
│   ├── skills-and-capabilities.md
│   ├── mcp-governance.md
│   ├── api-reference.md
│   ├── evaluation-and-promotion.md
│   ├── auth-and-approval-model.md
│   ├── audit-model.md
│   ├── gcp-architecture.md
│   ├── failure-modes.md
│   ├── repo-structure.md
│   ├── roadmap.md
│   ├── open-questions.md
│   ├── phase-notes/            # phase-1.md, phase-2.md, ... one per completed phase
│   └── adrs/
│       ├── README.md
│       ├── template.md
│       └── 0001-...-0014-...
├── backend/                    # FastAPI control-plane API (real, Phase 1-2)
│   ├── app/
│   │   ├── api/                # route handlers, one module per resource
│   │   ├── auth/                # JWT/JWKS verification, get_current_user dependency
│   │   ├── db/                  # engine/session, declarative Base
│   │   ├── models/              # SQLAlchemy models (mirrors domain-model.md) + shared column types
│   │   ├── services/            # permission checks, manifest resolution, audit, registries - the actual policy
│   │   ├── integrations/        # PLANNED (Phase 3+): agent-eval client
│   │   ├── events/              # PLANNED (Phase 4+): Pub/Sub publishers, Cloud Tasks handlers
│   │   └── main.py
│   ├── migrations/              # Alembic, one migration per entity group + one for DB-level immutability grants
│   └── tests/
├── frontend/                    # PLANNED (Phase 5): Next.js developer-facing UI
├── infra/                       # PLANNED (Phase 6): Cloud Run service configs, Cloud SQL, deployment scripts
├── scripts/
│   └── seed_orion_commerce.py   # seeds the sample org (docs/product-overview.md) through the real service layer
└── .gitignore
```

`backend/app/services/` is where the actual governance logic lives - permission checks (`permissions.py`), manifest validation/resolution (`manifest.py`), and every write path (`agents.py`, `skills.py`, `mcp.py`, `capability_grants.py`), each composing a transactional audit-event write (`audit.py`) into the same unit of work as its domain change. API routers (`app/api/`) are thin: parse the request, call a service function, translate the result or a `DomainError` (`app/services/errors.py`) into a response. This split is what keeps the service layer testable without a running API (see `tests/test_permissions.py`, `tests/test_audit_transaction.py`) and is where `backend/app/integrations/` will plug in once Phase 3 needs to call `agent-eval` - isolated there specifically so the rest of the codebase depends on this platform's own domain types, not on upstream response shapes, per [`control-plane-boundaries.md`](control-plane-boundaries.md).
