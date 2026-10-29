"""Email inbox review: what the agent found, approve/edit/reject with feedback, and the Outlook connection."""
import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..agent import worker
from ..agent.commit import commit_item
from ..agent.email_agent import ScanResult, extract_and_queue, load_email
from ..auth import CurrentUser, get_current_user
from ..db import service_tx, user_tx
from ..llm import LLMProvider
from ..llm.tenant import llm_for_task
from ..schemas import _Base
from ..services import graph
from ..services.storage import Storage, get_storage

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["inbox"])
log = logging.getLogger("inbox")


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

@router.get("/mail")
async def mail_status(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        accounts = await conn.fetch(
            """select id, mailbox_address, is_enabled, last_sync_at, last_error, created_at from public.mail_accounts
               where tenant_id = $1 order by created_at""", tenant_id)
    from ..config import get_settings
    s = get_settings()
    pending = graph.pending_signin(str(tenant_id))
    return {
        "configured": bool(s.ms_client_id and s.ms_tenant_id),
        "accounts": [dict(a) for a in accounts],
        "signin": {k: pending[k] for k in ("user_code", "verification_uri", "status", "error", "expires_at")
                   if k in pending} if pending else None,
    }


async def _finish_signin(tenant_id: UUID, user_id: UUID, mailbox: graph.GraphMailbox, flow: dict) -> None:
    key = str(tenant_id)
    try:
        await asyncio.to_thread(mailbox.finish_device_flow, flow)
        me = await mailbox.me()
        address = (me.get("mail") or me.get("userPrincipalName") or "").lower()
        async with service_tx() as conn:
            account_id = await conn.fetchval(
                """insert into public.mail_accounts (tenant_id, user_id, provider, mailbox_address, auth_mode, is_enabled)
                   values ($1,$2,'microsoft',$3,'delegated',true)
                   on conflict (tenant_id, mailbox_address) do update set is_enabled = true, last_error = null
                   returning id""", tenant_id, user_id, address)
        mailbox.rename(str(account_id))
        graph.set_pending(key, {**(graph.pending_signin(key) or {}), "status": "connected", "mailbox": address})
    except Exception as exc:  # noqa: BLE001
        log.warning("Outlook sign-in failed: %s", exc)
        graph.set_pending(key, {**(graph.pending_signin(key) or {}), "status": "failed", "error": str(exc)})


@router.post("/mail/connect")
async def connect_outlook(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Start Microsoft sign-in. Returns a code to enter at the Microsoft page; the CRM finishes once you sign in."""
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select public.is_tenant_admin($1)", tenant_id):
            raise HTTPException(403, "Only workspace owners and admins can connect a mailbox")
    try:
        mailbox = graph.GraphMailbox(f"pending-{tenant_id}")
        flow = await asyncio.to_thread(mailbox.start_device_flow)
    except graph.GraphAuthError as exc:
        raise HTTPException(503, str(exc)) from exc
    graph.set_pending(str(tenant_id), {"user_code": flow["user_code"], "verification_uri": flow["verification_uri"],
                                       "status": "waiting", "expires_at": flow.get("expires_at")})
    asyncio.create_task(_finish_signin(tenant_id, user.id, mailbox, flow))
    return {"user_code": flow["user_code"], "verification_uri": flow["verification_uri"]}


@router.post("/mail/accounts/{account_id}/scan")
async def scan(tenant_id: UUID, account_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select 1 from public.mail_accounts where tenant_id = $1 and id = $2",
                                   tenant_id, account_id):
            raise HTTPException(404, "mailbox not found")
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
                                "returning id, is_enabled", tenant_id, account_id, enabled)
    if r is None:
        raise HTTPException(404, "mailbox not found")
    return dict(r)
