"""Public-key resolution for verifying Identity Platform / Firebase Auth
RS256 ID tokens (docs/adrs/0010-authorization-model.md).

Production wires RemoteJWKSProvider at settings.auth_jwks_url. Tests use
StaticJWKSProvider with a locally generated RSA keypair - see
tests/conftest.py - so the real RS256/JWKS verification path in verify.py
is exercised end-to-end without a network dependency or real GCP project.
"""
from abc import ABC, abstractmethod
from time import monotonic

import httpx
import jwt


class JWKSProvider(ABC):
    @abstractmethod
    def get_signing_key(self, kid: str) -> jwt.PyJWK: ...


class StaticJWKSProvider(JWKSProvider):
    """Wraps a fixed JWK set - used in tests, never in production."""

    def __init__(self, jwk_set: dict):
        self._client = jwt.PyJWKClient.__new__(jwt.PyJWKClient)
        self._keys = {
            key["kid"]: jwt.PyJWK.from_dict(key) for key in jwk_set["keys"]
        }

    def get_signing_key(self, kid: str) -> jwt.PyJWK:
        try:
            return self._keys[kid]
        except KeyError:
            raise jwt.InvalidTokenError(f"no signing key found for kid={kid!r}")


class RemoteJWKSProvider(JWKSProvider):
    """Fetches and caches Identity Platform's real JWKS over HTTPS."""

    def __init__(self, jwks_url: str, cache_ttl_seconds: float = 3600.0):
        self._jwks_url = jwks_url
        self._cache_ttl = cache_ttl_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0

    def _refresh(self) -> None:
        response = httpx.get(self._jwks_url, timeout=10.0)
        response.raise_for_status()
        jwk_set = response.json()
        self._keys = {key["kid"]: jwt.PyJWK.from_dict(key) for key in jwk_set["keys"]}
        self._fetched_at = monotonic()

    def get_signing_key(self, kid: str) -> jwt.PyJWK:
        if kid not in self._keys or (monotonic() - self._fetched_at) > self._cache_ttl:
            self._refresh()
        try:
            return self._keys[kid]
        except KeyError:
            raise jwt.InvalidTokenError(f"no signing key found for kid={kid!r}")
