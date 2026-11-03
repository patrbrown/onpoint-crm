"""Email inbox review: what the agent found, approve/edit/reject with feedback, and the Outlook connection."""
import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..agent import worker
from ..agent.commit import commit_item
from ..agent.email_agent import ScanResult, extract_and_queue, fetch_missing_files, load_email
from ..auth import CurrentUser, get_current_user
from ..db import service_tx, user_tx
from ..llm import LLMProvider
from ..llm.tenant import llm_for_task
from ..schemas import _Base
from ..services import graph
from ..services.storage import Storage, get_storage

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["inbox"])
log = logging.getLogger("inbox")


async def _fetch_files(conn, tenant_id: UUID, email_id: UUID) -> None:
    """Skipped emails didn't keep their files; get them from Outlook now. Best effort: if Outlook can't be
    reached, the email is still re-read from the text that was kept."""
    try:
        async with conn.transaction():
            await fetch_missing_files(conn, get_storage(), tenant_id, email_id, mailbox_factory=mailbox_factory())
    except Exception as exc:  # noqa: BLE001
        log.warning("couldn't fetch attachments for email %s: %s", email_id, exc)


def mailbox_factory():
    """Replaced in tests."""
    return graph.GraphMailbox


def llm_dep() -> LLMProvider | None:
    return None   # resolved per tenant; overridable in tests


# ── Review queue ────────────────────────────────────────────────────────────

