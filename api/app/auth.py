from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings
from .db import user_tx


@dataclass
class CurrentUser:
    id: UUID
    email: str | None = None


def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validates the Supabase access token sent by the web app."""
    if settings.dev_user_id and not authorization:
        return CurrentUser(id=UUID(settings.dev_user_id))
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        claims = jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return CurrentUser(id=UUID(claims["sub"]), email=claims.get("email"))


async def require_member(tenant_id: UUID, user: CurrentUser) -> None:
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select public.is_member($1)", tenant_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this tenant")
