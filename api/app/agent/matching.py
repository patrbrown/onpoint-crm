"""Find existing records an inbox item probably refers to, so approving it links instead of duplicating."""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

import asyncpg
from rapidfuzz import fuzz

FREE_MAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "live.com", "msn.com",
             "protonmail.com", "proton.me", "aol.com", "shaw.ca", "telus.net", "rogers.com", "me.com"}


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


async def candidate_matches(conn: asyncpg.Connection, tenant_id: UUID, fields: dict[str, Any]) -> list[dict]:
    """Same email → certain. Same name (+phone) → likely."""
    out: list[dict] = []
    if fields.get("email"):
        r = await conn.fetchrow("select id, first_name, last_name, email, current_title from public.candidates "
                                "where tenant_id = $1 and email = $2", tenant_id, fields["email"].lower())
        if r:
            out.append({"type": "candidate", "id": str(r["id"]), "label": f"{r['first_name']} {r['last_name'] or ''}".strip(),
                        "detail": r["current_title"], "reason": "same email", "score": 100})
    name = _norm(f"{fields.get('first_name', '')} {fields.get('last_name', '') or ''}")
    if name and not out:
        rows = await conn.fetch("select id, first_name, last_name, email, current_title from public.candidates "
                                "where tenant_id = $1 and lower(first_name) = $2 limit 50", tenant_id,
                                _norm(fields.get("first_name")))
        for r in rows:
            score = fuzz.token_sort_ratio(name, _norm(f"{r['first_name']} {r['last_name'] or ''}"))
            if score >= 90:
                out.append({"type": "candidate", "id": str(r["id"]), "label": f"{r['first_name']} {r['last_name'] or ''}".strip(),
                            "detail": r["email"], "reason": "same name", "score": int(score)})
    return out


async def job_mentions(conn: asyncpg.Connection, tenant_id: UUID, text: str, limit: int = 3) -> list[dict]:
    """Open jobs whose title or req number appears in an email (e.g. a resume sent 'for the Epic analyst role')."""
    text_n = _norm(text)[:4000]
    rows = await conn.fetch("select id, title, reference_code from public.jobs where tenant_id = $1 "
                            "and status in ('open','on_hold')", tenant_id)
    scored = []
    for r in rows:
        if r["reference_code"] and _norm(r["reference_code"]) in text_n:
            scored.append((100, r, "req number in email"))
            continue
        s = fuzz.partial_ratio(_norm(r["title"]), text_n)
        if s >= 85:
            scored.append((s, r, "job title in email"))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"type": "job", "id": str(r["id"]), "label": r["title"], "reason": why, "score": int(s)}
            for s, r, why in scored[:limit]]


async def client_matches(conn: asyncpg.Connection, tenant_id: UUID, client_name: str | None,
                         sender_email: str | None) -> list[dict]:
    out: list[dict] = []
    if sender_email:
        r = await conn.fetchrow(
            """select cc.id as contact_id, cc.first_name, cc.last_name, c.id, c.name from public.client_contacts cc
               join public.clients c on c.id = cc.client_id where cc.tenant_id = $1 and cc.email = $2""",
            tenant_id, sender_email)
        if r:
            out.append({"type": "client", "id": str(r["id"]), "label": r["name"], "contact_id": str(r["contact_id"]),
                        "contact_label": f"{r['first_name']} {r['last_name'] or ''}".strip(),
                        "reason": "sender is a known contact", "score": 100})
            return out
    domain = (sender_email or "").split("@")[-1]
    clients = await conn.fetch("select id, name, website from public.clients where tenant_id = $1", tenant_id)
    for c in clients:
        score, why = 0, ""
        if client_name:
            score, why = fuzz.token_set_ratio(_norm(client_name), _norm(c["name"])), "same client name"
        if domain and domain not in FREE_MAIL and c["website"] and domain in c["website"].lower():
            score, why = 100, "sender's email domain matches the client website"
        if score >= 88:
            out.append({"type": "client", "id": str(c["id"]), "label": c["name"], "reason": why, "score": int(score)})
    return sorted(out, key=lambda x: x["score"], reverse=True)[:3]


async def duplicate_jobs(conn: asyncpg.Connection, tenant_id: UUID, title: str | None, ref: str | None,
                         client_ids: list[str]) -> list[dict]:
    rows = await conn.fetch("select id, title, reference_code, client_id from public.jobs where tenant_id = $1 "
                            "and status not in ('closed','cancelled','filled')", tenant_id)
    out = []
    for r in rows:
        if ref and r["reference_code"] and _norm(ref) == _norm(r["reference_code"]):
            out.append({"type": "job", "id": str(r["id"]), "label": r["title"], "reason": "same req number", "score": 100})
        elif title and fuzz.token_sort_ratio(_norm(title), _norm(r["title"])) >= 90 and (
                not client_ids or str(r["client_id"]) in client_ids):
            out.append({"type": "job", "id": str(r["id"]), "label": r["title"], "reason": "same title, same client", "score": 90})
    return out[:3]


async def application_matches(conn: asyncpg.Connection, tenant_id: UUID, candidate_name: str | None,
                              candidate_email: str | None, job_title: str | None) -> list[dict]:
    rows = await conn.fetch(
        """select a.id, c.first_name, c.last_name, c.email, j.title from public.applications a
           join public.candidates c on c.id = a.candidate_id join public.jobs j on j.id = a.job_id
           where a.tenant_id = $1 and j.status not in ('closed','cancelled')""", tenant_id)
    out = []
    for r in rows:
        name = f"{r['first_name']} {r['last_name'] or ''}".strip()
        s_name = 100 if candidate_email and r["email"] == candidate_email.lower() else (
            fuzz.token_sort_ratio(_norm(candidate_name), _norm(name)) if candidate_name else 0)
        if s_name < 85:
            continue
        s_job = fuzz.token_set_ratio(_norm(job_title), _norm(r["title"])) if job_title else 60
        score = int(0.7 * s_name + 0.3 * s_job)
        out.append({"type": "application", "id": str(r["id"]), "label": f"{name}, {r['title']}",
                    "reason": "candidate on this job", "score": score})
    return sorted(out, key=lambda x: x["score"], reverse=True)[:5]
