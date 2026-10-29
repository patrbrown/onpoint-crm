from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings

_jwks_clients: dict[str, jwt.PyJWKClient] = {}


@dataclass
class CurrentUser:
    id: UUID
    email: str | None = None


def _decode(token: str, settings: Settings) -> dict:
    """Supabase signs access tokens either with a shared secret (HS256, older projects) or with
    asymmetric signing keys published at /auth/v1/.well-known/jwks.json (newer projects). Support both."""
    alg = jwt.get_unverified_header(token).get("alg", "HS256")
    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("SUPABASE_JWT_SECRET is not set")
        return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    client = _jwks_clients.setdefault(url, jwt.PyJWKClient(url, cache_keys=True))
    key = client.get_signing_key_from_jwt(token)
    return jwt.decode(token, key.key, algorithms=[alg], audience="authenticated")


def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    """Validates the Supabase access token sent by the web app."""
    if settings.dev_user_id and not authorization:
        return CurrentUser(id=UUID(settings.dev_user_id))
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = _decode(authorization.split(" ", 1)[1], settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {exc}") from exc
    return CurrentUser(id=UUID(claims["sub"]), email=claims.get("email"))
