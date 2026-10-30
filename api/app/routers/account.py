"""Who am I, which workspaces can I use, and per-workspace settings."""
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from fastapi.responses import Response

from ..auth import CurrentUser, get_current_user
from ..db import user_tx
from ..schemas import _Base
from ..services.storage import Storage, get_storage

router = APIRouter(tags=["account"])


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        profile = await conn.fetchrow("select id, full_name, email, is_platform_admin from public.profiles where id = $1",
                                      user.id)
        tenants = await conn.fetch(
            """select t.id, t.name, t.portal_slug, t.logo_url, t.brand_primary, t.plan,
                      coalesce(m.role, 'platform_admin') as role
               from public.tenants t
               left join public.memberships m on m.tenant_id = t.id and m.user_id = $1
               order by (m.role is null), t.name""", user.id)
    if profile is None:
        raise HTTPException(403, "No profile for this user")
    return {"profile": dict(profile), "tenants": [dict(t) for t in tenants]}


class Route(_Base):
    provider: Literal["anthropic", "openrouter", "openai_compatible"]
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    fallback: bool = False


class JevConfig(_Base):
    instructions: str | None = Field(default=None, max_length=4000)
    categories: dict[Literal["job_requisition", "resume", "interview_feedback", "client_correspondence",
                             "candidate_reply", "other"], str] | None = None
    use_corrections: bool | None = None
    body_chars: int | None = Field(default=None, ge=500, le=30000)
    attachment_chars: int | None = Field(default=None, ge=0, le=10000)


AI_FIELDS = {"llm_provider", "llm_model", "llm_base_url", "model_routes", "triage_provider", "jev_model", "jev_config"}


class SettingsUpdate(_Base):
    llm_provider: Literal["anthropic", "openrouter", "openai_compatible"] | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    email_agent_enabled: bool | None = None
    email_scan_minutes: int | None = None
    inbox_mode: Literal["review", "auto"] | None = None
    auto_approve_threshold: Decimal | None = None
    ai_scoring_enabled: bool | None = None
    model_routes: dict[Literal["default", "email_triage", "email_extraction", "resume_parsing"], Route | None] | None = None
    triage_provider: Literal["llm", "jev"] | None = None
    jev_model: str | None = Field(default=None, min_length=1, max_length=100)
    jev_config: JevConfig | None = None
    review_below_confidence: Decimal | None = Field(default=None, ge=0, le=1)


@router.get("/tenants/{tenant_id}/settings")
async def get_settings_(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        r = await conn.fetchrow("select * from public.tenant_settings where tenant_id = $1", tenant_id)
    if r is None:
        raise HTTPException(404, "settings not found")
    return dict(r)


@router.patch("/tenants/{tenant_id}/settings")
async def update_settings(tenant_id: UUID, body: SettingsUpdate, user: CurrentUser = Depends(get_current_user)) -> dict:
    values = body.model_dump(exclude_unset=True)
    if "model_routes" in values:   # drop cleared routes (null) so the task uses the default again
        values["model_routes"] = {k: v for k, v in values["model_routes"].items() if v}
    if "jev_config" in values:
        values["jev_config"] = {k: v for k, v in values["jev_config"].items() if v is not None}
    async with user_tx(user.id) as conn:
        if AI_FIELDS & values.keys() and not await conn.fetchval("select public.is_tenant_admin($1)", tenant_id):
            raise HTTPException(403, "Only workspace owners and admins can change AI models")
        if values:
            sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(values, start=2))
            r = await conn.fetchrow(f"update public.tenant_settings set {sets} where tenant_id = $1 returning *",
                                    tenant_id, *values.values())
        else:
            r = await conn.fetchrow("select * from public.tenant_settings where tenant_id = $1", tenant_id)
    if r is None:
        raise HTTPException(404, "settings not found")
    return dict(r)


@router.get("/tenants/{tenant_id}/candidates/{candidate_id}/documents")
async def list_documents(tenant_id: UUID, candidate_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list:
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select d.id, d.kind, d.file_name, d.mime_type, d.size_bytes, d.is_primary, d.created_at, d.uploaded_by,
                      tm.full_name as uploaded_by_name, left(d.extracted_text, 60000) as extracted_text
               from public.candidate_documents d left join public.team_members tm on tm.id = d.uploaded_by
               where d.tenant_id = $1 and d.candidate_id = $2
               order by d.is_primary desc, d.created_at desc""", tenant_id, candidate_id)
    return [dict(r) for r in rows]


@router.get("/tenants/{tenant_id}/documents/{document_id}/download")
async def download_document(tenant_id: UUID, document_id: UUID, user: CurrentUser = Depends(get_current_user),
                            storage: Storage = Depends(get_storage)) -> Response:
    async with user_tx(user.id) as conn:   # RLS check happens here
        doc = await conn.fetchrow(
            "select file_name, storage_path, mime_type from public.candidate_documents where tenant_id = $1 and id = $2",
            tenant_id, document_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    data = await storage.get(doc["storage_path"])
    return Response(data, media_type=doc["mime_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{doc["file_name"]}"'})
