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


settings = Settings()
