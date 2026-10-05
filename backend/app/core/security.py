from fastapi import Header, HTTPException, status

from app.core.config import get_settings


async def require_user(authorization: str | None = Header(default=None)) -> str:
    s = get_settings()
    if not s.require_auth:
        return "owner"
    expected = f"Bearer {s.access_token}"
    if authorization != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    return "owner"
