"""People who applied on the agency website (the careers page), and the Website settings.

Applications arrive in Supabase directly (careers Edge Function → portal_apply), even while the CRM is off.
When the CRM runs, it reads each new resume (text + AI) to fill in the candidate's details."""
import asyncio
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from ..auth import CurrentUser, get_current_user
from ..config import get_settings
from ..db import service_tx, user_tx
from ..errors import explain
from ..llm.tenant import llm_for_task
from ..schemas import _Base
from ..services.candidates import parse_resume, upsert_candidate
from ..services.storage import get_storage
from ..services.text_extract import extract_text

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["applicants"])
log = logging.getLogger("applicants")


@router.get("/applicants")
async def list_applicants(tenant_id: UUID, only_new: bool = False,
                          user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select a.id, a.candidate_id, a.job_id, coalesce(a.applied_at, a.created_at) as applied_at, a.seen_at,
                      c.first_name, c.last_name, c.email, c.phone, c.current_title, c.location,
                      j.title as job_title, st.name as stage_name,
                      exists(select 1 from public.candidate_documents d where d.candidate_id = c.id and d.needs_parsing)
                          as reading_resume
               from public.applications a
               join public.candidates c on c.id = a.candidate_id
               join public.jobs j on j.id = a.job_id
               left join public.pipeline_stages st on st.id = a.stage_id
               where a.tenant_id = $1 and a.source = 'portal' and (not $2 or a.seen_at is null)
               order by coalesce(a.applied_at, a.created_at) desc limit 500""", tenant_id, only_new)
    return [dict(r) for r in rows]


@router.get("/applicants/count")
async def count_new(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        n = await conn.fetchval("select count(*) from public.applications where tenant_id = $1 "
                                "and source = 'portal' and seen_at is null", tenant_id)
    return {"new": n}


@router.post("/applicants/{application_id}/seen")
async def mark_seen(tenant_id: UUID, application_id: UUID, seen: bool = True,
                    user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        r = await conn.fetchrow(
            "update public.applications set seen_at = case when $3 then coalesce(seen_at, now()) end "
            "where tenant_id = $1 and id = $2 returning id, seen_at", tenant_id, application_id, seen)
    if r is None:
        raise HTTPException(404, "application not found")
    return dict(r)


@router.post("/applicants/seen-all")
async def mark_all_seen(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        res = await conn.execute("update public.applications set seen_at = now() where tenant_id = $1 "
                                 "and source = 'portal' and seen_at is null", tenant_id)
    return {"updated": int(res.split()[-1])}


# ── Website settings ────────────────────────────────────────────────────────

def careers_url() -> str | None:
    base = get_settings().supabase_url.rstrip("/")
    return f"{base}/functions/v1/careers" if base else None


@router.get("/website")
async def website(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        slug = await conn.fetchval("select portal_slug from public.tenants where id = $1", tenant_id)
        consent = await conn.fetchrow("select id, version, body, created_at from public.consent_versions "
                                      "where tenant_id = $1 and is_current", tenant_id)
        posted = await conn.fetch(
            """select j.id, j.title, j.public_description is not null and j.public_description <> '' as has_website_text,
                      c.name as client_name,
                      c.name is not null and position(lower(c.name) in lower(coalesce(nullif(j.public_description, ''),
                          j.description, ''))) > 0 as mentions_client
               from public.jobs j left join public.clients c on c.id = j.client_id
               where j.tenant_id = $1 and j.is_published and j.status = 'open' order by j.published_at desc""", tenant_id)
    return {"site": slug, "careers_url": careers_url(), "consent": dict(consent) if consent else None,
            "posted": [dict(r) for r in posted]}


class ConsentUpdate(_Base):
    body: str = Field(min_length=40, max_length=4000)


@router.put("/website/consent")
async def update_consent(tenant_id: UUID, body: ConsentUpdate, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Saves a new version of the consent text. Earlier versions are kept, so each applicant's record still
    points at the exact wording they agreed to."""
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select public.is_tenant_admin($1)", tenant_id):
            raise HTTPException(403, "Only workspace owners and admins can change the consent text")
        current = await conn.fetchrow("select id, body from public.consent_versions where tenant_id = $1 and is_current",
                                      tenant_id)
        text = body.body.strip()
        if current and current["body"].strip() == text:
            return dict(await conn.fetchrow("select id, version, body, created_at from public.consent_versions "
                                            "where id = $1", current["id"]))
        n = await conn.fetchval("select count(*) from public.consent_versions where tenant_id = $1", tenant_id)
        await conn.execute("update public.consent_versions set is_current = false where tenant_id = $1 and is_current",
                           tenant_id)
        r = await conn.fetchrow(
            """insert into public.consent_versions (tenant_id, version, body, is_current) values ($1, $2, $3, true)
               returning id, version, body, created_at""", tenant_id, f"{n + 1}.0", text)
        return dict(r)


# ── Reading resumes that came in from the website ───────────────────────────

MAX_ATTEMPTS = 3


async def read_pending_resumes(storage=None, llm_for=llm_for_task, limit: int = 10) -> int:
    """Extract text from website resumes and fill in blank candidate details with the AI.
    What the applicant typed (name, email, phone, LinkedIn) is kept; the resume only fills gaps."""
    storage = storage or get_storage()
    async with service_tx() as conn:
        docs = await conn.fetch(
            """select id, tenant_id, candidate_id, file_name, storage_path from public.candidate_documents
               where needs_parsing and parse_attempts < $1 order by created_at limit $2""", MAX_ATTEMPTS, limit)
    done = 0
    for d in docs:
        try:
            data = await storage.get(d["storage_path"])
            text = extract_text(d["file_name"], data)
            if text:   # keep the text even if the AI step below fails, so the resume can be read in the CRM
                async with service_tx() as conn:
                    await conn.execute("update public.candidate_documents set extracted_text = $2 where id = $1",
                                       d["id"], text)
            parsed = {}
            if text:
                async with service_tx() as conn:
                    llm = await llm_for(conn, d["tenant_id"], "resume_parsing")
                parsed = await parse_resume(llm, text)
            async with service_tx() as conn:
                await upsert_candidate(conn, d["tenant_id"], parsed, source="portal", existing_id=d["candidate_id"])
                await conn.execute("update public.candidate_documents set extracted_text = $2, needs_parsing = false, "
                                   "parse_error = null where id = $1", d["id"], text or None)
            done += 1
        except Exception as exc:  # noqa: BLE001 — retried next round, then left for a person
            log.warning("website resume %s: %s", d["id"], exc)
            async with service_tx() as conn:
                await conn.execute(
                    """update public.candidate_documents set parse_attempts = parse_attempts + 1, parse_error = $2,
                       needs_parsing = parse_attempts + 1 < $3 where id = $1""", d["id"], explain(exc)[1][:300], MAX_ATTEMPTS)
    return done


_task: asyncio.Task | None = None


async def _loop() -> None:
    while True:
        try:
            await read_pending_resumes()
        except Exception:  # noqa: BLE001
            log.exception("reading website resumes failed")
        await asyncio.sleep(60)


def start() -> None:
    global _task
    if get_settings().portal_worker_enabled and _task is None:
        _task = asyncio.create_task(_loop())


def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
