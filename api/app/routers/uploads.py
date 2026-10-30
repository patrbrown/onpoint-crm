"""Candidate uploads: one-off resume (PDF/DOCX) and bulk (ZIP and/or CSV)."""

import asyncio
import logging
import zipfile
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from .. import crud
from ..auth import CurrentUser, get_current_user
from ..config import get_settings
from ..db import service_tx, user_tx
from ..errors import explain
from ..llm import LLMProvider
from ..llm.tenant import llm_for_task
from ..services import bulk_import as bi
from ..services.candidates import candidate_from_resume, upsert_candidate
from ..services.storage import Storage, get_storage
from ..services.text_extract import SUPPORTED
from .team import check_member, my_member_id

router = APIRouter(prefix="/tenants/{tenant_id}/candidates", tags=["uploads"])
log = logging.getLogger("uploads")
MAX_FILE = 20 * 1024 * 1024
MAX_ZIP = 300 * 1024 * 1024


async def tenant_llm(conn, tenant_id: UUID) -> LLMProvider:
    return await llm_for_task(conn, tenant_id, "resume_parsing")


def llm_dep() -> LLMProvider | None:
    return None  # resolved per tenant inside the handler; overridable in tests


@router.post("/upload", status_code=201)
async def upload_resume(tenant_id: UUID, file: UploadFile = File(...), job_id: UUID | None = Form(None),
                        candidate_id: UUID | None = Form(None), uploaded_by: UUID | None = Form(None),
                        user: CurrentUser = Depends(get_current_user), storage: Storage = Depends(get_storage),
                        llm_override: LLMProvider | None = Depends(llm_dep)) -> dict:
    """One resume → parsed candidate (merged into an existing one if the email matches, or into `candidate_id`).
    Optionally linked to a job. `uploaded_by` is the team member who uploaded it (default: you)."""
    name = file.filename or "resume"
    if not any(name.lower().endswith(ext) for ext in SUPPORTED):
        raise HTTPException(415, "Upload a PDF, DOCX or TXT resume")
    data = await file.read()
    if len(data) > MAX_FILE:
        raise HTTPException(413, "File larger than 20 MB")
    async with user_tx(user.id) as conn:
        llm = llm_override or await tenant_llm(conn, tenant_id)
        by = await check_member(conn, tenant_id, uploaded_by) or await my_member_id(conn, tenant_id, user.id)
        if candidate_id:
            await crud.get_row(conn, "candidates", tenant_id, candidate_id)   # 404 if not this workspace's
        try:
            result = await candidate_from_resume(conn, storage, llm, tenant_id, name, data, source="manual",
                                                 uploaded_by=by, existing_id=candidate_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if job_id:
            await conn.execute(
                """insert into public.applications (tenant_id, candidate_id, job_id, stage_id, source)
                   select $1, $2, j.id, (select st.id from public.pipeline_stages st join public.pipelines p
                        on p.id = st.pipeline_id where p.tenant_id = $1 and (p.id = j.pipeline_id or
                        (j.pipeline_id is null and p.is_default)) order by st.position limit 1), 'manual'
                   from public.jobs j where j.tenant_id = $1 and j.id = $3
                   on conflict (candidate_id, job_id) do nothing""", tenant_id, result["candidate"]["id"], job_id)
        return result


_running: set[asyncio.Task] = set()   # keep references so background imports aren't garbage-collected


@router.post("/bulk-import", status_code=202)
async def bulk_import(tenant_id: UUID, zip_file: UploadFile | None = File(None), csv_file: UploadFile | None = File(None),
                      parse_unmatched: bool = Form(True), uploaded_by: UUID | None = Form(None), user: CurrentUser = Depends(get_current_user),
                      storage: Storage = Depends(get_storage),
                      llm_override: LLMProvider | None = Depends(llm_dep)) -> dict:
    """ZIP of resumes and/or a CSV. Starts the import in the background and returns straight away;
    follow progress with GET /candidates/imports/{batch_id}. Each candidate is saved as soon as it's read."""
    if not zip_file and not csv_file:
        raise HTTPException(422, "Send a zip_file, a csv_file, or both")
    files, skipped = [], []
    if zip_file:
        data = await zip_file.read()
        if len(data) > MAX_ZIP:
            raise HTTPException(413, "ZIP larger than 300 MB; split it into smaller batches")
        try:
            files, skipped = bi.read_zip(data)
        except zipfile.BadZipFile as exc:
            raise HTTPException(422, "That file isn't a readable ZIP. Re-create it (right-click → Send to → "
                                     "Compressed (zipped) folder) and try again.") from exc
    rows = bi.read_csv(await csv_file.read()) if csv_file else None
    plan = bi.plan_import(files, rows, parse_unmatched=parse_unmatched)
    if not plan.rows and not skipped:
        raise HTTPException(422, "Nothing to import: no PDF, Word or text resumes in the ZIP and no CSV rows")
    kind = "zip_csv" if zip_file and csv_file else ("zip" if zip_file else "csv")
    report = [{"item": s["file"], "status": "skipped", "reason": s["reason"]} for s in skipped]

    async with user_tx(user.id) as conn:   # committed now, so progress is visible straight away
        by = await check_member(conn, tenant_id, uploaded_by) or await my_member_id(conn, tenant_id, user.id)
        batch_id = await conn.fetchval(
            """insert into public.import_batches (tenant_id, kind, total, error_count, report, created_by, uploaded_by)
               values ($1,$2,$3,$4,$5,$6,$7) returning id""",
            tenant_id, kind, len(plan.rows), len(skipped), report, user.id, by)
        llm = llm_override or await tenant_llm(conn, tenant_id)
    task = asyncio.create_task(_run_import(batch_id, tenant_id, user.id, plan, storage, llm, len(skipped), by))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return {"batch_id": str(batch_id), "status": "processing", "total": len(plan.rows), "skipped": len(skipped)}


async def _run_import(batch_id: UUID, tenant_id: UUID, user_id: UUID, plan: bi.ImportPlan, storage: Storage,
                      llm: LLMProvider, skipped: int, uploaded_by: UUID | None = None) -> None:
    sem = asyncio.Semaphore(max(1, get_settings().bulk_import_concurrency))
    counts = {"created": 0, "updated": 0, "errors": 0}

    async def one(row: bi.ImportRow) -> None:
        label = row.resume.name if row.resume else f"{row.fields.get('first_name', '')} {row.fields.get('last_name', '')}".strip()
        async with sem:
            try:
                async with user_tx(user_id) as conn:   # each candidate is its own transaction
                    if row.resume:
                        res = await candidate_from_resume(conn, storage, llm, tenant_id, row.resume.name,
                                                          row.resume.data, source="import", known_fields=row.fields,
                                                          uploaded_by=uploaded_by)
                        cand, was_created = res["candidate"], res["created"]
                    else:
                        cand, was_created = await upsert_candidate(conn, tenant_id, row.fields, source="import")
                entry = {"item": label, "status": "created" if was_created else "updated", "candidate_id": str(cand["id"]),
                         "match": row.match, "match_score": row.match_score, "warnings": row.warnings}
                counts["created" if was_created else "updated"] += 1
            except Exception as exc:  # noqa: BLE001 — reported per row
                log.warning("bulk import %s: %s failed: %s", batch_id, label, exc)
                entry = {"item": label, "status": "error", "error": explain(exc)[1][:300], "warnings": row.warnings}
                counts["errors"] += 1
            # Add to the counters in the database (not from a local total): imports run several resumes at once,
            # and two updates writing their own totals could overwrite each other.
            async with service_tx() as conn:
                await conn.execute(
                    """update public.import_batches set created_count = created_count + $2,
                       updated_count = updated_count + $3, error_count = error_count + $4,
                       report = report || $5::jsonb where id = $1""",
                    batch_id, int(entry["status"] == "created"), int(entry["status"] == "updated"),
                    int(entry["status"] == "error"), [entry])

    try:
        await asyncio.gather(*(one(r) for r in plan.rows))
        done = counts["created"] + counts["updated"]
        status = ("completed" if counts["errors"] == 0 and not skipped
                  else "failed" if done == 0 and plan.rows else "completed_with_errors")
    except Exception:  # noqa: BLE001
        log.exception("bulk import %s stopped", batch_id)
        status = "failed"
    async with service_tx() as conn:
        await conn.execute("update public.import_batches set status = $2, finished_at = now() where id = $1",
                           batch_id, status)


@router.get("/imports")
async def list_imports(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select b.id, b.kind, b.status, b.total, b.created_count, b.updated_count, b.error_count, b.created_at,
                      b.finished_at, tm.full_name as uploaded_by_name
               from public.import_batches b left join public.team_members tm on tm.id = b.uploaded_by
               where b.tenant_id = $1 order by b.created_at desc limit 20""", tenant_id)
    return [dict(r) for r in rows]


@router.get("/imports/{batch_id}")
async def get_import(tenant_id: UUID, batch_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        r = await conn.fetchrow("select * from public.import_batches where tenant_id = $1 and id = $2", tenant_id, batch_id)
    if r is None:
        raise HTTPException(404, "import not found")
    return dict(r)


async def mark_interrupted_imports() -> None:
    """At start-up: imports that were running when the CRM stopped can't resume; say so instead of 'processing' forever."""
    async with service_tx() as conn:
        await conn.execute(
            """update public.import_batches set status = 'failed', finished_at = now(),
               report = report || '[{"item": "Import stopped", "status": "error",
                 "error": "The CRM was restarted before this import finished. Run it again: resumes already imported are updated, not duplicated."}]'::jsonb
               where status = 'processing'""")
