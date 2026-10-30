-- Team members (Users), who uploaded each resume, editable notes, and per-job pipelines.

-- ── Team members ────────────────────────────────────────────────────────────
-- Everyone at the agency who can be tagged on work. A member may or may not have a login (user_id);
-- people with a login are added automatically when they join the workspace.
create table if not exists public.team_members (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    user_id     uuid references public.profiles(id) on delete set null,
    full_name   text not null,
    email       citext,
    title       text,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    unique (tenant_id, email),
    unique (tenant_id, user_id)
);
create index if not exists team_members_tenant on public.team_members (tenant_id, is_active, full_name);

alter table public.team_members enable row level security;
drop policy if exists team_members_read on public.team_members;
drop policy if exists team_members_write on public.team_members;
create policy team_members_read on public.team_members for select using (public.is_member(tenant_id));
-- Admins manage the list; anyone can edit their own entry (e.g. their display name).
create policy team_members_write on public.team_members for all
    using (public.is_tenant_admin(tenant_id) or user_id = auth.uid())
    with check (public.is_tenant_admin(tenant_id) or user_id = auth.uid());
grant select, insert, update, delete on public.team_members to authenticated;

-- Everyone already in a workspace becomes a team member.
insert into public.team_members (tenant_id, user_id, full_name, email)
select m.tenant_id, m.user_id, coalesce(nullif(p.full_name, ''), split_part(p.email::text, '@', 1), 'Team member'), p.email
from public.memberships m join public.profiles p on p.id = m.user_id
on conflict do nothing;

-- New logins joining a workspace: link them to an existing member with the same email, or add them.
create or replace function public.add_team_member() returns trigger
language plpgsql security definer set search_path = public as $$
declare p record;
begin
    select id, full_name, email into p from public.profiles where id = new.user_id;
    update public.team_members set user_id = new.user_id
     where tenant_id = new.tenant_id and user_id is null and email = p.email;
    if not found then
        insert into public.team_members (tenant_id, user_id, full_name, email)
        values (new.tenant_id, new.user_id, coalesce(nullif(p.full_name, ''), split_part(p.email::text, '@', 1), 'Team member'), p.email)
        on conflict do nothing;
    end if;
    return new;
end $$;
drop trigger if exists memberships_add_team_member on public.memberships;
create trigger memberships_add_team_member after insert on public.memberships
    for each row execute function public.add_team_member();

-- ── Who uploaded a resume ───────────────────────────────────────────────────
alter table public.candidate_documents add column if not exists uploaded_by uuid references public.team_members(id) on delete set null;
alter table public.import_batches     add column if not exists uploaded_by uuid references public.team_members(id) on delete set null;

-- ── Notes can be edited ─────────────────────────────────────────────────────
alter table public.activities add column if not exists updated_at timestamptz;
alter table public.activities add column if not exists updated_by uuid references public.profiles(id);
create index if not exists activities_candidate on public.activities (candidate_id, created_at desc);

-- ── Per-job pipelines ───────────────────────────────────────────────────────
-- A pipeline with job_id set belongs to that one job (its stages were customized there) and is hidden
-- from the shared list in Settings.
alter table public.pipelines add column if not exists job_id uuid references public.jobs(id) on delete cascade;
create unique index if not exists pipelines_one_per_job on public.pipelines (job_id) where job_id is not null;

-- When a job switches pipeline, keep each candidate in the matching stage (same name, else same kind of
-- closed stage, else the first stage) rather than leaving them pointing at the old pipeline.
create or replace function public.remap_job_stages() returns trigger
language plpgsql as $$
declare target uuid;
begin
    if new.pipeline_id is not distinct from old.pipeline_id then
        return new;
    end if;
    target := coalesce(new.pipeline_id,
                       (select id from public.pipelines where tenant_id = new.tenant_id and is_default and job_id is null limit 1));
    if target is null then
        return new;
    end if;
    update public.applications a set stage_id = coalesce(
        (select ns.id from public.pipeline_stages ns join public.pipeline_stages os on os.id = a.stage_id
          where ns.pipeline_id = target and lower(ns.name) = lower(os.name) order by ns.position limit 1),
        (select ns.id from public.pipeline_stages ns join public.pipeline_stages os on os.id = a.stage_id
          where ns.pipeline_id = target and os.stage_type <> 'active' and ns.stage_type = os.stage_type
          order by ns.position limit 1),
        (select ns.id from public.pipeline_stages ns where ns.pipeline_id = target order by ns.position limit 1))
    where a.job_id = new.id;
    return new;
end $$;
drop trigger if exists jobs_remap_stages on public.jobs;
create trigger jobs_remap_stages after update of pipeline_id on public.jobs
    for each row execute function public.remap_job_stages();
