"""Candidate uploads: one-off resume (PDF/DOCX) and bulk (ZIP and/or CSV)."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import CurrentUser, get_current_user
from ..db import user_tx
from ..llm import LLMProvider, get_provider
from ..services import bulk_import as bi
from ..services.candidates import candidate_from_resume, upsert_candidate
from ..services.storage import Storage, get_storage
from ..services.text_extract import SUPPORTED

router = APIRouter(prefix="/tenants/{tenant_id}/candidates", tags=["uploads"])
MAX_FILE = 20 * 1024 * 1024
MAX_ZIP = 300 * 1024 * 1024


async def tenant_llm(conn, tenant_id: UUID) -> LLMProvider:
    st = await conn.fetchrow(
        "select llm_provider, llm_model, llm_base_url from public.tenant_settings where tenant_id = $1", tenant_id)
    return get_provider(st["llm_provider"], st["llm_model"], st["llm_base_url"]) if st else get_provider()


def llm_dep() -> LLMProvider | None:
    return None  # resolved per tenant inside the handler; overridable in tests


@router.post("/upload", status_code=201)
async def upload_resume(tenant_id: UUID, file: UploadFile = File(...), job_id: UUID | None = Form(None),
                        user: CurrentUser = Depends(get_current_user), storage: Storage = Depends(get_storage),
                        llm_override: LLMProvider | None = Depends(llm_dep)) -> dict:
    """One resume → parsed candidate (merged into an existing one if the email matches). Optionally linked to a job."""
    name = file.filename or "resume"
    if not any(name.lower().endswith(ext) for ext in SUPPORTED):
        raise HTTPException(415, "Upload a PDF, DOCX or TXT resume")
    data = await file.read()
    if len(data) > MAX_FILE:
        raise HTTPException(413, "File larger than 20 MB")
    async with user_tx(user.id) as conn:
        llm = llm_override or await tenant_llm(conn, tenant_id)
        result = await candidate_from_resume(conn, storage, llm, tenant_id, name, data, source="manual")
        if job_id:
            await conn.execute(
                """insert into public.applications (tenant_id, candidate_id, job_id, stage_id, source)
                   select $1, $2, j.id, (select st.id from public.pipeline_stages st join public.pipelines p
                        on p.id = st.pipeline_id where p.tenant_id = $1 and (p.id = j.pipeline_id or
                        (j.pipeline_id is null and p.is_default)) order by st.position limit 1), 'manual'
                   from public.jobs j where j.tenant_id = $1 and j.id = $3
                   on conflict (candidate_id, job_id) do nothing""", tenant_id, result["candidate"]["id"], job_id)
        return result


@router.post("/bulk-import", status_code=201)
async def bulk_import(tenant_id: UUID, zip_file: UploadFile | None = File(None), csv_file: UploadFile | None = File(None),
                      parse_unmatched: bool = Form(True), user: CurrentUser = Depends(get_current_user),
                      storage: Storage = Depends(get_storage),
                      llm_override: LLMProvider | None = Depends(llm_dep)) -> dict:
    """ZIP of resumes and/or a CSV. CSV rows are matched to files by a resume_file column, else by name."""
    if not zip_file and not csv_file:
        raise HTTPException(422, "Send a zip_file, a csv_file, or both")
    files, skipped = [], []
    if zip_file:
        data = await zip_file.read()
        if len(data) > MAX_ZIP:
            raise HTTPException(413, "ZIP larger than 300 MB; split it into smaller batches")
        files, skipped = bi.read_zip(data)
    rows = bi.read_csv(await csv_file.read()) if csv_file else None
    plan = bi.plan_import(files, rows, parse_unmatched=parse_unmatched)
    kind = "zip_csv" if zip_file and csv_file else ("zip" if zip_file else "csv")

    report: list[dict] = [{"file": s["file"], "status": "skipped", "reason": s["reason"]} for s in skipped]
    created = updated = errors = 0
    async with user_tx(user.id) as conn:
        batch_id = await conn.fetchval(
            "insert into public.import_batches (tenant_id, kind, total, created_by) values ($1,$2,$3,$4) returning id",
            tenant_id, kind, len(plan.rows), user.id)
        llm = llm_override or await tenant_llm(conn, tenant_id)
        for row in plan.rows:
            label = row.resume.name if row.resume else f"{row.fields.get('first_name', '')} {row.fields.get('last_name', '')}".strip()
            try:
                async with conn.transaction():   # savepoint: one bad row doesn't sink the batch
                    if row.resume:
                        res = await candidate_from_resume(conn, storage, llm, tenant_id, row.resume.name,
                                                          row.resume.data, source="import", known_fields=row.fields)
                        cand, was_created = res["candidate"], res["created"]
                    else:
                        cand, was_created = await upsert_candidate(conn, tenant_id, row.fields, source="import")
                created += was_created
                updated += not was_created
                report.append({"item": label, "status": "created" if was_created else "updated",
                               "candidate_id": str(cand["id"]), "match": row.match,
                               "match_score": row.match_score, "warnings": row.warnings})
            except Exception as exc:  # noqa: BLE001 — reported per row
                errors += 1
                report.append({"item": label, "status": "error", "error": str(exc)[:300], "warnings": row.warnings})
        status = "completed" if errors == 0 and not skipped else ("failed" if created + updated == 0 else "completed_with_errors")
        await conn.execute(
            """update public.import_batches set status=$2, created_count=$3, updated_count=$4, error_count=$5,
               report=$6, finished_at=$7 where id=$1""",
            batch_id, status, created, updated, errors + len(skipped), report, datetime.now(timezone.utc))
    return {"batch_id": str(batch_id), "status": status, "created": created, "updated": updated,
            "errors": errors, "skipped": len(skipped), "report": report}
