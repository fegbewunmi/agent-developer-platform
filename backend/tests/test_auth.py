"""End-to-end auth tests through the real HTTP layer: real RS256 signing,
real JWKS-based verification (app/auth/verify.py + app/auth/jwks.py), real
DB lookup of the resolved user. Only the JWKS *source* is swapped for a
local keypair (tests/conftest.py) - verification logic itself is untouched.
"""
async def test_health_is_public(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_me_without_authorization_header_is_401(client):
    resp = await client.get("/v1/me")
    assert resp.status_code == 401


async def test_me_with_malformed_header_is_401(client):
    resp = await client.get("/v1/me", headers={"Authorization": "NotBearer xyz"})
    assert resp.status_code == 401


async def test_me_with_valid_token_resolves_the_seeded_user(client, seed_team_and_user, sign_token):
    from app.models.enums import Role

    team, user = await seed_team_and_user(role=Role.BUILDER, email="maya.chen@orioncommerce.example")
    token = sign_token(email="maya.chen@orioncommerce.example")

    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "maya.chen@orioncommerce.example"
    assert body["role"] == "builder"
    assert body["team_id"] == str(team.id)


async def test_me_for_unknown_email_is_401(client, sign_token):
    token = sign_token(email="nobody@orioncommerce.example")
    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_me_with_expired_token_is_401(client, seed_team_and_user, sign_token):
    await seed_team_and_user(email="maya.chen@orioncommerce.example")
    token = sign_token(email="maya.chen@orioncommerce.example", exp_delta_seconds=-60)
    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_me_with_wrong_audience_is_401(client, seed_team_and_user, sign_token):
    await seed_team_and_user(email="maya.chen@orioncommerce.example")
    token = sign_token(email="maya.chen@orioncommerce.example", audience="some-other-project")
    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_me_with_wrong_issuer_is_401(client, seed_team_and_user, sign_token):
    await seed_team_and_user(email="maya.chen@orioncommerce.example")
    token = sign_token(email="maya.chen@orioncommerce.example", issuer="https://evil.example/not-real")
    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_me_with_token_signed_by_a_different_key_is_401(client, seed_team_and_user):
    """A token that is well-formed and even claims the right kid, but was
    actually signed by a key our JWKS provider doesn't have, must be
    rejected - proves signature verification is real, not just claim
    inspection.
    """
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    await seed_team_and_user(email="maya.chen@orioncommerce.example")
    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives import serialization

    pem = rogue_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    from datetime import datetime, timedelta, timezone

    from app.config import settings

    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "rogue",
            "email": "maya.chen@orioncommerce.example",
            "aud": settings.auth_audience,
            "iss": settings.auth_issuer,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        pem,
        algorithm="RS256",
        headers={"kid": "test-key-1"},  # same kid, different actual key
    )

    resp = await client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
