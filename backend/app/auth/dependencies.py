from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwks import JWKSProvider, RemoteJWKSProvider, StaticJWKSProvider
from app.auth.verify import TokenVerificationError, verify_id_token
from app.config import settings
from app.db.session import get_db
from app.models.identity import User

# auto_error=False so a missing/malformed header falls through to our own
# 401 below (matching existing behavior/tests) instead of HTTPBearer's
# default 403. Using the standard HTTPBearer security scheme (rather than a
# raw Header(...) parameter) also gives /docs a proper global "Authorize"
# button - found necessary in practice: a generic header text field tripped
# a real Swagger UI bug in this environment (reproduced in both Safari and
# Chrome) where a typed value never made it into the actual request.
_bearer_scheme = HTTPBearer(auto_error=False)


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
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
    jwks_provider: JWKSProvider = Depends(get_jwks_provider),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = credentials.credentials

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
