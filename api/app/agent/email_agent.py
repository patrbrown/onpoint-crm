"""The email agent: read new Outlook mail, decide what each email is, extract the details, and either queue
it for review or (in automatic mode, when confident) save it straight into the CRM.

It never changes anything in Outlook: it only reads (Graph Mail.Read)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Any, Protocol
from uuid import UUID

import asyncpg
from rapidfuzz import fuzz

from ..llm import LLMProvider
import httpx

from ..services import jd_markdown, jev
from ..services.storage import Storage
from ..services.text_extract import SUPPORTED, extract_text
from . import matching
from .commit import commit_item
from .prompts import (CLASSIFY_SYSTEM, FEEDBACK_EXTRACT_SYSTEM, JOB_EXTRACT_SYSTEM, PROMPT_VERSION,
                      RESUME_EXTRACT_SYSTEM, with_examples)

log = logging.getLogger("email_agent")
FIRST_SYNC_DAYS = 7
CLASSES = {"job_requisition", "resume", "interview_feedback", "client_correspondence", "candidate_reply", "other"}
ACTIONABLE = {"job_requisition", "resume", "interview_feedback"}
RESUME_HINT = re.compile(r"(resume|résumé|cv|curriculum)", re.I)
MAX_ATTEMPTS = 3
_attempts: dict[str, int] = {}


class Mailbox(Protocol):
    async def new_messages(self, since: datetime | None, limit: int = 100) -> list: ...


@dataclass
class ScanResult:
    fetched: int = 0
    new: int = 0
    queued: int = 0
    auto_approved: int = 0
    ignored: int = 0
    errors: int = 0


def _clamp(x: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return default


async def feedback_examples(conn: asyncpg.Connection, tenant_id: UUID, target: str, limit: int = 10) -> list[dict]:
    """Recent recruiter corrections, fed back into the prompts so the agent learns this agency's inbox."""
    rows = await conn.fetch(
        """select f.corrected_value, f.comment, e.subject, e.from_address,
                  coalesce(i.item_type, f.corrected_value->>'was') as item_type
           from public.ai_feedback f
           left join public.inbox_items i on i.id = f.inbox_item_id
           left join public.email_messages e on e.id = coalesce(f.email_id, i.email_id)
           where f.tenant_id = $1 and f.target_type = $2 and f.use_as_example and f.verdict <> 'correct'
           order by f.created_at desc limit $3""", tenant_id, target, limit)
    out = []
    for r in rows:
        cv = r["corrected_value"] or {}
        if target == "classification":
            out.append({"summary": f"email from {r['from_address']} with subject “{(r['subject'] or '')[:80]}” "
                                   f"was labelled {r['item_type']}",
                        "correct": cv.get("classification"), "comment": r["comment"]})
        elif r["comment"]:
            out.append({"summary": f"{r['item_type']} extraction", "correct": "see note", "comment": r["comment"]})
    return out


def _email_prompt(msg, attachments: list[tuple[str, str]], per_attachment: int = 6000) -> str:
    parts = [f"From: {msg.from_name or ''} <{msg.from_address or ''}>", f"Subject: {msg.subject}", "", msg.body_text[:8000]]
    for name, text in attachments:
        parts += ["", f"--- Attachment: {name} ---", text[:per_attachment]]
    return "\n".join(parts)


def apply_jd_attachments(data: dict, atts: list[dict]) -> None:
    """If the req came with the JD as an attachment, the job description is that file, copied word for word
    as Markdown (not the model's summary of it)."""
    by_name = {a["name"]: a for a in atts if a.get("markdown")}
    picked = jd_markdown.pick_jd_attachments(list(by_name))
    if not picked:
        return
    if len(picked) == 1:
        description = by_name[picked[0]]["markdown"]
    else:
        description = "\n\n".join(f"# {PurePath(n).stem}\n\n{by_name[n]['markdown']}" for n in picked)
    data["description"] = description.strip()
    data["_description_from"] = picked


def jev_client():
    """Factory (replaced in tests)."""
    return jev.JevClient()


