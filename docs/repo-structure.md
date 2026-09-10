# Repo Structure

Planned layout for implementation phases, matching the sibling projects' shape (`ai-operations`, `agent-eval`) so contributors moving between repos find familiar structure.

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
│   ├── evaluation-and-promotion.md
│   ├── auth-and-approval-model.md
│   ├── audit-model.md
│   ├── gcp-architecture.md
│   ├── failure-modes.md
│   ├── repo-structure.md
│   ├── roadmap.md
│   ├── open-questions.md
│   ├── phase-notes/            # one file per completed implementation phase
│   └── adrs/
│       ├── README.md
│       ├── template.md
│       └── 0001-...-0013-...
├── backend/                    # FastAPI control-plane API
│   ├── app/
│   │   ├── api/                # route handlers, one module per resource
│   │   ├── models/              # SQLAlchemy models (mirrors domain-model.md)
│   │   ├── services/            # gate evaluation, promotion transitions, manifest validation
│   │   ├── integrations/        # agent-eval client, ai-operations client, MCP health checks
│   │   ├── events/               # Pub/Sub publishers, Cloud Tasks handlers
│   │   └── main.py
│   ├── migrations/              # Alembic
│   └── tests/
├── frontend/                    # Next.js developer-facing UI
│   ├── app/
│   └── ...
├── infra/                       # Cloud Run service configs, Cloud SQL, Terraform or gcloud scripts
├── scripts/
│   └── seed_orion_commerce.py   # seeds the sample org from product-overview.md
└── .mcp.json                    # if this repo's own tooling needs MCP access, e.g. to query ai-operations
```

`backend/app/integrations/` is the one directory that deliberately knows about the shape of `ai-operations` and `agent-eval`'s real APIs — isolated there specifically so the rest of the codebase depends on this platform's own domain types, not on upstream response shapes, per [`control-plane-boundaries.md`](control-plane-boundaries.md).
