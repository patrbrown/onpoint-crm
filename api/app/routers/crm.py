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
                      filters: tuple[str, ...] = (), order: str = "created_at desc", skip: tuple[str, ...] = ()) -> None:
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
    if "delete" not in skip:
        router.add_api_route(f"/{path}/{{item_id}}", delete_item, methods=["DELETE"], name=f"delete_{path}")


register_resource("clients", "clients", s.ClientCreate, s.ClientUpdate, filters=("status",))
register_resource("contacts", "client_contacts", s.ContactCreate, s.ContactUpdate, filters=("client_id",))
register_resource("jobs", "jobs", s.JobCreate, s.JobUpdate, filters=("status", "client_id"))
register_resource("candidates", "candidates", s.CandidateCreate, s.CandidateUpdate, filters=("status",))
register_resource("stages", "pipeline_stages", s.StageCreate, s.StageUpdate, filters=("pipeline_id",),
                  order="pipeline_id, position", skip=("delete",))
register_resource("interviews", "interviews", s.InterviewCreate, s.InterviewUpdate, filters=("application_id",))
register_resource("interview-feedback", "interview_feedback", s.FeedbackCreate, s.FeedbackUpdate,
                  filters=("application_id",))


# ── Pipelines ───────────────────────────────────────────────────────────────