async def triage_email(conn, llm: LLMProvider, tenant_id: UUID, msg, readable: list[tuple[str, str]],
                       settings: asyncpg.Record | None) -> tuple[str, float, dict]:
    """Decide what kind of email this is. Uses Jev when the workspace has switched to it (falling back to the
    LLM if Jev is unavailable), otherwise the LLM. Returns (type, confidence, triage details)."""
    examples = await feedback_examples(conn, tenant_id, "classification")
    use_jev = settings is not None and settings.get("triage_provider") == "jev"
    if use_jev:
        cfg = jev.merged_config(settings.get("jev_config"))
        corrections = [f"{e['summary']}, but it was actually {e['correct']}" + (f" ({e['comment']})" if e.get("comment") else "")
                       for e in examples]
        request = jev.build_request(cfg, settings.get("jev_model") or "jev-latest", msg.subject,
                                    f"{msg.from_name or ''} <{msg.from_address or ''}>", msg.body_text, readable, corrections)
        try:
            t = await jev_client().classify(request)
            kind, conf = t.classification, t.confidence
            details = {"provider": "jev", "model": t.model, "probabilities": t.probabilities}
            # Safety net: Jev says "not recruiting" but isn't sure, and a recruiting type is a real possibility.
            floor = float(settings.get("review_below_confidence") or 0)
            if kind not in ACTIONABLE and conf < floor:
                alt = max(ACTIONABLE, key=lambda c: t.probabilities.get(c, 0))
                if t.probabilities.get(alt, 0) >= 0.15:
                    details["unsure"] = {"was": kind, "was_confidence": round(conf, 3)}
                    kind, conf = alt, t.probabilities[alt]
            return kind, conf, details
        except jev.JevError as exc:
            log.warning("Jev unavailable, using the LLM for this email: %s", exc)
            fallback = str(exc)
        except httpx.HTTPError as exc:
            log.warning("Jev unreachable, using the LLM for this email: %s", exc)
            fallback = f"Jev unreachable: {exc}"
    cls, _ = await llm.complete_json(with_examples(CLASSIFY_SYSTEM, examples), _email_prompt(msg, readable), 400)
    kind = cls.get("classification") if cls.get("classification") in CLASSES else "other"
    details = {"provider": llm.name, "model": llm.model, "reason": cls.get("reason")}
    if use_jev:
        details["jev_error"] = fallback
    return kind, _clamp(cls.get("confidence")), details


async def _store_message(conn, storage: Storage, tenant_id: UUID, account_id: UUID, msg) -> tuple[UUID, list[dict]] | None:
    email_id = await conn.fetchval(
        """insert into public.email_messages (tenant_id, mail_account_id, provider_message_id, internet_message_id,
           conversation_id, from_address, from_name, to_addresses, subject, received_at, body_text, has_attachments)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
           on conflict (mail_account_id, provider_message_id) do nothing returning id""",
        tenant_id, account_id, msg.id, msg.internet_message_id, msg.conversation_id, msg.from_address, msg.from_name,
        msg.to, msg.subject, msg.received_at, msg.body_text, msg.has_attachments)
    if email_id is None:
        return None   # already processed
    atts = []
    for a in msg.attachments:
        text = None
        if PurePath(a.name).suffix.lower() in SUPPORTED:
            try:
                text = extract_text(a.name, a.data)
            except Exception:   # noqa: BLE001 — a broken attachment shouldn't stop the email
                text = None
        md = None
        if PurePath(a.name).suffix.lower() in jd_markdown.CONVERTIBLE:
            try:
                md = jd_markdown.to_markdown(a.name, a.data)
            except Exception:  # noqa: BLE001
                md = None
        safe = re.sub(r"[^\w.\-]+", "_", a.name)
        path = f"{tenant_id}/email/{email_id}/{safe}"
        await storage.put(path, a.data, a.content_type)
        att_id = await conn.fetchval(
            """insert into public.email_attachments (tenant_id, email_id, file_name, mime_type, size_bytes, storage_path,
               extracted_text, markdown) values ($1,$2,$3,$4,$5,$6,$7,$8) returning id""",
            tenant_id, email_id, a.name, a.content_type, len(a.data), path, text, md)
        atts.append({"id": att_id, "name": a.name, "text": text, "markdown": md})
    return email_id, atts


async def _queue(conn, tenant_id: UUID, email_id: UUID, kind: str, extracted: dict, confidence: float,
                 matches: list[dict], llm: LLMProvider) -> asyncpg.Record:
    return await conn.fetchrow(
        """insert into public.inbox_items (tenant_id, email_id, item_type, confidence, extracted, suggested_matches,
           llm_provider, llm_model, prompt_version) values ($1,$2,$3,$4,$5,$6,$7,$8,$9) returning *""",
        tenant_id, email_id, kind, round(confidence, 2), extracted, matches, llm.name, llm.model, PROMPT_VERSION)


