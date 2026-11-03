"""Supabase Auth admin calls (needs SUPABASE_URL and the secret/service-role key): create a login for an invited
person and get their personal sign-in link. Swapped for a fake in tests."""
from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings
from .storage import _auth_headers


class AuthAdminError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class AuthAdmin:
    def __init__(self, url: str, key: str):
        if not url or not key:
            raise AuthAdminError(0, "Inviting people needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in .env")
        self.base = f"{url.rstrip('/')}/auth/v1"
        self.headers = {**_auth_headers(key), "Content-Type": "application/json"}

    async def _post(self, path: str, body: dict, params: dict | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(self.base + path, json=body, params=params, headers=self.headers)
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            msg = data.get("msg") or data.get("message") or data.get("error_description") or data.get("error") or r.text[:200]
            raise AuthAdminError(r.status_code, str(msg))
        return data

    async def invite_link(self, email: str, full_name: str | None, redirect_to: str) -> tuple[str, str]:
        """Creates the login if it's new and returns (user_id, sign-in link). Sends no email."""
        meta = {"full_name": full_name} if full_name else {}
        try:
            d = await self._post("/admin/generate_link", {"type": "invite", "email": email, "data": meta,
                                                          "redirect_to": redirect_to})
        except AuthAdminError as exc:
            if exc.status not in (400, 409, 422) or "regist" not in str(exc).lower() and "exist" not in str(exc).lower():
                raise
            # Already has a login (e.g. invited before, or uses another workspace): a one-time sign-in link instead.
            d = await self._post("/admin/generate_link", {"type": "magiclink", "email": email, "redirect_to": redirect_to})
        user_id = d.get("id") or (d.get("user") or {}).get("id")
        link = d.get("action_link") or (d.get("properties") or {}).get("action_link")
        if not user_id or not link:
            raise AuthAdminError(502, "Supabase didn't return a sign-in link")
        return str(user_id), str(link)

    async def send_invite(self, email: str, full_name: str | None, redirect_to: str) -> str:
        """Asks Supabase to email the invite itself (needs your own email service set up in Supabase)."""
        d = await self._post("/invite", {"email": email, "data": {"full_name": full_name} if full_name else {}},
                             params={"redirect_to": redirect_to})
        user_id = d.get("id") or (d.get("user") or {}).get("id")
        if not user_id:
            raise AuthAdminError(502, "Supabase didn't confirm the invite")
        return str(user_id)


def get_auth_admin() -> AuthAdmin:
    s = get_settings()
    return AuthAdmin(s.supabase_url, s.supabase_service_role_key)
