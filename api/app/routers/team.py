"""Team members (Settings → Users): the people at the agency who can be tagged on work,
e.g. who uploaded a resume. People with a login are added automatically when they join the workspace."""
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import EmailStr, Field

from ..auth import CurrentUser, get_current_user
from ..config import get_settings
from ..db import service_tx, user_tx
from ..schemas import _Base
from ..services.auth_admin import AuthAdmin, AuthAdminError, get_auth_admin

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


# ── Logins: inviting people, roles, removing access ─────────────────────────

ROLE_LABEL = {"owner": "Owner", "admin": "Admin", "recruiter": "Recruiter"}


class InviteBody(_Base):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=200)
    role: Literal["admin", "recruiter", "owner"] = "recruiter"
    send_email: bool = False   # True: Supabase emails it (needs your own email service in Supabase)


class RoleBody(_Base):
    role: Literal["admin", "recruiter", "owner"]


async def _my_role(conn, tenant_id: UUID, user_id: UUID) -> str | None:
    if await conn.fetchval("select is_platform_admin from public.profiles where id = $1", user_id):
        return "owner"
    return await conn.fetchval("select role from public.memberships where tenant_id = $1 and user_id = $2",
                               tenant_id, user_id)


async def _require_admin(conn, tenant_id: UUID, user_id: UUID) -> str:
    role = await _my_role(conn, tenant_id, user_id)
    if role not in ("owner", "admin"):
        raise HTTPException(403, "Only workspace owners and admins can manage who has access")
    return role


def _welcome_url() -> str:
    return get_settings().app_url.rstrip("/") + "/welcome"