def _auto_links(kind: str, matches: list[dict]) -> dict | None:
    """Links automatic mode may use. None = ambiguous, so the item waits for review even if confident."""
    best = lambda t: [m for m in matches if m["type"] == t]  # noqa: E731
    if kind == "job_requisition":
        if best("job"):
            return None   # might be a duplicate of an existing job: a human decides
        clients = best("client")
        if len(clients) > 1:
            return None
        return {"client_id": clients[0]["id"], "contact_id": clients[0].get("contact_id")} if clients else {}
    if kind == "resume":
        cands, jobs = best("candidate"), best("job")
        if any(c["reason"] != "same email" for c in cands) or len(jobs) > 1:
            return None
        links = {"candidate_id": cands[0]["id"]} if cands else {}
        if jobs:
            links["job_id"] = jobs[0]["id"]
        return links
    if kind == "interview_feedback":
        apps = best("application")
        if len(apps) != 1 or apps[0]["score"] < 90:
            return None
        return {"application_id": apps[0]["id"]}
    return None


async def process_message(conn, storage: Storage, llm: LLMProvider, tenant_id: UUID, account_id: UUID, msg,
                          settings: asyncpg.Record, result: ScanResult) -> None:
    stored = await _store_message(conn, storage, tenant_id, account_id, msg)
    if stored is None:
        return
    email_id, atts = stored
    result.new += 1
    readable = [(a["name"], a["text"]) for a in atts if a["text"]]

    kind, conf, triage = await triage_email(conn, llm, tenant_id, msg, readable, settings)
    await conn.execute("update public.email_messages set classification = $2, confidence = $3, triage = $4, "
                       "processed_at = now() where id = $1", email_id, kind, round(conf, 2), triage)
    if kind not in ACTIONABLE:
        result.ignored += 1
        return
    await extract_and_queue(conn, llm, tenant_id, email_id, kind, conf, msg, atts, settings, result)


async def extract_and_queue(conn, llm: LLMProvider, tenant_id: UUID, email_id: UUID, kind: str, conf: float, msg,
                            atts: list[dict], settings: asyncpg.Record | None, result: ScanResult) -> list[UUID]:
    """Extract the details for one email of a known type and queue (or auto-save) the resulting item(s)."""
    readable = [(a["name"], a["text"]) for a in atts if a["text"]]
    notes = await feedback_examples(conn, tenant_id, "extraction", 5)
    items: list[tuple[dict, float, list[dict]]] = []
    if kind == "job_requisition":
        data, _ = await llm.complete_json(with_examples(JOB_EXTRACT_SYSTEM, notes),
                                          _email_prompt(msg, readable, per_attachment=20000), 6000)
        apply_jd_attachments(data, atts)
        clients = await matching.client_matches(conn, tenant_id, data.get("client_name"), msg.from_address)
        dupes = await matching.duplicate_jobs(conn, tenant_id, data.get("title"), data.get("reference_code"),
                                              [c["id"] for c in clients])
        items.append((data, min(conf, _clamp(data.get("confidence"))), clients + dupes))
    elif kind == "resume":
        jobs = await matching.job_mentions(conn, tenant_id, f"{msg.subject}\n{msg.body_text[:3000]}")
        resumes = [a for a in atts if a["text"] and (RESUME_HINT.search(a["name"]) or len(atts) == 1
                                                      or PurePath(a["name"]).suffix.lower() in {".pdf", ".docx"})]
        sources = [(a["id"], a["text"]) for a in resumes] or [(None, msg.body_text)]
        for att_id, text in sources[:5]:
            data, _ = await llm.complete_json(with_examples(RESUME_EXTRACT_SYSTEM, notes), f"Resume text:\n\n{text[:30000]}")
            if att_id:
                data["_attachment_id"] = str(att_id)
            if (not data.get("email") and msg.from_address and len(sources) == 1 and msg.from_name
                    and fuzz.token_sort_ratio(msg.from_name.lower(),
                                              f"{data.get('first_name') or ''} {data.get('last_name') or ''}".lower()) >= 85):
                data["email"] = msg.from_address   # the candidate emailed their own resume
            cands = await matching.candidate_matches(conn, tenant_id, data)
            items.append((data, min(conf, _clamp(data.get("confidence"))), cands + jobs))
    elif kind == "interview_feedback":
        data, _ = await llm.complete_json(with_examples(FEEDBACK_EXTRACT_SYSTEM, notes), _email_prompt(msg, readable))
        data.setdefault("from_email", msg.from_address)
        data.setdefault("from_name", msg.from_name)
        apps = await matching.application_matches(conn, tenant_id, data.get("candidate_name"),
                                                  data.get("candidate_email"), data.get("job_title"))
        items.append((data, min(conf, _clamp(data.get("confidence"))), apps))

    created: list[UUID] = []
    for data, confidence, matches in items:
        item = await _queue(conn, tenant_id, email_id, kind, data, confidence, matches, llm)
        created.append(item["id"])
        links = _auto_links(kind, matches)
        if (settings is not None and settings["inbox_mode"] == "auto" and links is not None
                and confidence >= float(settings["auto_approve_threshold"])):
            try:
                async with conn.transaction():
                    await commit_item(conn, tenant_id, item, data, links, reviewer=None, auto=True)
                result.auto_approved += 1
                continue
            except Exception as exc:  # noqa: BLE001 — fall back to review
                log.warning("auto-approve failed for %s: %s", item["id"], exc)
        result.queued += 1
    return created


