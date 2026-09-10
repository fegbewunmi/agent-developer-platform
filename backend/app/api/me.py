from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.models.identity import User

router = APIRouter(prefix="/v1", tags=["me"])


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    """Proves the JWT → platform-user resolution end to end - the first
    real authentication this platform (or any of the three systems it
    governs) has. See docs/adrs/0010-authorization-model.md.
    """
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "team_id": str(user.team_id),
        "role": user.role.value,
    }