@router.get("/members")
async def list_members(tenant_id: UUID, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """Everyone with a login to this workspace, with their role and whether they've signed in yet."""
    async with user_tx(user.id) as conn:
        if not await conn.fetchval("select public.is_member($1)", tenant_id):
            raise HTTPException(403, "Not a member of this workspace")
    async with service_tx() as conn:   # reading auth.users (sign-in status) needs the service connection
        rows = await conn.fetch(
            """select m.user_id, m.role, m.created_at as added_at, p.email,
                      coalesce(tm.full_name, p.full_name, split_part(p.email::text, '@', 1)) as name,
                      u.last_sign_in_at, m.user_id = $2 as is_me
               from public.memberships m join public.profiles p on p.id = m.user_id
               left join auth.users u on u.id = m.user_id
               left join public.team_members tm on tm.tenant_id = m.tenant_id and tm.user_id = m.user_id
               where m.tenant_id = $1 order by (m.role = 'owner') desc, name""", tenant_id, user.id)
    return [dict(r) for r in rows]


@router.post("/invites", status_code=201)
async def invite(tenant_id: UUID, body: InviteBody, user: CurrentUser = Depends(get_current_user),
                 auth: AuthAdmin = Depends(get_auth_admin)) -> dict:
    """Create a login for someone and give them access to this workspace. Returns a personal sign-in link to send
    them (or emails it, if Supabase has an email service set up)."""
    email = body.email.lower()
    async with user_tx(user.id) as conn:
        my_role = await _require_admin(conn, tenant_id, user.id)
    if body.role == "owner" and my_role != "owner":
        raise HTTPException(403, "Only an owner can invite another owner")
    async with service_tx() as conn:
        if await conn.fetchval("""select exists(select 1 from public.memberships m join public.profiles p on p.id = m.user_id
                                  where m.tenant_id = $1 and lower(p.email::text) = $2)""", tenant_id, email):
            raise HTTPException(409, f"{email} already has access to this workspace")
    emailed, note, link = False, None, None
    try:
        if body.send_email:
            try:
                user_id = await auth.send_invite(email, body.full_name, _welcome_url())
                emailed = True
            except AuthAdminError as exc:   # usually: no email service set up in Supabase
                note = f"Supabase couldn’t send the email ({exc}), so here’s the link to send yourself."
                user_id, link = await auth.invite_link(email, body.full_name, _welcome_url())
        else:
            user_id, link = await auth.invite_link(email, body.full_name, _welcome_url())
    except AuthAdminError as exc:
        raise HTTPException(502 if exc.status != 0 else 503, f"Couldn’t create the login: {exc}") from exc
    async with service_tx() as conn:
        uid = UUID(user_id)
        if body.full_name:
            await conn.execute("update public.profiles set full_name = coalesce(nullif(full_name, ''), $2) where id = $1",
                               uid, body.full_name.strip())
        if not await conn.fetchval("select exists(select 1 from public.profiles where id = $1)", uid):
            raise HTTPException(502, "The login was created but its profile is missing; try again in a moment")
        await conn.execute("insert into public.memberships (tenant_id, user_id, role) values ($1, $2, $3) "
                           "on conflict (tenant_id, user_id) do nothing", tenant_id, uid, body.role)
        await conn.execute("update public.team_members set is_active = true, full_name = coalesce($3, full_name) "
                           "where tenant_id = $1 and user_id = $2", tenant_id, uid, body.full_name)
    return {"user_id": user_id, "email": email, "emailed": emailed, "link": link, "note": note}


@router.post("/members/{member_id}/link")
async def new_link(tenant_id: UUID, member_id: UUID, user: CurrentUser = Depends(get_current_user),
                   auth: AuthAdmin = Depends(get_auth_admin)) -> dict:
    """A fresh sign-in link (links expire), e.g. for someone who hasn't signed in yet or forgot their password."""
    async with user_tx(user.id) as conn:
        await _require_admin(conn, tenant_id, user.id)
    async with service_tx() as conn:
        email = await conn.fetchval("""select p.email::text from public.memberships m join public.profiles p on p.id = m.user_id
                                       where m.tenant_id = $1 and m.user_id = $2""", tenant_id, member_id)
    if not email:
        raise HTTPException(404, "That person isn't in this workspace")
    try:
        _, link = await auth.invite_link(email, None, _welcome_url())
    except AuthAdminError as exc:
        raise HTTPException(502, f"Couldn’t create a link: {exc}") from exc
    return {"email": email, "link": link}


async def _owners(conn, tenant_id: UUID) -> int:
    return await conn.fetchval("select count(*) from public.memberships where tenant_id = $1 and role = 'owner'", tenant_id)


@router.patch("/members/{member_id}")
async def change_role(tenant_id: UUID, member_id: UUID, body: RoleBody, user: CurrentUser = Depends(get_current_user)) -> dict:
    async with user_tx(user.id) as conn:
        my_role = await _require_admin(conn, tenant_id, user.id)
    async with service_tx() as conn:
        current = await conn.fetchval("select role from public.memberships where tenant_id = $1 and user_id = $2",
                                      tenant_id, member_id)
        if current is None:
            raise HTTPException(404, "That person isn't in this workspace")
        if "owner" in (current, body.role) and my_role != "owner":
            raise HTTPException(403, "Only an owner can make someone an owner or change an owner’s role")
        if current == "owner" and body.role != "owner" and await _owners(conn, tenant_id) <= 1:
            raise HTTPException(422, "A workspace needs at least one owner")
        await conn.execute("update public.memberships set role = $3 where tenant_id = $1 and user_id = $2",
                           tenant_id, member_id, body.role)
    return {"user_id": str(member_id), "role": body.role}


@router.delete("/members/{member_id}")
async def remove_member(tenant_id: UUID, member_id: UUID, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Takes away their access to this workspace (their login itself stays, e.g. for other workspaces).
    Mailboxes shared with them stop being visible to them; their name stays on past notes and uploads."""
    if member_id == user.id:
        raise HTTPException(422, "You can’t remove yourself")
    async with user_tx(user.id) as conn:
        my_role = await _require_admin(conn, tenant_id, user.id)
    async with service_tx() as conn:
        current = await conn.fetchval("select role from public.memberships where tenant_id = $1 and user_id = $2",
                                      tenant_id, member_id)
        if current is None:
            raise HTTPException(404, "That person isn't in this workspace")
        if current == "owner" and my_role != "owner":
            raise HTTPException(403, "Only an owner can remove an owner")
        if current == "owner" and await _owners(conn, tenant_id) <= 1:
            raise HTTPException(422, "A workspace needs at least one owner")
        await conn.execute("delete from public.mailbox_access where tenant_id = $1 and user_id = $2", tenant_id, member_id)
        await conn.execute("update public.team_members set is_active = false where tenant_id = $1 and user_id = $2",
                           tenant_id, member_id)
        await conn.execute("delete from public.memberships where tenant_id = $1 and user_id = $2", tenant_id, member_id)
    return {"removed": str(member_id)}