@router.get("/inbox")
async def list_items(tenant_id: UUID, status: str = "pending", user: CurrentUser = Depends(get_current_user)) -> dict:
    statuses = ["approved", "auto_approved", "rejected", "merged"] if status == "done" else [status]
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select i.id, i.item_type, i.status, i.confidence, i.extracted, i.suggested_matches, i.created_at,
                      i.created_entity_type, i.created_entity_id, i.reviewed_at,
                      e.subject, e.from_address, e.from_name, e.received_at,
                      (select count(*) from public.email_attachments a where a.email_id = e.id) as attachment_count
               from public.inbox_items i left join public.email_messages e on e.id = i.email_id
               where i.tenant_id = $1 and i.status = any($2::text[])
               order by coalesce(e.received_at, i.created_at) desc limit 300""", tenant_id, statuses)
        counts = await conn.fetch("select status, count(*) from public.inbox_items where tenant_id = $1 group by 1",
                                  tenant_id)
        ignored = await conn.fetchval(
            """select count(*) from public.email_messages where tenant_id = $1
               and (classification not in ('job_requisition','resume','interview_feedback') or error is not null)""",
            tenant_id)
    return {"items": [dict(r) for r in rows], "counts": {r["status"]: r["count"] for r in counts}, "ignored_emails": ignored}


@router.get("/inbox/ignored")
async def ignored_emails(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """Emails the agent decided weren't jobs, resumes or feedback, so you can spot anything it missed."""
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select id, subject, from_address, from_name, received_at, classification, confidence, error
               from public.email_messages where tenant_id = $1
               and (classification not in ('job_requisition','resume','interview_feedback') or error is not null)
               order by received_at desc limit 200""", tenant_id)
    return [dict(r) for r in rows]


@router.get("/inbox/{item_id}")
async def get_item(tenant_id: UUID, item_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        item = await conn.fetchrow("select * from public.inbox_items where tenant_id = $1 and id = $2", tenant_id, item_id)
        if item is None:
            raise HTTPException(404, "inbox item not found")
        email = await conn.fetchrow(
            """select id, subject, from_address, from_name, to_addresses, received_at, body_text, classification, confidence
               from public.email_messages where id = $1""", item["email_id"]) if item["email_id"] else None
        atts = await conn.fetch("select id, file_name, mime_type, size_bytes from public.email_attachments "
                                "where email_id = $1", item["email_id"]) if item["email_id"] else []
    return {"item": dict(item), "email": dict(email) if email else None, "attachments": [dict(a) for a in atts]}


class Approve(_Base):
    final: dict[str, Any]            # the (possibly edited) fields to save
    links: dict[str, Any] = {}       # client_id / contact_id / candidate_id / job_id / application_id
    comment: str | None = None       # optional note to the agent about its extraction


def _changed_fields(extracted: dict, final: dict) -> dict:
    norm = lambda v: sorted(map(str, v)) if isinstance(v, list) else (None if v in ("", [], None) else str(v))  # noqa: E731
    return {k: {"was": extracted.get(k), "now": v} for k, v in final.items()
            if not k.startswith("_") and k != "confidence" and norm(extracted.get(k)) != norm(v)}


@router.post("/inbox/{item_id}/approve")
async def approve(tenant_id: UUID, item_id: UUID, body: Approve, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        item = await conn.fetchrow("select * from public.inbox_items where tenant_id = $1 and id = $2 for update",
                                   tenant_id, item_id)
        if item is None:
            raise HTTPException(404, "inbox item not found")
        final = {**body.final}
        if item["extracted"].get("_attachment_id"):
            final["_attachment_id"] = item["extracted"]["_attachment_id"]
        result = await commit_item(conn, tenant_id, item, final, body.links, reviewer=user.id)
        # Every review teaches the agent: the type was right, and which fields (if any) you corrected.
        changes = _changed_fields(item["extracted"], body.final)
        await conn.execute(
            """insert into public.ai_feedback (tenant_id, target_type, inbox_item_id, verdict, created_by)
               values ($1, 'classification', $2, 'correct', $3)""", tenant_id, item_id, user.id)
        await conn.execute(
            """insert into public.ai_feedback (tenant_id, target_type, inbox_item_id, verdict, corrected_value, comment,
               created_by) values ($1, 'extraction', $2, $3, $4, $5, $6)""",
            tenant_id, item_id, "partially_correct" if changes or body.comment else "correct", changes or None,
            body.comment, user.id)
    return result


class Reject(_Base):
    reason: Literal["wrong_type", "not_relevant", "duplicate", "other"]
    correct_type: Literal["job_requisition", "resume", "interview_feedback", "client_correspondence",
                          "candidate_reply", "other"] | None = None
    comment: str | None = None
    reprocess: bool = True   # with wrong_type + an actionable correct_type: re-read the email as that type


@router.post("/inbox/{item_id}/reject")
async def reject(tenant_id: UUID, item_id: UUID, body: Reject, user: CurrentUser = Depends(get_current_user),
                 llm_override: LLMProvider | None = Depends(llm_dep)) -> dict:
    async with user_tx(user.id) as conn:
        item = await conn.fetchrow("select * from public.inbox_items where tenant_id = $1 and id = $2 for update",
                                   tenant_id, item_id)
        if item is None:
            raise HTTPException(404, "inbox item not found")
        if item["status"] != "pending":
            raise HTTPException(409, f"This item was already {item['status'].replace('_', ' ')}")
        await conn.execute("update public.inbox_items set status = 'rejected', reviewed_by = $2, reviewed_at = now() "
                           "where id = $1", item_id, user.id)
        if body.reason == "wrong_type":
            await conn.execute(
                """insert into public.ai_feedback (tenant_id, target_type, inbox_item_id, verdict, corrected_value, comment,
                   created_by) values ($1, 'classification', $2, 'incorrect', $3, $4, $5)""",
                tenant_id, item_id, {"classification": body.correct_type or "other"}, body.comment, user.id)
        elif body.comment or body.reason == "not_relevant":
            await conn.execute(
                """insert into public.ai_feedback (tenant_id, target_type, inbox_item_id, verdict, corrected_value, comment,
                   created_by) values ($1, 'classification', $2, $3, $4, $5, $6)""",
                tenant_id, item_id, "incorrect" if body.reason == "not_relevant" else "correct",
                {"classification": "other"} if body.reason == "not_relevant" else None, body.comment, user.id)
        new_items: list[UUID] = []
        if (body.reason == "wrong_type" and body.reprocess and item["email_id"]
                and body.correct_type in ("job_requisition", "resume", "interview_feedback")):
            await conn.execute("update public.email_messages set classification = $2 where id = $1",
                               item["email_id"], body.correct_type)
            msg, atts = await load_email(conn, tenant_id, item["email_id"])
            llm = llm_override or await llm_for_task(conn, tenant_id, "email_extraction")
            new_items = await extract_and_queue(conn, llm, tenant_id, item["email_id"], body.correct_type, 1.0, msg,
                                                atts, None, ScanResult())
    return {"rejected": str(item_id), "new_items": [str(i) for i in new_items]}


class Rate(_Base):
    verdict: Literal["correct", "partially_correct", "incorrect"]
    comment: str | None = None


@router.post("/inbox/{item_id}/feedback")
async def rate(tenant_id: UUID, item_id: UUID, body: Rate, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Free-form feedback on an item at any time (including ones saved automatically)."""
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select 1 from public.inbox_items where tenant_id = $1 and id = $2", tenant_id, item_id):
            raise HTTPException(404, "inbox item not found")
        await conn.execute(
            """insert into public.ai_feedback (tenant_id, target_type, inbox_item_id, verdict, comment, created_by)
               values ($1, 'extraction', $2, $3, $4, $5)""", tenant_id, item_id, body.verdict, body.comment, user.id)
    return {"ok": True}


