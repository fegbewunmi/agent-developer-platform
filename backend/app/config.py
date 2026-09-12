from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # Runtime DB connection - the restricted `agent_platform_app` role.
    # Application code can never UPDATE/DELETE agent_versions, skill_versions,
    # or audit_events regardless of what the ORM/API layer exposes, because
    # this role's grants don't allow it (see ADR-0002's amendment and
    # migrations/versions/0008_immutability_roles.py).
    database_url: str = (
        "postgresql+asyncpg://agent_platform_app:agent_platform_app_dev"
        "@127.0.0.1:5432/agent_dev_platform_dev"
    )

    # Migration-time DB connection - a privileged owner role, used only by
    # Alembic. Never used by the running application.
    database_url_migrations: str = "postgresql+psycopg://ski@127.0.0.1:5432/agent_dev_platform_dev"

    # Auth: Identity Platform / Firebase Auth issues RS256 JWTs. In
    # production, jwks_url points at the real Identity Platform JWKS
    # endpoint. In tests, it's swapped for a local static JWKS fixture - see
    # app/auth/jwks.py and tests/conftest.py.
    auth_jwks_url: str = (
        "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
    )
    auth_issuer: str = "https://securetoken.google.com/orion-commerce-dev"
    auth_audience: str = "orion-commerce-dev"

    # Dev-only convenience: when set, app/auth/dependencies.py reads JWKS from
    # this local file instead of auth_jwks_url - see scripts/dev_login.py and
    # backend/README.md's "Local testing without real Identity Platform"
    # section. Never set in production; RemoteJWKSProvider is the real path.
    auth_jwks_file: str | None = None

    # Agent Evaluation Platform integration - docs/evaluation-and-promotion.md,
    # docs/gcp-architecture.md. Local dev/test target is unauthenticated (matches
    # agent-eval's real current state); the deployed Cloud Run target requires a
    # Google-signed ID token, supplied when agent_eval_audience is set.
    agent_eval_base_url: str = "http://127.0.0.1:8000"
    agent_eval_audience: str | None = None  # set to the Cloud Run URL to enable ID-token auth
    # Local-dev-only: impersonate this service account to mint the ID token above,
    # instead of using ADC directly (which fails for a human gcloud login - see
    # app/integrations/agent_eval_client.py::default_id_token_provider). Never set
    # in production, where the platform runs AS its own attached service account.
    agent_eval_impersonate_service_account: str | None = None

    # Job dispatch - "local" uses LocalSyncDispatcher (dev/test; not durable, see
    # app/services/job_dispatch.py), "cloud_tasks" uses the real CloudTasksDispatcher.
    job_dispatch_mode: str = "local"
    cloud_tasks_project: str | None = None
    cloud_tasks_location: str | None = None
    cloud_tasks_queue: str | None = None
    cloud_tasks_target_base_url: str | None = None
    cloud_tasks_target_service_account_email: str | None = None

    # Promotion lifecycle event outbox (Phase 4) - "local" uses LocalNoopPublisher
    # (dev/test; see app/services/event_publisher.py), "pubsub" uses the real
    # PubSubPublisher.
    event_publish_mode: str = "local"
    pubsub_project: str | None = None
    pubsub_topic: str | None = None

    # Public demo sandbox (Phase 7) - see app/services/demo.py and
    # docs/adrs/0022-public-demo-sandbox.md. Unset (None) means the demo
    # containment/rate-limit checks are all no-ops, matching every
    # environment before this feature existed (local dev, tests).
    demo_team_id: str | None = None
    # The only agent-eval target demo evaluation requests may invoke - a
    # lightweight stub run, never a real/expensive one. Requests naming any
    # other target are rejected outright for demo actors.
    demo_external_agent_version_id: str | None = None
    demo_eval_cooldown_seconds: int = 30
    demo_eval_concurrency_cap: int = 3

    # CI publishing machine identity (Phase 8) - see app/auth/ci_publisher.py,
    # docs/adrs/0024-ci-publishing-machine-identity.md. Unset (None) means the
    # CI-publish endpoint's OIDC check is a no-op, matching every environment
    # before this feature existed (local dev, tests) - real deployments
    # always set this to the real Workload-Identity-Federation-backed
    # publisher service account.
    ci_publisher_service_account_email: str | None = None
    ci_publisher_audience: str | None = None  # falls back to cloud_tasks_target_base_url if unset


settings = Settings()
