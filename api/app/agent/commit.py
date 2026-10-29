"""Turning an approved inbox item into real CRM records. Used both when the recruiter approves an item
and when automatic mode approves a confident one, so the two paths always behave the same."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException

from ..services.candidates import upsert_candidate

JOB_ENUMS = {
    "work_model": {"onsite", "hybrid", "remote"},
    "employment_type": {"permanent", "contract", "contract_to_hire", "temporary"},
    "rate_unit": {"hour", "day", "month", "year"},
    "priority": {"low", "normal", "high", "urgent"},
}
JOB_TEXT = ("title", "reference_code", "description", "location", "city", "region", "country", "currency")
JOB_NUM = ("salary_min", "salary_max", "rate_min", "rate_max")
JOB_LISTS = ("must_have_skills", "nice_to_have_skills", "systems", "certifications")
RECS = {"strong_yes", "yes", "maybe", "no", "strong_no"}


def _num(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v).replace(",", "").replace("$", ""))
    except InvalidOperation:
        return None


def clean_job(f: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in JOB_TEXT:
        if f.get(k):
            out[k] = str(f[k]).strip()
    if out.get("currency"):
        out["currency"] = out["currency"].upper()[:3]
    for k in JOB_NUM:
        if (n := _num(f.get(k))) is not None:
            out[k] = n
    for k, allowed in JOB_ENUMS.items():
        if f.get(k) in allowed:
            out[k] = f[k]
    for k in JOB_LISTS:
        v = f.get(k) or []
        out[k] = [str(x).strip() for x in (v if isinstance(v, list) else str(v).split(",")) if str(x).strip()]
    if f.get("openings"):
        try:
            out["openings"] = max(1, int(f["openings"]))
        except (TypeError, ValueError):
            pass
    if not out.get("title"):
        raise HTTPException(422, "A job needs a title")
    return out


async def _first_stage(conn: asyncpg.Connection, tenant_id: UUID, job_id: UUID) -> UUID | None:
    return await conn.fetchval(
        """select st.id from public.jobs j join public.pipelines p on p.tenant_id = j.tenant_id
             and (p.id = j.pipeline_id or (j.pipeline_id is null and p.is_default))
           join public.pipeline_stages st on st.pipeline_id = p.id
           where j.tenant_id = $1 and j.id = $2 order by st.position limit 1""", tenant_id, job_id)


async def commit_job(conn: asyncpg.Connection, tenant_id: UUID, item: asyncpg.Record, final: dict, links: dict,
                     sender: dict) -> tuple[str, UUID]:
    job = clean_job(final)
    # Client: chosen, or found by exact name, or created.
    client_id = links.get("client_id")
    name = (final.get("client_name") or "").strip()
    if not client_id and name:
        client_id = await conn.fetchval("select id from public.clients where tenant_id = $1 and lower(name) = lower($2)",
                                        tenant_id, name)
        if not client_id:
            client_id = await conn.fetchval("insert into public.clients (tenant_id, name, status) values ($1, $2, 'active') "
                                            "returning id", tenant_id, name)
    # Hiring contact: chosen, or the person named in the req, or the sender.
    contact_id = links.get("contact_id")
    hc = final.get("hiring_contact") or {}
    email = (hc.get("email") or sender.get("address") or "").lower() or None
    person = hc.get("name") or (sender.get("name") if email == (sender.get("address") or "").lower() else None)
    if not contact_id and client_id and email:
        contact_id = await conn.fetchval("select id from public.client_contacts where tenant_id = $1 and email = $2",
                                         tenant_id, email)
        if not contact_id:
            first, _, last = (person or email.split("@")[0]).partition(" ")
            contact_id = await conn.fetchval(
                """insert into public.client_contacts (tenant_id, client_id, first_name, last_name, email, phone, title,
                   is_hiring_manager) values ($1,$2,$3,$4,$5,$6,$7,true) returning id""",
                tenant_id, client_id, first, last or None, email, hc.get("phone"), hc.get("title"))
    job.update({"tenant_id": tenant_id, "client_id": client_id, "hiring_contact_id": contact_id,
                "source": "email", "source_email_id": item["email_id"], "status": "open"})
    cols = list(job)
    job_id = await conn.fetchval(
        f"insert into public.jobs ({', '.join(cols)}) values ({', '.join(f'${i}' for i in range(1, len(cols) + 1))}) returning id",
        *job.values())
    return "job", job_id


async def commit_resume(conn: asyncpg.Connection, tenant_id: UUID, item: asyncpg.Record, final: dict,
                        links: dict) -> tuple[str, UUID]:
    existing = UUID(str(links["candidate_id"])) if links.get("candidate_id") else None  # merge into this one
    try:
        cand, _ = await upsert_candidate(conn, tenant_id, final, source="email", existing_id=existing)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    cand_id = cand["id"]
    att_id = (item["extracted"] or {}).get("_attachment_id")
    if att_id:
        att = await conn.fetchrow("select file_name, storage_path, mime_type, size_bytes, extracted_text "
                                  "from public.email_attachments where tenant_id = $1 and id = $2", tenant_id, UUID(att_id))
        if att and att["storage_path"]:
            has_primary = await conn.fetchval(
                "select exists(select 1 from public.candidate_documents where candidate_id = $1 and is_primary)", cand_id)
            await conn.execute(
                """insert into public.candidate_documents (tenant_id, candidate_id, kind, file_name, storage_path, mime_type,
                   size_bytes, extracted_text, is_primary) values ($1,$2,'resume',$3,$4,$5,$6,$7,$8)""",
                tenant_id, cand_id, att["file_name"], att["storage_path"], att["mime_type"], att["size_bytes"],
                att["extracted_text"], not has_primary)
    if links.get("job_id"):
        job_id = UUID(str(links["job_id"]))
        await conn.execute(
            """insert into public.applications (tenant_id, candidate_id, job_id, stage_id, source)
               values ($1, $2, $3, $4, 'email') on conflict (candidate_id, job_id) do nothing""",
            tenant_id, cand_id, job_id, await _first_stage(conn, tenant_id, job_id))
    return "candidate", cand_id


async def commit_feedback(conn: asyncpg.Connection, tenant_id: UUID, item: asyncpg.Record, final: dict,
                          links: dict) -> tuple[str, UUID]:
    app_id = links.get("application_id")
    if not app_id:
        raise HTTPException(422, "Choose which candidate and job this feedback is for")
    rating = final.get("overall_rating")
    rating = int(rating) if str(rating or "").isdigit() and 1 <= int(rating) <= 5 else None
    scorecard = [{"criterion": str(s.get("criterion", ""))[:200], "rating": int(s["rating"]), "comment": s.get("comment")}
                 for s in final.get("scorecard") or []
                 if s.get("criterion") and str(s.get("rating", "")).isdigit() and 1 <= int(s["rating"]) <= 5]
    contact_id = None
    if final.get("from_email"):
        contact_id = await conn.fetchval("select id from public.client_contacts where tenant_id = $1 and email = $2",
                                         tenant_id, final["from_email"].lower())
    fid = await conn.fetchval(
        """insert into public.interview_feedback (tenant_id, application_id, from_contact_id, from_name, overall_rating,
           recommendation, scorecard, strengths, concerns, notes, source, source_email_id)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'email',$11) returning id""",
        tenant_id, UUID(str(app_id)), contact_id, final.get("from_name"), rating,
        final.get("recommendation") if final.get("recommendation") in RECS else None, scorecard,
        final.get("strengths"), final.get("concerns"), final.get("notes"), item["email_id"])
    return "interview_feedback", fid


async def commit_item(conn: asyncpg.Connection, tenant_id: UUID, item: asyncpg.Record, final: dict, links: dict,
                      *, reviewer: UUID | None, auto: bool = False) -> dict:
    if item["status"] not in ("pending",):
        raise HTTPException(409, f"This item was already {item['status'].replace('_', ' ')}")
    sender = {}
    if item["email_id"]:
        e = await conn.fetchrow("select from_address, from_name from public.email_messages where id = $1", item["email_id"])
        sender = {"address": e["from_address"], "name": e["from_name"]} if e else {}
    kind = item["item_type"]
    if kind == "job_requisition":
        etype, eid = await commit_job(conn, tenant_id, item, final, links, sender)
    elif kind == "resume":
        etype, eid = await commit_resume(conn, tenant_id, item, final, links)
    elif kind == "interview_feedback":
        etype, eid = await commit_feedback(conn, tenant_id, item, final, links)
    else:
        raise HTTPException(422, f"Can't approve items of type {kind}")
    await conn.execute(
        """update public.inbox_items set status = $2, final = $3, created_entity_type = $4, created_entity_id = $5,
           reviewed_by = $6, reviewed_at = $7 where id = $1""",
        item["id"], "auto_approved" if auto else "approved", {**final, "_links": links}, etype, eid, reviewer,
        datetime.now(timezone.utc))
    return {"entity_type": etype, "entity_id": str(eid)}
