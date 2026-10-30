"""Team members (Settings → Users): the people at the agency who can be tagged on work,
e.g. who uploaded a resume. People with a login are added automatically when they join the workspace."""
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr, Field

from ..auth import CurrentUser, get_current_user
from ..db import user_tx
from ..schemas import _Base

router = APIRouter(prefix="/tenants/{tenant_id}/team", tags=["team"])

SELECT = """select tm.id, tm.full_name, tm.email, tm.title, tm.is_active, tm.user_id, tm.created_at,
                   tm.user_id is not null as has_login, m.role, tm.user_id = $2 as is_me
            from public.team_members tm
            left join public.memberships m on m.tenant_id = tm.tenant_id and m.user_id = tm.user_id
            where tm.tenant_id = $1"""


class MemberCreate(_Base):
    full_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=200)


class MemberUpdate(_Base):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


async def my_member_id(conn, tenant_id: UUID, user_id: UUID) -> UUID | None:
    return await conn.fetchval("select id from public.team_members where tenant_id = $1 and user_id = $2",
                               tenant_id, user_id)


async def check_member(conn, tenant_id: UUID, member_id: UUID | None) -> UUID | None:
    """A team member id sent by the browser must belong to this workspace."""
    if member_id is None:
        return None
    if not await conn.fetchval("select exists(select 1 from public.team_members where tenant_id = $1 and id = $2)",
                               tenant_id, member_id):
        raise HTTPException(422, "That team member isn't in this workspace")
    return member_id


@router.get("")
async def list_team(tenant_id: UUID, include_inactive: bool = False,
                    user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    async with user_tx(user.id) as conn:
        if not await my_member_id(conn, tenant_id, user.id) and await conn.fetchval(
                "select exists(select 1 from public.memberships where tenant_id = $1 and user_id = $2)", tenant_id, user.id):
            # Someone who joined before team members existed: add them now.
            await conn.execute(
                """insert into public.team_members (tenant_id, user_id, full_name, email)
                   select $1, p.id, coalesce(nullif(p.full_name, ''), split_part(p.email::text, '@', 1), 'Me'), p.email
                   from public.profiles p where p.id = $2 on conflict do nothing""", tenant_id, user.id)
        rows = await conn.fetch(SELECT + (" " if include_inactive else " and tm.is_active ") + "order by tm.full_name",
                                tenant_id, user.id)
    return [dict(r) for r in rows]


def _dup(exc: asyncpg.UniqueViolationError) -> HTTPException:
    return HTTPException(409, "Someone on the team already has that email address")


@router.post("", status_code=201)
async def add_member(tenant_id: UUID, body: MemberCreate, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select public.is_tenant_admin($1)", tenant_id):
            raise HTTPException(403, "Only workspace owners and admins can add team members")
        try:
            mid = await conn.fetchval(
                "insert into public.team_members (tenant_id, full_name, email, title) values ($1,$2,$3,$4) returning id",
                tenant_id, body.full_name.strip(), body.email, body.title)
        except asyncpg.UniqueViolationError as exc:
            raise _dup(exc) from exc
        return dict(await conn.fetchrow(SELECT + " and tm.id = $3", tenant_id, user.id, mid))


@router.patch("/{member_id}")
async def update_member(tenant_id: UUID, member_id: UUID, body: MemberUpdate,
                        user: CurrentUser = Depends(get_current_user)) -> dict:
    values = body.model_dump(exclude_unset=True)
    async with user_tx(user.id) as conn:
        current = await conn.fetchrow("select user_id from public.team_members where tenant_id = $1 and id = $2",
                                      tenant_id, member_id)
        if current is None:
            raise HTTPException(404, "team member not found")
        admin = await conn.fetchval("select public.is_tenant_admin($1)", tenant_id)
        if not admin and current["user_id"] != user.id:
            raise HTTPException(403, "Only workspace owners and admins can change other team members")
        if values.get("is_active") is False and current["user_id"] == user.id:
            raise HTTPException(422, "You can't remove yourself")
        if values:
            sets = ", ".join(f"{c} = ${i}" for i, c in enumerate(values, start=3))
            try:
                await conn.execute(f"update public.team_members set {sets}, updated_at = now() "
                                   f"where tenant_id = $1 and id = $2", tenant_id, member_id, *values.values())
            except asyncpg.UniqueViolationError as exc:
                raise _dup(exc) from exc
        return dict(await conn.fetchrow(SELECT + " and tm.id = $3", tenant_id, user.id, member_id))
