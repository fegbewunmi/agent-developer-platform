"""Shared dev-only token-minting logic - the same real signing/verification
path scripts/dev_login.py has used since Phase 1 (a genuine RS256-signed
JWT, verified by the app's real StaticJWKSProvider/verify_id_token path, not
a frontend-only mock), extracted here so app/api/dev_auth.py (Phase 5's
browser-usable login) and the CLI script share one implementation instead of
two copies of RSA/JWT logic drifting apart.

Never used in production - see app/auth/dependencies.py's RemoteJWKSProvider
for the real path. Only reachable at all when settings.auth_jwks_file is set
(dev/test key-file mode), which app/api/dev_auth.py's router registration
checks before even wiring the route in - see app/main.py.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEVKEYS_DIR = Path(__file__).resolve().parents[2] / ".devkeys"
PRIVATE_KEY_PATH = DEVKEYS_DIR / "dev_private_key.pem"
JWKS_PATH = DEVKEYS_DIR / "jwks.json"
KID = "dev-key-1"

ISSUER = "https://securetoken.google.com/orion-commerce-dev"
AUDIENCE = "orion-commerce-dev"

SEEDED_EMAILS = [
    "maya.chen@orioncommerce.example",  # Builder, AI Platform
    "jordan.brooks@orioncommerce.example",  # Reviewer, SRE
    "priya.shah@orioncommerce.example",  # Reviewer, Customer Support Engineering
    "alex.rivera@orioncommerce.example",  # Admin, AI Platform
]


def _b64url_uint(n: int) -> str:
    import base64

    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()


def ensure_dev_keypair() -> bytes:
    """Generates the dev keypair once and caches it under .devkeys/
    (gitignored) - so tokens minted across separate runs/requests keep
    working against the same running server without needing a restart.
    """
    DEVKEYS_DIR.mkdir(parents=True, exist_ok=True)
    if PRIVATE_KEY_PATH.exists() and JWKS_PATH.exists():
        return PRIVATE_KEY_PATH.read_bytes()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    PRIVATE_KEY_PATH.write_bytes(pem)

    public_numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": _b64url_uint(public_numbers.n),
                "e": _b64url_uint(public_numbers.e),
            }
        ]
    }
    JWKS_PATH.write_text(json.dumps(jwks))
    return pem


def mint_dev_token(email: str, pem: bytes, *, expires_in_hours: int = 12) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": f"dev-login:{email}",
        "email": email,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=expires_in_hours),
    }
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": KID})
