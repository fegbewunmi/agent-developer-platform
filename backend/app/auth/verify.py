"""Verifies an Identity Platform / Firebase Auth RS256 ID token.

This is the one place this platform authenticates anything - deliberate,
since none of the three systems it governs (ai-operations, agent-eval,
doc-qa) have any authentication to inherit. See
docs/adrs/0010-authorization-model.md.
"""
from dataclasses import dataclass

import jwt

from app.auth.jwks import JWKSProvider


class TokenVerificationError(Exception):
    """Raised for any invalid, expired, or unverifiable token."""


@dataclass(frozen=True)
class VerifiedClaims:
    subject: str
    email: str


def verify_id_token(
    token: str,
    jwks_provider: JWKSProvider,
    audience: str,
    issuer: str,
) -> VerifiedClaims:
    try:
        header = jwt.get_unverified_header(token)
        kid = header["kid"]
        signing_key = jwks_provider.get_signing_key(kid)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
        )
    except jwt.PyJWTError as exc:
        raise TokenVerificationError(str(exc)) from exc

    email = claims.get("email")
    subject = claims.get("sub")
    if not email or not subject:
        raise TokenVerificationError("token is missing required 'sub'/'email' claims")

    return VerifiedClaims(subject=subject, email=email)
