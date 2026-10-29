"""CRUD endpoints for the core CRM records. All routes are scoped to /tenants/{tenant_id}/..."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .. import crud
from .. import schemas as s
from ..auth import CurrentUser, get_current_user
from ..db import user_tx

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["crm"])


def register_resource(path: str, table: str, create_model: type[BaseModel], update_model: type[BaseModel],
                      filters: tuple[str, ...] = (), order: str = "created_at desc") -> None:
    """Standard list / get / create / patch / delete for one table."""

    async def list_items(tenant_id: UUID, request: Request, limit: int = Query(200, le=1000), offset: int = 0,
                         user: CurrentUser = Depends(get_current_user)) -> list[dict]:
        # Only whitelisted filter names reach SQL; values are bound parameters.
        where: dict = {}
        for f in filters:
            if (v := request.query_params.get(f)) is not None:
                where[f] = UUID(v) if f.endswith("_id") else v
        async with user_tx(user.id) as conn:
            return await crud.list_rows(conn, table, tenant_id, where=where, order=order, limit=limit, offset=offset)

    async def get_item(tenant_id: UUID, item_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
        async with user_tx(user.id) as conn:
            return await crud.get_row(conn, table, tenant_id, item_id)

    async def create_item(tenant_id: UUID, body: create_model, user: CurrentUser = Depends(get_current_user)) -> dict:  # type: ignore[valid-type]
        async with user_tx(user.id) as conn:
            return await crud.insert_row(conn, table, tenant_id, body)

    async def update_item(tenant_id: UUID, item_id: UUID, body: update_model,  # type: ignore[valid-type]
                          user: CurrentUser = Depends(get_current_user)) -> dict:
        async with user_tx(user.id) as conn:
            return await crud.update_row(conn, table, tenant_id, item_id, body)

    async def delete_item(tenant_id: UUID, item_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
        async with user_tx(user.id) as conn:
            await crud.delete_row(conn, table, tenant_id, item_id)
        return {"deleted": str(item_id)}

    router.add_api_route(f"/{path}", list_items, methods=["GET"], name=f"list_{path}")
    router.add_api_route(f"/{path}/{{item_id}}", get_item, methods=["GET"], name=f"get_{path}")
    router.add_api_route(f"/{path}", create_item, methods=["POST"], status_code=201, name=f"create_{path}")
    router.add_api_route(f"/{path}/{{item_id}}", update_item, methods=["PATCH"], name=f"update_{path}")
    router.add_api_route(f"/{path}/{{item_id}}", delete_item, methods=["DELETE"], name=f"delete_{path}")


register_resource("clients", "clients", s.ClientCreate, s.ClientUpdate, filters=("status",))
register_resource("contacts", "client_contacts", s.ContactCreate, s.ContactUpdate, filters=("client_id",))
register_resource("jobs", "jobs", s.JobCreate, s.JobUpdate, filters=("status", "client_id"))
register_resource("candidates", "candidates", s.CandidateCreate, s.CandidateUpdate, filters=("status",))
register_resource("stages", "pipeline_stages", s.StageCreate, s.StageUpdate, filters=("pipeline_id",),
                  order="pipeline_id, position")
register_resource("interviews", "interviews", s.InterviewCreate, s.InterviewUpdate, filters=("application_id",))
register_resource("interview-feedback", "interview_feedback", s.FeedbackCreate, s.FeedbackUpdate,
                  filters=("application_id",))
register_resource("activities", "activities", s.ActivityCreate, s.ActivityUpdate,
                  filters=("candidate_id", "contact_id", "client_id", "job_id"))


# ── Pipelines ───────────────────────────────────────────────────────────────

@router.get("/pipelines")
async def list_pipelines(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        pipelines = await crud.list_rows(conn, "pipelines", tenant_id, order="is_default desc, name")
        stages = await crud.list_rows(conn, "pipeline_stages", tenant_id, order="position", limit=1000)
    for p in pipelines:
        p["stages"] = [st for st in stages if st["pipeline_id"] == p["id"]]
    return pipelines


@router.post("/pipelines", status_code=201)
async def create_pipeline(tenant_id: UUID, body: s.PipelineCreate, copy_from: UUID | None = None,
                          user: CurrentUser = Depends(get_current_user)) -> dict:
    """Create a pipeline, optionally copying the stages of an existing one."""
    async with user_tx(user.id) as conn:
        if body.is_default:
            await conn.execute("update public.pipelines set is_default = false where tenant_id = $1", tenant_id)
        p = await crud.insert_row(conn, "pipelines", tenant_id, body)
        if copy_from:
            await conn.execute(
                """insert into public.pipeline_stages (tenant_id, pipeline_id, name, position, color, stage_type)
                   select tenant_id, $2, name, position, color, stage_type from public.pipeline_stages
                   where tenant_id = $1 and pipeline_id = $3""", tenant_id, p["id"], copy_from)
        return p


@router.put("/pipelines/{pipeline_id}/stage-order")
async def reorder_stages(tenant_id: UUID, pipeline_id: UUID, body: s.StageReorder,
                         user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        current = {r["id"] for r in await conn.fetch(
            "select id from public.pipeline_stages where tenant_id = $1 and pipeline_id = $2", tenant_id, pipeline_id)}
        if set(body.stage_ids) != current:
            raise HTTPException(422, "stage_ids must list every stage of this pipeline exactly once")
        for pos, sid in enumerate(body.stage_ids, start=1):   # unique(position) is deferred until commit
            await conn.execute("update public.pipeline_stages set position = $1 where id = $2", pos, sid)
        return await crud.list_rows(conn, "pipeline_stages", tenant_id, where={"pipeline_id": pipeline_id},
                                    order="position")


# ── Applications (candidate ↔ job) ──────────────────────────────────────────

@router.get("/applications")
async def list_applications(tenant_id: UUID, job_id: UUID | None = None, candidate_id: UUID | None = None,
                            user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            """select a.*, c.first_name, c.last_name, c.email, c.current_title,
                      j.title as job_title, st.name as stage_name, st.position as stage_position,
                      (select score from public.match_scores m where m.candidate_id = a.candidate_id
                         and m.job_id = a.job_id order by created_at desc limit 1) as match_score
               from public.applications a
               join public.candidates c on c.id = a.candidate_id
               join public.jobs j on j.id = a.job_id
               left join public.pipeline_stages st on st.id = a.stage_id
               where a.tenant_id = $1 and ($2::uuid is null or a.job_id = $2)
                 and ($3::uuid is null or a.candidate_id = $3)
               order by st.position nulls first, a.created_at desc""", tenant_id, job_id, candidate_id)
        return [dict(r) for r in rows]


@router.post("/applications", status_code=201)
async def create_application(tenant_id: UUID, body: s.ApplicationCreate,
                             user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        data = body.model_dump()
        if data["stage_id"] is None:
            data["stage_id"] = await conn.fetchval(
                """select st.id from public.jobs j
                   join public.pipelines p on p.tenant_id = j.tenant_id
                        and (p.id = j.pipeline_id or (j.pipeline_id is null and p.is_default))
                   join public.pipeline_stages st on st.pipeline_id = p.id
                   where j.tenant_id = $1 and j.id = $2 order by st.position limit 1""", tenant_id, body.job_id)
        return await crud.insert_row(conn, "applications", tenant_id, data)


@router.patch("/applications/{item_id}")
async def update_application(tenant_id: UUID, item_id: UUID, body: s.ApplicationUpdate,
                             user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        if body.stage_id is not None and body.placed_at is None:
            stage_type = await conn.fetchval("select stage_type from public.pipeline_stages where id = $1",
                                             body.stage_id)
            if stage_type == "placed":
                body.placed_at = datetime.now(timezone.utc)
        return await crud.update_row(conn, "applications", tenant_id, item_id, body)


@router.delete("/applications/{item_id}")
async def delete_application(tenant_id: UUID, item_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        await crud.delete_row(conn, "applications", tenant_id, item_id)
    return {"deleted": str(item_id)}


# ── Job publishing ──────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/publish")
async def publish_job(tenant_id: UUID, job_id: UUID, published: bool = True,
                      user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        r = await conn.fetchrow(
            """update public.jobs set is_published = $3,
                   published_at = case when $3 then coalesce(published_at, now()) else published_at end
               where tenant_id = $1 and id = $2 returning id, is_published, published_at, status""",
            tenant_id, job_id, published)
        if r is None:
            raise HTTPException(404, "job not found")
        if published and r["status"] != "open":
            raise HTTPException(422, "Only open jobs appear on the website; set status to 'open' first")
        return dict(r)


# ── Saved views / layouts ───────────────────────────────────────────────────

@router.get("/views")
async def list_views(tenant_id: UUID, entity: str | None = None,
                     user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        where = {"entity": entity} if entity else None
        return await crud.list_rows(conn, "saved_views", tenant_id, where=where, order="name")


@router.post("/views", status_code=201)
async def create_view(tenant_id: UUID, body: s.SavedViewCreate, user: CurrentUser = Depends(get_current_user)) -> dict:
    data = body.model_dump()
    data["user_id"] = None if data.pop("shared") else user.id
    async with user_tx(user.id) as conn:
        return await crud.insert_row(conn, "saved_views", tenant_id, data)


@router.delete("/views/{item_id}")
async def delete_view(tenant_id: UUID, item_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        await crud.delete_row(conn, "saved_views", tenant_id, item_id)
    return {"deleted": str(item_id)}


# ── Several contacts at once ────────────────────────────────────────────────

@router.post("/clients/{client_id}/contacts", status_code=201)
async def add_contacts(tenant_id: UUID, client_id: UUID, body: list[s.ContactRow],
                       user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """Add one or more contacts to a client in one go: all are saved, or none are."""
    if not body:
        raise HTTPException(422, "Add at least one contact")
    async with user_tx(user.id) as conn:
        await crud.get_row(conn, "clients", tenant_id, client_id)   # 404 if not this tenant's client
        emails = [c.email.lower() for c in body if c.email]
        if len(emails) != len(set(emails)):
            raise HTTPException(422, "The same email address is listed twice")
        taken = await conn.fetch("select email from public.client_contacts where tenant_id = $1 and email = any($2::citext[])",
                                 tenant_id, emails)
        if taken:
            raise HTTPException(409, f"Already a contact: {', '.join(r['email'] for r in taken)}")
        if any(c.is_primary for c in body):
            await conn.execute("update public.client_contacts set is_primary = false where tenant_id = $1 and client_id = $2",
                               tenant_id, client_id)
        out = []
        for c in body:
            out.append(await crud.insert_row(conn, "client_contacts", tenant_id, {**c.model_dump(), "client_id": client_id}))
        return out