@router.post("/inbox/emails/{email_id}/reprocess")
async def reprocess_email(tenant_id: UUID, email_id: UUID, body: Reject, user: CurrentUser = Depends(get_current_user),
                          llm_override: LLMProvider | None = Depends(llm_dep)) -> dict:
    """An email the agent ignored was actually a job/resume/feedback: correct it and queue it."""
    if body.correct_type not in ("job_requisition", "resume", "interview_feedback"):
        raise HTTPException(422, "Choose job requisition, resume or interview feedback")
    async with user_tx(user.id) as conn:
        e = await conn.fetchrow("select classification from public.email_messages where tenant_id = $1 and id = $2",
                                tenant_id, email_id)
        if e is None:
            raise HTTPException(404, "email not found")
        await conn.execute(
            """insert into public.ai_feedback (tenant_id, target_type, email_id, verdict, corrected_value, comment,
               created_by) values ($1,'classification',$2,'incorrect',$3,$4,$5)""",
            tenant_id, email_id, {"classification": body.correct_type, "was": e["classification"]}, body.comment, user.id)
        await conn.execute("update public.email_messages set classification = $2 where id = $1", email_id, body.correct_type)
        await _fetch_files(conn, tenant_id, email_id)
        msg, atts = await load_email(conn, tenant_id, email_id)
        llm = llm_override or await llm_for_task(conn, tenant_id, "email_extraction")
        new_items = await extract_and_queue(conn, llm, tenant_id, email_id, body.correct_type, 1.0, msg, atts, None,
                                            ScanResult())
    return {"new_items": [str(i) for i in new_items]}


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(tenant_id: UUID, attachment_id: UUID, user: CurrentUser = Depends(get_current_user),
                              storage: Storage = Depends(get_storage)) -> Response:
    async with user_tx(user.id) as conn:
        a = await conn.fetchrow("select file_name, storage_path, mime_type from public.email_attachments "
                                "where tenant_id = $1 and id = $2", tenant_id, attachment_id)
    if a is None or not a["storage_path"]:
        raise HTTPException(404, "attachment not found")
    return Response(await storage.get(a["storage_path"]), media_type=a["mime_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{a["file_name"]}"'})


# ── Outlook connection ──────────────────────────────────────────────────────

def _signin_key(tenant_id: UUID, user_id: UUID) -> str:
    return f"{tenant_id}:{user_id}"   # each person signs in to their own mailbox


@router.get("/mail")
async def mail_status(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Mailboxes you can see: your own and ones shared with you (with their email), plus, for workspace admins,
    that other people's mailboxes exist (address and status only; their email stays private)."""
    async with user_tx(user.id) as conn:
        accounts = await conn.fetch(
            """select ma.id, ma.mailbox_address, ma.is_enabled, ma.last_sync_at, ma.last_error, ma.created_at,
                      ma.user_id = $2 as is_mine, public.can_read_mailbox(ma.id) as can_read,
                      coalesce(tm.full_name, p.full_name, p.email::text) as owner_name
               from public.mail_accounts ma
               left join public.profiles p on p.id = ma.user_id
               left join public.team_members tm on tm.tenant_id = ma.tenant_id and tm.user_id = ma.user_id
               where ma.tenant_id = $1 order by (ma.user_id = $2) desc, ma.created_at""", tenant_id, user.id)
        out = []
        for a in accounts:
            d = dict(a)
            if d["is_mine"]:
                d["shared_with"] = [dict(r) for r in await conn.fetch(
                    """select x.user_id, coalesce(tm.full_name, p.full_name, p.email::text) as name, p.email
                       from public.mailbox_access x join public.profiles p on p.id = x.user_id
                       left join public.team_members tm on tm.tenant_id = x.tenant_id and tm.user_id = x.user_id
                       where x.mail_account_id = $1 order by name""", d["id"])]
            out.append(d)
    from ..config import get_settings
    s = get_settings()
    pending = graph.pending_signin(_signin_key(tenant_id, user.id))
    return {
        "configured": bool(s.ms_client_id and s.ms_tenant_id),
        "accounts": out,
        "signin": {k: pending[k] for k in ("user_code", "verification_uri", "status", "error", "expires_at")
                   if k in pending} if pending else None,
    }


async def _finish_signin(tenant_id: UUID, user_id: UUID, mailbox: graph.GraphMailbox, flow: dict) -> None:
    key = _signin_key(tenant_id, user_id)
    try:
        await asyncio.to_thread(mailbox.finish_device_flow, flow)
        me = await mailbox.me()
        address = (me.get("mail") or me.get("userPrincipalName") or "").lower()
        async with service_tx() as conn:
            existing = await conn.fetchrow("select id, user_id from public.mail_accounts where tenant_id = $1 "
                                           "and mailbox_address = $2", tenant_id, address)
            if existing and existing["user_id"] and existing["user_id"] != user_id:
                # Someone else already connected this mailbox; it stays theirs (they decide who sees it).
                raise RuntimeError(f"{address} is already connected by someone else in this workspace. "
                                   "Ask them to share it with you.")
            account_id = await conn.fetchval(
                """insert into public.mail_accounts (tenant_id, user_id, provider, mailbox_address, auth_mode, is_enabled)
                   values ($1,$2,'microsoft',$3,'delegated',true)
                   on conflict (tenant_id, mailbox_address) do update set is_enabled = true, last_error = null,
                       user_id = coalesce(public.mail_accounts.user_id, excluded.user_id)
                   returning id""", tenant_id, user_id, address)
        mailbox.rename(str(account_id))
        graph.set_pending(key, {**(graph.pending_signin(key) or {}), "status": "connected", "mailbox": address})
    except Exception as exc:  # noqa: BLE001
        log.warning("Outlook sign-in failed: %s", exc)
        graph.set_pending(key, {**(graph.pending_signin(key) or {}), "status": "failed", "error": str(exc)})


@router.post("/mail/connect")
async def connect_outlook(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Start Microsoft sign-in for your own mailbox. Returns a code to enter at the Microsoft page; the CRM finishes
    once you sign in. The mailbox is private to you until you share it."""
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select public.is_member_strict($1)", tenant_id):
            raise HTTPException(403, "Only people in this workspace can connect a mailbox to it")
    try:
        mailbox = graph.GraphMailbox(f"pending-{tenant_id}-{user.id}")
        flow = await asyncio.to_thread(mailbox.start_device_flow)
    except graph.GraphAuthError as exc:
        raise HTTPException(503, str(exc)) from exc
    graph.set_pending(_signin_key(tenant_id, user.id), {
        "user_code": flow["user_code"], "verification_uri": flow["verification_uri"],
        "status": "waiting", "expires_at": flow.get("expires_at")})
    asyncio.create_task(_finish_signin(tenant_id, user.id, mailbox, flow))
    return {"user_code": flow["user_code"], "verification_uri": flow["verification_uri"]}


async def _readable(conn, tenant_id: UUID, account_id: UUID) -> None:
    if not await conn.fetchval("select exists(select 1 from public.mail_accounts where tenant_id = $1 and id = $2 "
                               "and public.can_read_mailbox(id))", tenant_id, account_id):
        raise HTTPException(404, "mailbox not found")


# ── Who can see a mailbox ───────────────────────────────────────────────────

class ShareBody(_Base):
    user_id: UUID


@router.get("/mail/people")
async def people(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """People in this workspace who have a login (the only ones a mailbox can be shared with)."""
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select m.user_id, coalesce(tm.full_name, p.full_name, p.email::text) as name, p.email, m.role
               from public.memberships m join public.profiles p on p.id = m.user_id
               left join public.team_members tm on tm.tenant_id = m.tenant_id and tm.user_id = m.user_id
               where m.tenant_id = $1 and m.user_id <> $2 order by name""", tenant_id, user.id)
    return [dict(r) for r in rows]


@router.post("/mail/accounts/{account_id}/access")
async def share(tenant_id: UUID, account_id: UUID, body: ShareBody, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select exists(select 1 from public.mail_accounts where tenant_id = $1 and id = $2 "
                                   "and user_id = $3)", tenant_id, account_id, user.id):
            raise HTTPException(403, "Only the person who connected this mailbox can change who sees it")
        if not await conn.fetchval("select exists(select 1 from public.memberships where tenant_id = $1 and user_id = $2)",
                                   tenant_id, body.user_id):
            raise HTTPException(422, "That person isn't in this workspace (or has no login yet)")
        await conn.execute(
            """insert into public.mailbox_access (tenant_id, mail_account_id, user_id, granted_by) values ($1,$2,$3,$4)
               on conflict do nothing""", tenant_id, account_id, body.user_id, user.id)
    return {"shared_with": str(body.user_id)}


@router.delete("/mail/accounts/{account_id}/access/{user_id}")
async def unshare(tenant_id: UUID, account_id: UUID, user_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select exists(select 1 from public.mail_accounts where tenant_id = $1 and id = $2 "
                                   "and user_id = $3)", tenant_id, account_id, user.id):
            raise HTTPException(403, "Only the person who connected this mailbox can change who sees it")
        await conn.execute("delete from public.mailbox_access where mail_account_id = $1 and user_id = $2",
                           account_id, user_id)
    return {"removed": str(user_id)}


@router.post("/mail/accounts/{account_id}/scan")
async def scan(tenant_id: UUID, account_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        await _readable(conn, tenant_id, account_id)
    try:
        r = await worker.scan_now(account_id)
    except graph.GraphAuthError as exc:
        raise HTTPException(401, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return r.__dict__


@router.patch("/mail/accounts/{account_id}")
async def toggle_account(tenant_id: UUID, account_id: UUID, enabled: bool, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        r = await conn.fetchrow("update public.mail_accounts set is_enabled = $3 where tenant_id = $1 and id = $2 "
                                "and user_id = $4 returning id, is_enabled", tenant_id, account_id, enabled, user.id)
    if r is None:
        raise HTTPException(403, "Only the person who connected this mailbox can pause or resume it")
    return dict(r)
