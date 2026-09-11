import os
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

# Must happen before any `app.*` import, since app.config.settings is built
# once at import time from the environment.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://agent_platform_app:agent_platform_app_dev@127.0.0.1:5432/agent_dev_platform_test",
)
os.environ.setdefault(
    "DATABASE_URL_MIGRATIONS", "postgresql+psycopg://ski@127.0.0.1:5432/agent_dev_platform_test"
)
os.environ.setdefault("AUTH_ISSUER", "https://securetoken.google.com/orion-commerce-dev")
os.environ.setdefault("AUTH_AUDIENCE", "orion-commerce-dev")

import jwt
import psycopg
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_jwks_provider
from app.auth.jwks import StaticJWKSProvider
from app.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models.agent import Agent
from app.models.enums import Role
from app.models.identity import Team, User

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "test-key-1"


def _rsa_public_jwk() -> dict:
    public_numbers = _PRIVATE_KEY.public_key().public_numbers()

    def _b64url_uint(n: int) -> str:
        import base64

        length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    return {
        "kty": "RSA",
        "kid": _KID,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url_uint(public_numbers.n),
        "e": _b64url_uint(public_numbers.e),
    }


@pytest.fixture(scope="session")
def jwks_provider() -> StaticJWKSProvider:
    return StaticJWKSProvider({"keys": [_rsa_public_jwk()]})


@pytest.fixture
def sign_token():
    """Mints a real RS256-signed test ID token. Callers override claims,
    e.g. sign_token(email="wrong@x.example") or sign_token(exp_delta=-60)
    to produce an already-expired token.
    """

    def _sign(
        email: str = "maya.chen@orioncommerce.example",
        subject: str = "test-subject",
        audience: str | None = None,
        issuer: str | None = None,
        exp_delta_seconds: int = 3600,
    ) -> str:
        now = datetime.now(timezone.utc)
        claims = {
            "sub": subject,
            "email": email,
            "aud": audience or settings.auth_audience,
            "iss": issuer or settings.auth_issuer,
            "iat": now,
            "exp": now + timedelta(seconds=exp_delta_seconds),
        }
        pem = _PRIVATE_KEY.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": _KID})

    return _sign


@pytest.fixture(autouse=True)
def _reset_database():
    """Truncates every app table before each test, via the privileged
    migration role (the restricted agent_platform_app role has no TRUNCATE
    grant, by design - see migrations/versions/0008_immutability_roles.py).
    """
    conn = psycopg.connect("postgresql://ski@127.0.0.1:5432/agent_dev_platform_test")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE TABLE
                audit_events, outbox_events, promotion_decisions, promotion_requests,
                evaluation_gate_results, evaluation_run_references, evaluation_policies,
                agent_capability_grants, mcp_tools, mcp_servers,
                agent_version_skills, skill_versions, skills,
                agent_version_lifecycle, agent_versions, agents,
                users, teams
            RESTART IDENTITY CASCADE
            """
        )
    conn.close()
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator:
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def seed_team_and_user(db_session):
    """Minimal Team + User fixture for tests that need an authenticated caller."""

    async def _create(role: Role = Role.BUILDER, email: str = "maya.chen@orioncommerce.example"):
        team = Team(id=uuid.uuid4(), name=f"Team-{uuid.uuid4().hex[:8]}", slack_channel=None)
        db_session.add(team)
        await db_session.flush()
        user = User(id=uuid.uuid4(), name="Test User", email=email, team_id=team.id, role=role)
        db_session.add(user)
        await db_session.flush()
        await db_session.commit()
        return team, user

    return _create


@pytest_asyncio.fixture
async def org(db_session):
    """Two teams, one user per role in the first team (plus a second-team
    Builder for cross-team permission tests), all committed and ready to
    authenticate against. Returns a dict of role-name -> User.
    """
    team_a = Team(id=uuid.uuid4(), name=f"Team-A-{uuid.uuid4().hex[:8]}", slack_channel=None)
    team_b = Team(id=uuid.uuid4(), name=f"Team-B-{uuid.uuid4().hex[:8]}", slack_channel=None)
    db_session.add_all([team_a, team_b])
    await db_session.flush()

    def _user(role: Role, suffix: str, team_id: uuid.UUID) -> User:
        return User(
            id=uuid.uuid4(),
            name=f"Test {suffix}",
            email=f"{suffix}@orgtest.example",
            team_id=team_id,
            role=role,
        )

    viewer = _user(Role.VIEWER, "viewer", team_a.id)
    builder = _user(Role.BUILDER, "builder", team_a.id)
    reviewer = _user(Role.REVIEWER, "reviewer", team_a.id)
    admin = _user(Role.ADMIN, "admin", team_a.id)
    other_team_builder = _user(Role.BUILDER, "other-team-builder", team_b.id)
    db_session.add_all([viewer, builder, reviewer, admin, other_team_builder])
    await db_session.flush()
    await db_session.commit()

    return {
        "team_a": team_a,
        "team_b": team_b,
        "viewer": viewer,
        "builder": builder,
        "reviewer": reviewer,
        "admin": admin,
        "other_team_builder": other_team_builder,
    }


@pytest.fixture
def headers_for(sign_token):
    def _headers(user) -> dict:
        return {"Authorization": f"Bearer {sign_token(email=user.email)}"}

    return _headers


@pytest_asyncio.fixture
async def client(jwks_provider) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_jwks_provider] = lambda: jwks_provider
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
