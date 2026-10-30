"""Creating candidates from resumes (one-off upload, bulk import, email agent, portal all share this)."""
from __future__ import annotations

import mimetypes
import re
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from ..agent.prompts import RESUME_EXTRACT_SYSTEM
from ..llm import LLMProvider
from .clean import nul_free
from .storage import Storage
from .text_extract import extract_text

CANDIDATE_FIELDS = {
    "first_name", "last_name", "email", "phone", "linkedin_url", "location", "city", "region", "country",
    "current_title", "current_company", "years_experience", "skills", "systems", "certifications", "summary",
    "work_authorization", "source_detail",
}
LIST_FIELDS = {"skills", "systems", "certifications"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def clean_fields(raw: dict[str, Any]) -> dict[str, Any]:
    raw = nul_free(raw)
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in CANDIDATE_FIELDS or v in (None, "", []):
            continue
        if k in LIST_FIELDS and isinstance(v, str):
            v = [x.strip() for x in re.split(r"[;,|]", v) if x.strip()]
        if k == "email":
            m = EMAIL_RE.search(str(v))
            if not m:
                continue
            v = m.group(0).lower()
        if k == "years_experience":
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
        out[k] = v
    return out


async def parse_resume(llm: LLMProvider, text: str) -> dict[str, Any]:
    data, _ = await llm.complete_json(RESUME_EXTRACT_SYSTEM, f"Resume text:\n\n{text[:30000]}")
    return data


async def upsert_candidate(conn: asyncpg.Connection, tenant_id: UUID, fields: dict[str, Any], *,
                           source: str, existing_id: UUID | None = None) -> tuple[dict, bool]:
    """Insert, or fill blanks on an existing candidate (the one given, else the one with the same email).
    Returns (row, created)."""
    fields = clean_fields(fields)
    if not fields.get("first_name"):
        fields["first_name"] = (fields.get("email") or "Unknown").split("@")[0]
    existing = None
    if existing_id:
        existing = await conn.fetchrow("select * from public.candidates where tenant_id = $1 and id = $2",
                                       tenant_id, existing_id)
        if existing is None:
            raise ValueError("The candidate to merge into no longer exists")
    elif fields.get("email"):
        existing = await conn.fetchrow(
            "select * from public.candidates where tenant_id = $1 and email = $2", tenant_id, fields["email"])
    if existing:
        updates = {k: v for k, v in fields.items() if existing[k] in (None, "", [])}
        merged_lists = {k: sorted(set(existing[k] or []) | set(fields.get(k) or [])) for k in LIST_FIELDS}
        updates.update({k: v for k, v in merged_lists.items() if v != sorted(existing[k] or [])})
        if updates:
            sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(updates, start=2))
            existing = await conn.fetchrow(
                f"update public.candidates set {sets} where id = $1 returning *", existing["id"], *updates.values())
        return dict(existing), False
    cols = list(fields) + ["tenant_id", "source"]
    vals = list(fields.values()) + [tenant_id, source]
    row = await conn.fetchrow(
        f"insert into public.candidates ({', '.join(cols)}) values ({', '.join(f'${i}' for i in range(1, len(cols) + 1))}) returning *",
        *vals)
    return dict(row), True


async def attach_document(conn: asyncpg.Connection, storage: Storage, tenant_id: UUID, candidate_id: UUID,
                          file_name: str, data: bytes, text: str | None, kind: str = "resume",
                          uploaded_by: UUID | None = None) -> dict:
    safe = re.sub(r"[^\w.\-]+", "_", file_name)
    path = f"{tenant_id}/candidates/{candidate_id}/{uuid4().hex[:8]}_{safe}"
    mime = mimetypes.guess_type(file_name)[0]
    await storage.put(path, data, mime)
    if kind == "resume":   # the newest resume is the one shown on the profile
        await conn.execute("update public.candidate_documents set is_primary = false where candidate_id = $1 and is_primary",
                           candidate_id)
    row = await conn.fetchrow(
        """insert into public.candidate_documents (tenant_id, candidate_id, kind, file_name, storage_path, mime_type,
                                                   size_bytes, extracted_text, is_primary, uploaded_by)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) returning id, file_name, storage_path, is_primary, uploaded_by""",
        tenant_id, candidate_id, kind, file_name, path, mime, len(data), text, kind == "resume", uploaded_by)
    return dict(row)


async def candidate_from_resume(conn: asyncpg.Connection, storage: Storage, llm: LLMProvider | None,
                                tenant_id: UUID, file_name: str, data: bytes, *, source: str,
                                known_fields: dict[str, Any] | None = None, uploaded_by: UUID | None = None,
                                existing_id: UUID | None = None) -> dict:
    """Extract → parse → upsert → store file. Known fields (e.g. from a CSV or portal form) win over parsed ones."""
    text = extract_text(file_name, data)
    parsed: dict[str, Any] = {}
    if llm is not None and text:
        parsed = await parse_resume(llm, text)
    fields = {**clean_fields(parsed), **clean_fields(known_fields or {})}
    if not fields.get("email") and (m := EMAIL_RE.search(text)):
        fields["email"] = m.group(0)
    if existing_id and fields.get("email"):
        # Uploading to a chosen candidate: don't take an email that already belongs to someone else.
        if await conn.fetchval("select exists(select 1 from public.candidates where tenant_id = $1 and email = $2 "
                               "and id <> $3)", tenant_id, fields["email"], existing_id):
            fields.pop("email")
    candidate, created = await upsert_candidate(conn, tenant_id, fields, source=source, existing_id=existing_id)
    doc = await attach_document(conn, storage, tenant_id, candidate["id"], file_name, data, text, uploaded_by=uploaded_by)
    candidate.pop("embedding", None)
    return {"candidate": candidate, "created": created, "document": doc,
            "parse_confidence": parsed.get("confidence")}
