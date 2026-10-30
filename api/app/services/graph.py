"""Microsoft Graph, read-only.

Sign-in uses the device-code flow: the CRM shows a short code, you enter it at microsoft.com/devicelogin
and sign in with your Outlook account. The token is cached per mailbox (in .secrets/, never committed)
and refreshed silently afterwards.

Only these delegated scopes are requested: Mail.Read, User.Read (+ offline_access, added by MSAL).
Mail.Read cannot move, flag, delete or send anything, so the agent physically cannot change Outlook.
"""
from __future__ import annotations

import asyncio
import base64
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import msal

from ..config import get_settings
from .clean import nul_free

SCOPES = ["Mail.Read", "User.Read"]
GRAPH = "https://graph.microsoft.com/v1.0"
MAX_ATTACHMENT = 15 * 1024 * 1024
MESSAGE_FIELDS = ("id,internetMessageId,conversationId,subject,from,toRecipients,receivedDateTime,"
                  "hasAttachments,body,bodyPreview")


class GraphAuthError(Exception):
    """No valid sign-in for this mailbox: the user needs to connect (again)."""


@dataclass
class Attachment:
    name: str
    content_type: str | None
    data: bytes


@dataclass
class Message:
    id: str
    internet_message_id: str | None
    conversation_id: str | None
    subject: str
    from_address: str | None
    from_name: str | None
    to: list[str]
    received_at: datetime
    body_text: str
    has_attachments: bool
    attachments: list[Attachment] = field(default_factory=list)


def _html_to_text(html: str) -> str:
    import html as htmllib
    import re

    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", html)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_message(m: dict[str, Any]) -> Message:
    m = nul_free(m)
    body = m.get("body") or {}
    content = body.get("content") or m.get("bodyPreview") or ""
    text = _html_to_text(content) if body.get("contentType", "").lower() == "html" else content
    sender = (m.get("from") or {}).get("emailAddress") or {}
    return Message(
        id=m["id"], internet_message_id=m.get("internetMessageId"), conversation_id=m.get("conversationId"),
        subject=m.get("subject") or "", from_address=(sender.get("address") or "").lower() or None,
        from_name=sender.get("name"),
        to=[(r.get("emailAddress") or {}).get("address", "") for r in m.get("toRecipients") or []],
        received_at=datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00")),
        body_text=text[:100_000], has_attachments=bool(m.get("hasAttachments")),
    )


class GraphMailbox:
    """One connected mailbox. `cache_key` is the mail_accounts.id (or 'pending-<tenant>' during sign-in)."""

    def __init__(self, cache_key: str):
        s = get_settings()
        if not (s.ms_client_id and s.ms_tenant_id):
            raise GraphAuthError("MS_CLIENT_ID and MS_TENANT_ID are not set in .env")
        self.cache_path = Path(s.ms_token_cache_path).parent / f"msal_{cache_key}.json"
        self.cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            self.cache.deserialize(self.cache_path.read_text())
        self.app = msal.PublicClientApplication(
            s.ms_client_id, authority=f"https://login.microsoftonline.com/{s.ms_tenant_id}", token_cache=self.cache)

    def _save(self) -> None:
        if self.cache.has_state_changed:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(self.cache.serialize())

    def rename(self, new_key: str) -> None:
        """After sign-in, move the cache from the pending key to the mail account id."""
        self._save()
        target = self.cache_path.parent / f"msal_{new_key}.json"
        if self.cache_path.exists():
            self.cache_path.replace(target)
        self.cache_path = target

    # ── sign-in ──────────────────────────────────────────────────────────────
    def start_device_flow(self) -> dict[str, Any]:
        flow = self.app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise GraphAuthError(flow.get("error_description") or "Could not start Microsoft sign-in")
        return flow

    def finish_device_flow(self, flow: dict[str, Any]) -> dict[str, Any]:
        """Blocks until the user finishes signing in (or the code expires, ~15 min)."""
        result = self.app.acquire_token_by_device_flow(flow)
        self._save()
        if "access_token" not in result:
            raise GraphAuthError(result.get("error_description") or "Microsoft sign-in did not complete")
        return result

    def token(self) -> str:
        accounts = self.app.get_accounts()
        result = self.app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        self._save()
        if not result or "access_token" not in result:
            raise GraphAuthError("Outlook sign-in has expired; connect Outlook again from the Email inbox page")
        return result["access_token"]

    def signed_in_address(self) -> str | None:
        accounts = self.app.get_accounts()
        return accounts[0].get("username", "").lower() if accounts else None

    # ── reading mail (GET only) ──────────────────────────────────────────────
    async def _get(self, client: httpx.AsyncClient, url: str, params: dict | None = None) -> dict[str, Any]:
        token = await asyncio.to_thread(self.token)
        for attempt in range(3):
            r = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}",
                                                               "Prefer": 'outlook.body-content-type="text"'})
            if r.status_code == 429 or r.status_code >= 500:   # throttled / transient
                await asyncio.sleep(int(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code == 401:
                raise GraphAuthError("Outlook rejected the sign-in; connect Outlook again")
            r.raise_for_status()
            return r.json()
        r.raise_for_status()
        return {}

    async def me(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as c:
            return await self._get(c, f"{GRAPH}/me", {"$select": "mail,userPrincipalName,displayName"})

    async def new_messages(self, since: datetime | None, limit: int = 100) -> list[Message]:
        """Inbox messages received after `since`, oldest first, with attachments loaded."""
        params = {"$select": MESSAGE_FIELDS, "$orderby": "receivedDateTime asc", "$top": "50"}
        if since:
            params["$filter"] = f"receivedDateTime gt {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        out: list[Message] = []
        async with httpx.AsyncClient(timeout=60) as c:
            url, p = f"{GRAPH}/me/mailFolders/inbox/messages", params
            while url and len(out) < limit:
                page = await self._get(c, url, p)
                out += [parse_message(m) for m in page.get("value", [])]
                url, p = page.get("@odata.nextLink"), None
            for msg in out[:limit]:
                if msg.has_attachments:
                    msg.attachments = await self._attachments(c, msg.id)
        return out[:limit]

    async def _attachments(self, c: httpx.AsyncClient, message_id: str) -> list[Attachment]:
        page = await self._get(c, f"{GRAPH}/me/messages/{message_id}/attachments")
        files = []
        for a in page.get("value", []):
            if a.get("@odata.type") != "#microsoft.graph.fileAttachment" or a.get("isInline"):
                continue
            if (a.get("size") or 0) > MAX_ATTACHMENT or not a.get("contentBytes"):
                continue
            files.append(Attachment(a.get("name") or "attachment", a.get("contentType"), base64.b64decode(a["contentBytes"])))
        return files


# ── device-code sign-in state, kept in memory while the user signs in ────────
_pending: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def pending_signin(tenant_id: str) -> dict[str, Any] | None:
    with _lock:
        return _pending.get(tenant_id)


def set_pending(tenant_id: str, state: dict[str, Any] | None) -> None:
    with _lock:
        if state is None:
            _pending.pop(tenant_id, None)
        else:
            _pending[tenant_id] = state
