"""Fill a job's description from a JD file: an attachment on the email the job came from, or an uploaded file.
Both return a Markdown preview; saving goes through the normal job update."""
from pathlib import PurePath
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..auth import CurrentUser, get_current_user
from ..db import user_tx
from ..services import jd_markdown
from ..services.storage import Storage, get_storage

router = APIRouter(prefix="/tenants/{tenant_id}/jobs/{job_id}", tags=["job descriptions"])


@router.get("/jd-sources")
async def jd_sources(tenant_id: UUID, job_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Attachments on the email this job was created from (newest emails in the same thread included)."""
    async with user_tx(user.id) as conn:
        job = await conn.fetchrow("select source_email_id from public.jobs where tenant_id = $1 and id = $2", tenant_id, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        rows = []
        if job["source_email_id"]:
            rows = await conn.fetch(
                """select a.id, a.file_name, a.size_bytes, e.subject, e.received_at
                   from public.email_attachments a join public.email_messages e on e.id = a.email_id
                   where a.tenant_id = $1
                     and (a.email_id = $2 or e.conversation_id = (select conversation_id from public.email_messages
                                                                   where id = $2))
                   order by e.received_at desc""", tenant_id, job["source_email_id"])
    out = [dict(r) for r in rows if PurePath(r["file_name"]).suffix.lower() in jd_markdown.CONVERTIBLE]
    suggested = jd_markdown.pick_jd_attachments([r["file_name"] for r in out])
    for r in out:
        r["suggested"] = r["file_name"] in suggested
    return {"attachments": out}


@router.post("/jd-preview/attachment/{attachment_id}")
async def preview_from_attachment(tenant_id: UUID, job_id: UUID, attachment_id: UUID,
                                  user: CurrentUser = Depends(get_current_user),
                                  storage: Storage = Depends(get_storage)) -> dict:
    async with user_tx(user.id) as conn:
        a = await conn.fetchrow("select file_name, storage_path, markdown from public.email_attachments "
                                "where tenant_id = $1 and id = $2", tenant_id, attachment_id)
    if a is None:
        raise HTTPException(404, "attachment not found")
    if a["markdown"]:
        return {"markdown": a["markdown"], "file_name": a["file_name"]}
    try:
        md = jd_markdown.to_markdown(a["file_name"], await storage.get(a["storage_path"]))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    async with user_tx(user.id) as conn:
        await conn.execute("update public.email_attachments set markdown = $3 where tenant_id = $1 and id = $2",
                           tenant_id, attachment_id, md)
    return {"markdown": md, "file_name": a["file_name"]}


@router.post("/jd-preview/file")
async def preview_from_file(tenant_id: UUID, job_id: UUID, file: UploadFile = File(...),
                            user: CurrentUser = Depends(get_current_user)) -> dict:
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File larger than 15 MB")
    try:
        md = jd_markdown.to_markdown(file.filename or "jd", data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"markdown": md, "file_name": file.filename}