@router.get("/pipelines")
async def list_pipelines(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        # Shared pipelines only; a job's own customized pipeline is under /jobs/{id}/pipeline.
        pipelines = [dict(r) for r in await conn.fetch(
            "select * from public.pipelines where tenant_id = $1 and job_id is null order by is_default desc, name",
            tenant_id)]
        stages = await crud.list_rows(conn, "pipeline_stages", tenant_id, order="position", limit=5000)
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


# ── Stages: delete (moving any candidates first) ────────────────────────────

@router.delete("/stages/{stage_id}")
async def delete_stage(tenant_id: UUID, stage_id: UUID, move_to: UUID | None = None,
                       user: CurrentUser = Depends(get_current_user)) -> dict:
    """Delete a stage. If candidates are in it, `move_to` (another stage of the same pipeline) says where they go."""
    async with user_tx(user.id) as conn:
        st = await conn.fetchrow("select pipeline_id from public.pipeline_stages where tenant_id = $1 and id = $2",
                                 tenant_id, stage_id)
        if st is None:
            raise HTTPException(404, "stage not found")
        if await conn.fetchval("select count(*) from public.pipeline_stages where pipeline_id = $1", st["pipeline_id"]) <= 1:
            raise HTTPException(422, "A pipeline needs at least one stage")
        in_stage = await conn.fetchval("select count(*) from public.applications where stage_id = $1", stage_id)
        if in_stage:
            if move_to is None:
                raise HTTPException(409, f"{in_stage} candidate(s) are in this stage. Choose a stage to move them to.")
            ok = await conn.fetchval("select exists(select 1 from public.pipeline_stages where tenant_id = $1 and id = $2 "
                                     "and pipeline_id = $3 and id <> $4)", tenant_id, move_to, st["pipeline_id"], stage_id)
            if not ok:
                raise HTTPException(422, "Move candidates to another stage of the same pipeline")
            await conn.execute("update public.applications set stage_id = $2 where stage_id = $1", stage_id, move_to)
        await conn.execute("delete from public.pipeline_stages where id = $1", stage_id)
        # close the gap in positions (unique(position) is checked at commit)
        await conn.execute(
            """update public.pipeline_stages s set position = r.n
               from (select id, row_number() over (order by position) as n from public.pipeline_stages
                     where pipeline_id = $1) r where s.id = r.id""", st["pipeline_id"])
    return {"deleted": str(stage_id), "moved": in_stage}


# ── A job's own pipeline ────────────────────────────────────────────────────

async def _job_pipeline(conn, tenant_id: UUID, job_id: UUID) -> dict:
    job = await conn.fetchrow("select id, title, pipeline_id from public.jobs where tenant_id = $1 and id = $2",
                              tenant_id, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    p = await conn.fetchrow(
        """select * from public.pipelines where tenant_id = $1
           and (id = $2 or ($2::uuid is null and is_default and job_id is null))
           order by (id = $2) desc nulls last limit 1""", tenant_id, job["pipeline_id"])
    if p is None:
        p = await conn.fetchrow("select * from public.pipelines where tenant_id = $1 and job_id is null "
                                "order by is_default desc, created_at limit 1", tenant_id)
    if p is None:
        raise HTTPException(404, "This workspace has no pipeline")
    out = dict(p)
    out["stages"] = await crud.list_rows(conn, "pipeline_stages", tenant_id, where={"pipeline_id": p["id"]},
                                         order="position", limit=1000)
    out["is_custom"] = p["job_id"] == job_id
    return out


@router.get("/jobs/{job_id}/pipeline")
async def get_job_pipeline(tenant_id: UUID, job_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        return await _job_pipeline(conn, tenant_id, job_id)


@router.post("/jobs/{job_id}/pipeline/customize")
async def customize_job_pipeline(tenant_id: UUID, job_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Give this job its own copy of its pipeline, so stages can be added or removed for this job only.
    Candidates stay in the same-named stage."""
    async with user_tx(user.id) as conn:
        current = await _job_pipeline(conn, tenant_id, job_id)
        if current["is_custom"]:
            return current
        title = await conn.fetchval("select title from public.jobs where id = $1", job_id)
        new_id = await conn.fetchval(
            "insert into public.pipelines (tenant_id, name, job_id) values ($1, $2, $3) returning id",
            tenant_id, f"{title} (this job only)", job_id)
        await conn.execute(
            """insert into public.pipeline_stages (tenant_id, pipeline_id, name, position, color, stage_type)
               select tenant_id, $2, name, position, color, stage_type from public.pipeline_stages
               where tenant_id = $1 and pipeline_id = $3""", tenant_id, new_id, current["id"])
        await conn.execute("update public.jobs set pipeline_id = $3 where tenant_id = $1 and id = $2",
                           tenant_id, job_id, new_id)   # trigger moves candidates to the copied stages
        return await _job_pipeline(conn, tenant_id, job_id)


class UseShared(BaseModel):
    pipeline_id: UUID | None = None   # None = the workspace default


@router.post("/jobs/{job_id}/pipeline/reset")
async def reset_job_pipeline(tenant_id: UUID, job_id: UUID, body: UseShared,
                             user: CurrentUser = Depends(get_current_user)) -> dict:
    """Stop using this job's own stages and go back to a shared pipeline. Candidates move to the stage with
    the same name (or the first stage)."""
    async with user_tx(user.id) as conn:
        current = await _job_pipeline(conn, tenant_id, job_id)
        if body.pipeline_id and not await conn.fetchval(
                "select exists(select 1 from public.pipelines where tenant_id = $1 and id = $2 and job_id is null)",
                tenant_id, body.pipeline_id):
            raise HTTPException(422, "Choose a shared pipeline")
        await conn.execute("update public.jobs set pipeline_id = $3 where tenant_id = $1 and id = $2",
                           tenant_id, job_id, body.pipeline_id)
        if current["is_custom"]:
            await conn.execute("delete from public.pipelines where id = $1", current["id"])
        return await _job_pipeline(conn, tenant_id, job_id)


# ── Notes and activity ──────────────────────────────────────────────────────

NOTE_SELECT = """
    select a.*, coalesce(tm.full_name, p.full_name, p.email::text) as author_name,
           coalesce(tu.full_name, pu.full_name, pu.email::text) as editor_name,
           (a.created_by = $2 or public.is_tenant_admin(a.tenant_id)) as can_edit
    from public.activities a
    left join public.profiles p on p.id = a.created_by
    left join public.team_members tm on tm.tenant_id = a.tenant_id and tm.user_id = a.created_by
    left join public.profiles pu on pu.id = a.updated_by
    left join public.team_members tu on tu.tenant_id = a.tenant_id and tu.user_id = a.updated_by
    where a.tenant_id = $1"""


@router.get("/activities")
async def list_activities(tenant_id: UUID, candidate_id: UUID | None = None, contact_id: UUID | None = None,
                          client_id: UUID | None = None, job_id: UUID | None = None, limit: int = Query(200, le=1000),
                          user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        rows = await conn.fetch(
            NOTE_SELECT + """ and ($3::uuid is null or a.candidate_id = $3) and ($4::uuid is null or a.contact_id = $4)
                 and ($5::uuid is null or a.client_id = $5) and ($6::uuid is null or a.job_id = $6)
               order by a.created_at desc limit $7""", tenant_id, user.id, candidate_id, contact_id, client_id, job_id, limit)
    return [dict(r) for r in rows]


async def _note(conn, tenant_id: UUID, user_id: UUID, note_id: UUID) -> dict:
    r = await conn.fetchrow(NOTE_SELECT + " and a.id = $3", tenant_id, user_id, note_id)
    if r is None:
        raise HTTPException(404, "note not found")
    return dict(r)


@router.post("/activities", status_code=201)
async def create_activity(tenant_id: UUID, body: s.ActivityCreate, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        row = await crud.insert_row(conn, "activities", tenant_id, {**body.model_dump(exclude_unset=True),
                                                                    "created_by": user.id})
        return await _note(conn, tenant_id, user.id, row["id"])


@router.patch("/activities/{note_id}")
async def update_activity(tenant_id: UUID, note_id: UUID, body: s.ActivityUpdate,
                          user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        note = await _note(conn, tenant_id, user.id, note_id)
        if not note["can_edit"]:
            raise HTTPException(403, "Only the person who wrote this note (or an admin) can change it")
        values = body.model_dump(exclude_unset=True)
        changed = {k: v for k, v in values.items() if note.get(k) != v}
        if changed:
            sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(changed, start=4))
            await conn.execute(f"update public.activities set {sets}, updated_at = now(), updated_by = $3 "
                               f"where tenant_id = $1 and id = $2", tenant_id, note_id, user.id, *changed.values())
        return await _note(conn, tenant_id, user.id, note_id)


@router.delete("/activities/{note_id}")
async def delete_activity(tenant_id: UUID, note_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        note = await _note(conn, tenant_id, user.id, note_id)
        if not note["can_edit"]:
            raise HTTPException(403, "Only the person who wrote this note (or an admin) can delete it")
        await conn.execute("delete from public.activities where tenant_id = $1 and id = $2", tenant_id, note_id)
    return {"deleted": str(note_id)}
