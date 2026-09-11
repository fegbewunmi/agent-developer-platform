# Repo Structure

Matches the sibling projects' shape (`ai-operations`, `agent-eval`) so contributors moving between repos find familiar structure. As of Phase 5, everything except `infra/` is real, not planned.

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
│   ├── frontend-architecture.md
│   ├── gcp-architecture.md
│   ├── failure-modes.md
│   ├── repo-structure.md
│   ├── roadmap.md
│   ├── open-questions.md
│   ├── phase-notes/            # phase-1.md, phase-2.md, ... one per completed phase
│   └── adrs/
│       ├── README.md
│       ├── template.md
│       └── 0001-...-0020-...
├── backend/                    # FastAPI control-plane API (real)
│   ├── app/
│   │   ├── api/                # route handlers, one module per resource
│   │   ├── auth/                # JWT/JWKS verification, get_current_user dependency, dev-login token minting
│   │   ├── db/                  # engine/session, declarative Base
│   │   ├── models/              # SQLAlchemy models (mirrors domain-model.md) + shared column types
│   │   ├── services/            # permission checks, manifest resolution, audit, registries - the actual policy
│   │   ├── integrations/        # agent-eval client
│   │   └── main.py
│   ├── migrations/              # Alembic, one migration per entity group + one for DB-level immutability grants
│   └── tests/
├── frontend/                    # Next.js (App Router) developer-facing UI (real, Phase 5)
│   ├── app/                     # pages (Server Components), Route Handlers (auth, proxy)
│   │   ├── overview/             # dashboard
│   │   ├── agents/[agentId]/versions/[versionId]/  # the core reproducibility surface
│   │   ├── skills/, mcp/, promotions/, activity/, login/
│   │   └── api/auth/, api/proxy/[...path]/  # Route Handlers - see docs/frontend-architecture.md
│   ├── components/              # shared display components (badges, layout, activity feed)
│   └── lib/                     # api.ts (server-only fetch wrapper), auth.ts, permissions.ts, types.ts
├── infra/                       # PLANNED (Phase 6): Cloud Run service configs, Cloud SQL, deployment scripts
├── scripts/
│   ├── seed_orion_commerce.py   # seeds the sample org (docs/product-overview.md) through the real service layer
│   └── dev_login.py             # CLI dev-token minting (frontend/backend share the same signing logic)
└── .gitignore
```

`backend/app/services/` is where the actual governance logic lives - permission checks (`permissions.py`), manifest validation/resolution (`manifest.py`), and every write path (`agents.py`, `skills.py`, `mcp.py`, `capability_grants.py`, `promotions.py`), each composing a transactional audit-event write (`audit.py`) into the same unit of work as its domain change. API routers (`app/api/`) are thin: parse the request, call a service function, translate the result or a `DomainError` (`app/services/errors.py`) into a response. This split is what keeps the service layer testable without a running API (see `tests/test_permissions.py`, `tests/test_audit_transaction.py`) and is where `backend/app/integrations/` plugs in for calling `agent-eval` - isolated there specifically so the rest of the codebase depends on this platform's own domain types, not on upstream response shapes, per [`control-plane-boundaries.md`](control-plane-boundaries.md).

`frontend/` never talks to the backend from the browser - see [`frontend-architecture.md`](frontend-architecture.md) for the full request-flow diagram. Server Components and Server Actions call the backend directly over the network (server-to-server, no CORS needed); client components that need interactivity go through `app/api/proxy/[...path]/route.ts`, a same-origin proxy that attaches the real JWT from an httpOnly cookie server-side. The frontend does not duplicate any backend domain logic - permission checks in `lib/permissions.ts` mirror the backend's `app/services/permissions.py` purely to decide what to *show*, never as the actual authorization boundary.
