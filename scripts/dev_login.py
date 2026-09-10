#!/usr/bin/env python3
"""Dev-only helper: mints a locally-signed bearer token so you can actually
call authenticated endpoints without a real GCP/Identity Platform project.

Never used in production - the app's real auth path is
app/auth/jwks.py::RemoteJWKSProvider against Identity Platform
(docs/adrs/0010-authorization-model.md). This just generates a throwaway
RSA keypair (cached under backend/.devkeys/, gitignored) and signs a token
the app will accept when started with AUTH_JWKS_FILE pointed at the
matching public JWKS - see backend/README.md.

Usage:
    python scripts/dev_login.py                              # tokens for all 4 seeded users
    python scripts/dev_login.py --email maya.chen@orioncommerce.example
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEVKEYS_DIR = Path(__file__).resolve().parents[1] / "backend" / ".devkeys"
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


def _ensure_keypair() -> bytes:
    """Generates the dev keypair once and caches it - so tokens minted
    across separate runs of this script keep working against the same
    running server without needing to restart it.
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


def mint_token(email: str, pem: bytes) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": f"dev-login:{email}",
        "email": email,
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=12),
    }
    return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": KID})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="Mint a token for just this seeded user's email")
    args = parser.parse_args()

    pem = _ensure_keypair()

    print(f"Start the server with (once, in this shell):\n")
    print(f'  export AUTH_JWKS_FILE="{JWKS_PATH}"')
    print(f'  export AUTH_ISSUER="{ISSUER}"')
    print(f'  export AUTH_AUDIENCE="{AUDIENCE}"')
    print(f"  uvicorn app.main:app --reload\n")
    print("Then use one of these bearer tokens (valid 12h):\n")

    emails = [args.email] if args.email else SEEDED_EMAILS
    for email in emails:
        print(f"# {email}")
        print(mint_token(email, pem))
        print()


if __name__ == "__main__":
    main()