@dataclass
class StoredEmail:
    """An email rebuilt from the database (for re-running extraction after a correction)."""
    id: str
    subject: str
    from_address: str | None
    from_name: str | None
    body_text: str


async def load_email(conn, tenant_id: UUID, email_id: UUID) -> tuple[StoredEmail, list[dict]]:
    e = await conn.fetchrow("select * from public.email_messages where tenant_id = $1 and id = $2", tenant_id, email_id)
    atts = await conn.fetch("select id, file_name as name, extracted_text as text, markdown from public.email_attachments "
                            "where tenant_id = $1 and email_id = $2", tenant_id, email_id)
    return (StoredEmail(e["provider_message_id"], e["subject"] or "", e["from_address"], e["from_name"], e["body_text"] or ""),
            [dict(a) for a in atts])


async def scan_account(conn: asyncpg.Connection, storage: Storage, llm: LLMProvider, mailbox: Mailbox,
                       account: asyncpg.Record) -> ScanResult:
    """One pass over a mailbox. `conn` must be a service connection (the agent runs without a logged-in user)."""
    tenant_id, account_id = account["tenant_id"], account["id"]
    settings = await conn.fetchrow("select * from public.tenant_settings where tenant_id = $1", tenant_id)
    since = account["last_sync_at"] or datetime.now(timezone.utc) - timedelta(days=FIRST_SYNC_DAYS)
    result = ScanResult()
    messages = await mailbox.new_messages(since)
    result.fetched = len(messages)
    latest = since
    for msg in messages:
        before = replace(result)   # counts roll back with the transaction if this email fails
        try:
            async with conn.transaction():   # one email = one unit of work
                await process_message(conn, storage, llm, tenant_id, account_id, msg, settings, result)
            latest = max(latest, msg.received_at)
        except Exception as exc:  # noqa: BLE001
            result.__dict__.update(before.__dict__)
            result.errors += 1
            log.exception("failed to process message %s", msg.id)
            await conn.execute("update public.mail_accounts set last_error = $2 where id = $1", account_id,
                               f"“{msg.subject[:80]}”: {exc}"[:500])
            _attempts[msg.id] = _attempts.get(msg.id, 0) + 1
            if _attempts[msg.id] < MAX_ATTEMPTS:
                break   # stop so this email is retried next scan (e.g. the AI service was briefly down)
            # Give up on this one email after repeated failures so it can't block the inbox; keep a record of it.
            await conn.execute(
                """insert into public.email_messages (tenant_id, mail_account_id, provider_message_id, from_address,
                   from_name, subject, received_at, error, processed_at) values ($1,$2,$3,$4,$5,$6,$7,$8,now())
                   on conflict (mail_account_id, provider_message_id) do nothing""",
                tenant_id, account_id, msg.id, msg.from_address, msg.from_name, msg.subject, msg.received_at,
                str(exc)[:500])
            _attempts.pop(msg.id, None)
            latest = max(latest, msg.received_at)
    await conn.execute(
        "update public.mail_accounts set last_sync_at = $2, last_error = case when $3 then null else last_error end "
        "where id = $1", account_id, latest, result.errors == 0)
    return result
