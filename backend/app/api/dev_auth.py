"""Browser-usable dev login (Phase 5) - the same real signing path
scripts/dev_login.py has used since Phase 1, exposed as an endpoint so the
Next.js frontend's /login page can let a developer pick one of the four
seeded Orion Commerce users without running a script and pasting a token by
hand. The resulting token is genuinely RS256-signed and genuinely verified
by app/auth/dependencies.py::get_current_user via the real
StaticJWKSProvider/verify_id_token path - not a frontend-only mock, and not
a bypass of backend authorization.

Only registered at all when settings.auth_jwks_file is set (dev/test
key-file mode) - see app/main.py. In any deployment using the real
RemoteJWKSProvider (production), this module is never imported and this
route never exists.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dev_tokens import SEEDED_EMAILS, ensure_dev_keypair, mint_dev_token
from app.db.session import SessionLocal
from app.models.identity import User

router = APIRouter(prefix="/v1", tags=["dev-auth"])


class DevLoginRequest(BaseModel):
    email: str


@router.get("/dev-login/users")
async def list_dev_login_users() -> list[dict]:
    async with SessionLocal() as db:
        result = await db.execute(select(User).where(User.email.in_(SEEDED_EMAILS)).order_by(User.name))
        return [
            {"email": u.email, "name": u.name, "role": u.role.value, "team_id": str(u.team_id)}
            for u in result.scalars().all()
        ]


@router.post("/dev-login")
async def dev_login(body: DevLoginRequest) -> dict:
    if body.email not in SEEDED_EMAILS:
        raise HTTPException(status_code=400, detail="not a recognized dev-login user")
    pem = ensure_dev_keypair()
    token = mint_dev_token(body.email, pem)
    return {"token": token, "email": body.email}
