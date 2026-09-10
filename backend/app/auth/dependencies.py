from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwks import JWKSProvider, RemoteJWKSProvider, StaticJWKSProvider
from app.auth.verify import TokenVerificationError, verify_id_token
from app.config import settings
from app.db.session import get_db
from app.models.identity import User


@lru_cache
def get_jwks_provider() -> JWKSProvider:
    """Default: the real Identity Platform JWKS endpoint. If
    settings.auth_jwks_file is set (dev-only - see scripts/dev_login.py),
    reads a local static JWKS instead, so the app can run without a real GCP
    project. Never set auth_jwks_file in production.

    Overridden again in tests via app.dependency_overrides - see tests/conftest.py.
    """
    if settings.auth_jwks_file:
        return StaticJWKSProvider.from_file(settings.auth_jwks_file)
    return RemoteJWKSProvider(settings.auth_jwks_url)


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    jwks_provider: JWKSProvider = Depends(get_jwks_provider),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.removeprefix("Bearer ").strip()

    try:
        claims = verify_id_token(
            token,
            jwks_provider,
            audience=settings.auth_audience,
            issuer=settings.auth_issuer,
        )
    except TokenVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        ) from exc

    result = await db.execute(select(User).where(User.email == claims.email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"No platform user found for authenticated email {claims.email!r}",
        )
    return user
