#!/usr/bin/env python3
"""Dev-only helper: mints a locally-signed bearer token so you can actually
call authenticated endpoints without a real GCP/Identity Platform project.

Never used in production - the app's real auth path is
app/auth/jwks.py::RemoteJWKSProvider against Identity Platform
(docs/adrs/0010-authorization-model.md). This just generates a throwaway
RSA keypair (cached under backend/.devkeys/, gitignored) and signs a token
the app will accept when started with AUTH_JWKS_FILE pointed at the
matching public JWKS - see backend/README.md.

The actual signing logic lives in app/auth/dev_tokens.py (Phase 5 extracted
it there so the frontend's browser-usable dev login, app/api/dev_auth.py,
shares the exact same real signing path rather than a second copy).

Usage:
    python scripts/dev_login.py                              # tokens for all 4 seeded users
    python scripts/dev_login.py --email maya.chen@orioncommerce.example
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.auth.dev_tokens import AUDIENCE, ISSUER, JWKS_PATH, SEEDED_EMAILS, ensure_dev_keypair, mint_dev_token  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="Mint a token for just this seeded user's email")
    args = parser.parse_args()

    pem = ensure_dev_keypair()

    print(f"Start the server with (once, in this shell):\n")
    print(f'  export AUTH_JWKS_FILE="{JWKS_PATH}"')
    print(f'  export AUTH_ISSUER="{ISSUER}"')
    print(f'  export AUTH_AUDIENCE="{AUDIENCE}"')
    print(f"  uvicorn app.main:app --reload\n")
    print("Then use one of these bearer tokens (valid 12h):\n")

    emails = [args.email] if args.email else SEEDED_EMAILS
    for email in emails:
        print(f"# {email}")
        print(mint_dev_token(email, pem))
        print()


if __name__ == "__main__":
    main()
