-- OnPoint CRM — core schema (multi-tenant)
-- Every business table carries tenant_id and is protected by Row Level Security.

create extension if not exists "pgcrypto";
create extension if not exists "vector";
create extension if not exists "citext";

-- ─────────────────────────────────────────────────────────────────────────────
-- Tenancy, users, billing
-- ─────────────────────────────────────────────────────────────────────────────

create table public.tenants (
    id                  uuid primary key default gen_random_uuid(),
    name                text not null,
    portal_slug         citext not null unique,              -- used by the portal/embed: /portal-api/{slug}/jobs
    custom_domain       text,                                -- e.g. jobs.onpointpersonnel.com
    logo_url            text,
    brand_primary       text default '#1F4E79',
    brand_accent        text default '#2E86C1',
    website_url         text,
    -- billing (Stripe wired later)
    plan                text not null default 'trial' check (plan in ('trial','starter','pro','enterprise','internal')),
    status              text not null default 'active' check (status in ('active','past_due','suspended','cancelled')),
    stripe_customer_id  text,
    trial_ends_at       timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create table public.profiles (
    id                  uuid primary key references auth.users(id) on delete cascade,
    full_name           text,
    email               citext,
    is_platform_admin   boolean not null default false,       -- platform owner: onboards and manages tenants
    created_at          timestamptz not null default now()
);

create table public.memberships (
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    user_id     uuid not null references public.profiles(id) on delete cascade,
    role        text not null default 'recruiter' check (role in ('owner','admin','recruiter','viewer')),
    created_at  timestamptz not null default now(),
    primary key (tenant_id, user_id)
);

create table public.tenant_settings (
    tenant_id               uuid primary key references public.tenants(id) on delete cascade,
    -- LLM (swappable)
    llm_provider            text not null default 'anthropic' check (llm_provider in ('anthropic','openai_compatible')),
    llm_model               text not null default 'claude-sonnet-5-5',
    llm_base_url            text,                             -- for local/sovereign models (Ollama, vLLM…)
    -- email agent
    email_agent_enabled     boolean not null default true,
    email_scan_minutes      int not null default 15 check (email_scan_minutes between 5 and 1440),
    inbox_mode              text not null default 'review' check (inbox_mode in ('review','auto')),
    auto_approve_threshold  numeric(3,2) not null default 0.90 check (auto_approve_threshold between 0 and 1),
    -- AI scoring
    ai_scoring_enabled      boolean not null default false,
    updated_at              timestamptz not null default now()
);

-- Helper functions used by RLS policies
create or replace function public.is_platform_admin() returns boolean
language sql stable security definer set search_path = public as $$
    select coalesce((select is_platform_admin from public.profiles where id = auth.uid()), false);
$$;

create or replace function public.is_member(t uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select public.is_platform_admin()
        or exists (select 1 from public.memberships m where m.tenant_id = t and m.user_id = auth.uid());
$$;

create or replace function public.is_tenant_admin(t uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select public.is_platform_admin()
        or exists (select 1 from public.memberships m
                   where m.tenant_id = t and m.user_id = auth.uid() and m.role in ('owner','admin'));
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- Clients and contacts
-- ─────────────────────────────────────────────────────────────────────────────

create table public.clients (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    name        text not null,
    industry    text,
    website     text,
    address     text,
    city        text,
    region      text,
    country     text,
    fee_terms   text,                                       -- e.g. "20% of first-year salary"
    status      text not null default 'active' check (status in ('prospect','active','inactive')),
    notes       text,
    owner_id    uuid references public.profiles(id),
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index on public.clients (tenant_id, name);

create table public.client_contacts (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    client_id   uuid not null references public.clients(id) on delete cascade,
    first_name  text not null,
    last_name   text,
    title       text,
    email       citext,
    phone       text,
    mobile      text,
    linkedin_url text,
    is_primary  boolean not null default false,
    is_hiring_manager boolean not null default false,
    notes       text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index on public.client_contacts (tenant_id, client_id);
create index on public.client_contacts (tenant_id, email);

-- ─────────────────────────────────────────────────────────────────────────────
-- Pipelines (customizable stages) and saved layouts
-- ─────────────────────────────────────────────────────────────────────────────

create table public.pipelines (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    name        text not null,
    is_default  boolean not null default false,
    created_at  timestamptz not null default now()
);
create unique index pipelines_one_default on public.pipelines (tenant_id) where is_default;

create table public.pipeline_stages (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    pipeline_id uuid not null references public.pipelines(id) on delete cascade,
    name        text not null,
    position    int not null,
    color       text default '#94A3B8',
    stage_type  text not null default 'active' check (stage_type in ('active','placed','rejected','withdrawn')),
    unique (pipeline_id, position) deferrable initially deferred
);

create table public.saved_views (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    user_id     uuid references public.profiles(id) on delete cascade,  -- null = shared with the tenant
    entity      text not null check (entity in ('jobs','candidates','clients','contacts','applications','inbox')),
    name        text not null,
    layout      text not null default 'table' check (layout in ('table','board','cards')),
    config      jsonb not null default '{}'::jsonb,         -- columns, filters, sort, grouping
    is_default  boolean not null default false,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Jobs
-- ─────────────────────────────────────────────────────────────────────────────

create table public.jobs (
    id                  uuid primary key default gen_random_uuid(),
    tenant_id           uuid not null references public.tenants(id) on delete cascade,
    client_id           uuid references public.clients(id) on delete set null,
    hiring_contact_id   uuid references public.client_contacts(id) on delete set null,
    pipeline_id         uuid references public.pipelines(id) on delete set null,
    owner_id            uuid references public.profiles(id),
    title               text not null,
    reference_code      text,                               -- client req number
    description         text,                               -- full JD (markdown)
    public_description  text,                               -- what the portal shows (client name can be hidden)
    location            text,
    city                text,
    region              text,
    country             text,
    work_model          text check (work_model in ('onsite','hybrid','remote')),
    employment_type     text check (employment_type in ('permanent','contract','contract_to_hire','temporary')),
    salary_min          numeric(12,2),
    salary_max          numeric(12,2),
    rate_min            numeric(10,2),
    rate_max            numeric(10,2),
    rate_unit           text check (rate_unit in ('hour','day','month','year')),
    currency            char(3) default 'CAD',
    must_have_skills    text[] not null default '{}',
    nice_to_have_skills text[] not null default '{}',
    -- healthcare IT specifics (free-form arrays; Epic/Cerner modules, certifications)
    systems             text[] not null default '{}',
    certifications      text[] not null default '{}',
    openings            int not null default 1,
    fee_percent         numeric(5,2),
    fee_flat            numeric(12,2),
    status              text not null default 'open' check (status in ('draft','open','on_hold','filled','closed','cancelled')),
    priority            text default 'normal' check (priority in ('low','normal','high','urgent')),
    -- publishing
    is_published        boolean not null default false,
    published_at        timestamptz,
    hide_client_name    boolean not null default true,
    -- provenance
    source              text not null default 'manual' check (source in ('manual','email','import','api')),
    source_email_id     uuid,
    embedding           vector(1024),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index on public.jobs (tenant_id, status);
create index on public.jobs (tenant_id, is_published) where is_published;

-- ─────────────────────────────────────────────────────────────────────────────
-- Candidates, documents, applications
-- ─────────────────────────────────────────────────────────────────────────────

create table public.candidates (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    first_name      text not null,
    last_name       text,
    email           citext,
    phone           text,
    linkedin_url    text,
    location        text,
    city            text,
    region          text,
    country         text,
    current_title   text,
    current_company text,
    years_experience numeric(4,1),
    skills          text[] not null default '{}',
    systems         text[] not null default '{}',
    certifications  text[] not null default '{}',
    summary         text,
    work_authorization text,
    desired_rate    text,
    availability    text,
    status          text not null default 'active' check (status in ('active','placed','do_not_contact','archived')),
    source          text not null default 'manual' check (source in ('manual','email','import','portal','api')),
    source_detail   text,
    owner_id        uuid references public.profiles(id),
    embedding       vector(1024),
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index on public.candidates (tenant_id, last_name, first_name);
create unique index candidates_tenant_email on public.candidates (tenant_id, email) where email is not null;

create table public.candidate_documents (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    candidate_id    uuid not null references public.candidates(id) on delete cascade,
    kind            text not null default 'resume' check (kind in ('resume','cover_letter','reference','other')),
    file_name       text not null,
    storage_path    text not null,                           -- Supabase Storage key: {tenant_id}/candidates/{id}/{file}
    mime_type       text,
    size_bytes      bigint,
    extracted_text  text,
    is_primary      boolean not null default false,
    created_at      timestamptz not null default now()
);
create index on public.candidate_documents (tenant_id, candidate_id);

create table public.applications (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    candidate_id    uuid not null references public.candidates(id) on delete cascade,
    job_id          uuid not null references public.jobs(id) on delete cascade,
    stage_id        uuid references public.pipeline_stages(id) on delete set null,
    source          text not null default 'manual' check (source in ('manual','email','import','portal','api')),
    submitted_to_client_at timestamptz,
    placed_at       timestamptz,
    start_date      date,
    bill_rate       numeric(10,2),
    pay_rate        numeric(10,2),
    placement_fee   numeric(12,2),
    rejection_reason text,
    notes           text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (candidate_id, job_id)
);
create index on public.applications (tenant_id, job_id, stage_id);

create table public.application_stage_history (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    application_id  uuid not null references public.applications(id) on delete cascade,
    from_stage_id   uuid references public.pipeline_stages(id) on delete set null,
    to_stage_id     uuid references public.pipeline_stages(id) on delete set null,
    changed_by      uuid references public.profiles(id),
    changed_at      timestamptz not null default now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Interviews and feedback
-- ─────────────────────────────────────────────────────────────────────────────

create table public.interviews (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    application_id  uuid not null references public.applications(id) on delete cascade,
    round           int not null default 1,
    interview_type  text check (interview_type in ('phone_screen','video','onsite','technical','panel','final','other')),
    scheduled_at    timestamptz,
    duration_minutes int,
    location        text,
    interviewer_contact_ids uuid[] not null default '{}',
    status          text not null default 'scheduled' check (status in ('scheduled','completed','cancelled','no_show')),
    created_at      timestamptz not null default now()
);

create table public.interview_feedback (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    interview_id    uuid references public.interviews(id) on delete cascade,
    application_id  uuid not null references public.applications(id) on delete cascade,
    from_contact_id uuid references public.client_contacts(id) on delete set null,
    from_name       text,                                    -- if the giver is not a stored contact
    overall_rating  int check (overall_rating between 1 and 5),
    recommendation  text check (recommendation in ('strong_yes','yes','maybe','no','strong_no')),
    scorecard       jsonb not null default '[]'::jsonb,      -- [{criterion, rating, comment}]
    strengths       text,
    concerns        text,
    notes           text,
    source          text not null default 'manual' check (source in ('manual','email')),
    source_email_id uuid,
    received_at     timestamptz not null default now(),
    created_at      timestamptz not null default now()
);
create index on public.interview_feedback (tenant_id, application_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Activities (calls, emails, notes, meetings) on any entity
-- ─────────────────────────────────────────────────────────────────────────────

create table public.activities (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    kind            text not null check (kind in ('note','call','email','meeting','task','system')),
    subject         text,
    body            text,
    candidate_id    uuid references public.candidates(id) on delete cascade,
    contact_id      uuid references public.client_contacts(id) on delete cascade,
    client_id       uuid references public.clients(id) on delete cascade,
    job_id          uuid references public.jobs(id) on delete cascade,
    application_id  uuid references public.applications(id) on delete cascade,
    due_at          timestamptz,
    completed_at    timestamptz,
    created_by      uuid references public.profiles(id),
    created_at      timestamptz not null default now()
);
create index on public.activities (tenant_id, created_at desc);

-- ─────────────────────────────────────────────────────────────────────────────
-- Email agent: accounts, processed messages, review inbox, AI feedback
-- ─────────────────────────────────────────────────────────────────────────────

create table public.mail_accounts (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    user_id         uuid references public.profiles(id) on delete set null,
    provider        text not null default 'microsoft' check (provider in ('microsoft','google','imap')),
    mailbox_address citext not null,
    auth_mode       text not null default 'delegated' check (auth_mode in ('delegated','application')),
    is_enabled      boolean not null default true,
    last_sync_at    timestamptz,
    delta_link      text,                                     -- Graph delta token for incremental sync
    last_error      text,
    created_at      timestamptz not null default now(),
    unique (tenant_id, mailbox_address)
);

create table public.email_messages (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    mail_account_id uuid not null references public.mail_accounts(id) on delete cascade,
    provider_message_id text not null,                       -- Graph message id (dedupe)
    internet_message_id text,
    conversation_id text,
    from_address    citext,
    from_name       text,
    to_addresses    text[] not null default '{}',
    subject         text,
    received_at     timestamptz,
    body_text       text,
    has_attachments boolean not null default false,
    classification  text check (classification in ('job_requisition','resume','interview_feedback','client_correspondence','candidate_reply','other')),
    confidence      numeric(3,2),
    processed_at    timestamptz,
    error           text,
    created_at      timestamptz not null default now(),
    unique (mail_account_id, provider_message_id)
);
create index on public.email_messages (tenant_id, received_at desc);

create table public.email_attachments (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    email_id        uuid not null references public.email_messages(id) on delete cascade,
    file_name       text not null,
    mime_type       text,
    size_bytes      bigint,
    storage_path    text,
    extracted_text  text,
    created_at      timestamptz not null default now()
);

create table public.inbox_items (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    email_id        uuid references public.email_messages(id) on delete cascade,
    item_type       text not null check (item_type in ('job_requisition','resume','interview_feedback','contact')),
    status          text not null default 'pending' check (status in ('pending','approved','auto_approved','rejected','merged')),
    confidence      numeric(3,2),
    extracted       jsonb not null,                           -- what the agent proposed
    final           jsonb,                                    -- what was actually saved (after edits)
    suggested_matches jsonb not null default '[]'::jsonb,     -- possible duplicates / related jobs or candidates
    created_entity_type text,
    created_entity_id   uuid,
    reviewed_by     uuid references public.profiles(id),
    reviewed_at     timestamptz,
    llm_provider    text,
    llm_model       text,
    prompt_version  text,
    created_at      timestamptz not null default now()
);
create index on public.inbox_items (tenant_id, status, created_at desc);

-- Feedback on any AI output: classification, extraction, match score.
create table public.ai_feedback (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    target_type     text not null check (target_type in ('classification','extraction','match_score')),
    inbox_item_id   uuid references public.inbox_items(id) on delete cascade,
    match_score_id  uuid,
    verdict         text not null check (verdict in ('correct','partially_correct','incorrect')),
    corrected_value jsonb,                                    -- e.g. {"classification":"resume"} or field diffs or {"score":72}
    comment         text,
    use_as_example  boolean not null default true,            -- feed back as few-shot examples
    created_by      uuid references public.profiles(id),
    created_at      timestamptz not null default now()
);
create index on public.ai_feedback (tenant_id, target_type, created_at desc);

-- ─────────────────────────────────────────────────────────────────────────────
-- AI scoring
-- ─────────────────────────────────────────────────────────────────────────────

create table public.match_scores (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    candidate_id    uuid not null references public.candidates(id) on delete cascade,
    job_id          uuid not null references public.jobs(id) on delete cascade,
    score           int not null check (score between 0 and 100),
    strengths       text[] not null default '{}',
    gaps            text[] not null default '{}',
    rationale       text,
    llm_provider    text,
    llm_model       text,
    prompt_version  text,
    created_at      timestamptz not null default now(),
    unique (candidate_id, job_id, prompt_version)
);
alter table public.ai_feedback
    add constraint ai_feedback_match_score_fk foreign key (match_score_id) references public.match_scores(id) on delete cascade;

-- ─────────────────────────────────────────────────────────────────────────────
-- Bulk import
-- ─────────────────────────────────────────────────────────────────────────────

create table public.import_batches (
    id              uuid primary key default gen_random_uuid(),
    tenant_id       uuid not null references public.tenants(id) on delete cascade,
    kind            text not null check (kind in ('single','zip','csv','zip_csv')),
    status          text not null default 'processing' check (status in ('processing','completed','completed_with_errors','failed')),
    total           int not null default 0,
    created_count   int not null default 0,
    updated_count   int not null default 0,
    error_count     int not null default 0,
    report          jsonb not null default '[]'::jsonb,       -- per-row/per-file outcome incl. unmatched
    created_by      uuid references public.profiles(id),
    created_at      timestamptz not null default now(),
    finished_at     timestamptz
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Portal consent
-- ─────────────────────────────────────────────────────────────────────────────

create table public.consent_versions (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    version     text not null,
    body        text not null,
    is_current  boolean not null default false,
    created_at  timestamptz not null default now(),
    unique (tenant_id, version)
);
create unique index consent_one_current on public.consent_versions (tenant_id) where is_current;

create table public.consent_records (
    id                  uuid primary key default gen_random_uuid(),
    tenant_id           uuid not null references public.tenants(id) on delete cascade,
    candidate_id        uuid not null references public.candidates(id) on delete cascade,
    consent_version_id  uuid not null references public.consent_versions(id),
    application_id      uuid references public.applications(id) on delete set null,
    ip_address          inet,
    user_agent          text,
    granted_at          timestamptz not null default now(),
    withdrawn_at        timestamptz
);

-- ─────────────────────────────────────────────────────────────────────────────
-- updated_at triggers
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.touch_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end; $$;

do $$
declare t text;
begin
    foreach t in array array['tenants','tenant_settings','clients','client_contacts','saved_views','jobs','candidates','applications']
    loop
        execute format('create trigger %I_touch before update on public.%I for each row execute function public.touch_updated_at()', t, t);
    end loop;
end $$;

-- Stage history on application stage change
create or replace function public.log_stage_change() returns trigger language plpgsql as $$
begin
    if new.stage_id is distinct from old.stage_id then
        insert into public.application_stage_history (tenant_id, application_id, from_stage_id, to_stage_id, changed_by)
        values (new.tenant_id, new.id, old.stage_id, new.stage_id, auth.uid());
    end if;
    return new;
end; $$;
create trigger applications_stage_history after update of stage_id on public.applications
    for each row execute function public.log_stage_change();

-- ─────────────────────────────────────────────────────────────────────────────
-- New tenant bootstrap: settings, default pipeline, default consent text
-- ─────────────────────────────────────────────────────────────────────────────

create or replace function public.bootstrap_tenant() returns trigger
language plpgsql security definer set search_path = public as $$
declare p uuid;
begin
    insert into public.tenant_settings (tenant_id) values (new.id);

    insert into public.pipelines (tenant_id, name, is_default) values (new.id, 'Standard', true) returning id into p;
    insert into public.pipeline_stages (tenant_id, pipeline_id, name, position, color, stage_type) values
        (new.id, p, 'New',                 1, '#94A3B8', 'active'),
        (new.id, p, 'Screening',           2, '#60A5FA', 'active'),
        (new.id, p, 'Submitted to Client', 3, '#818CF8', 'active'),
        (new.id, p, 'Client Interview',    4, '#A78BFA', 'active'),
        (new.id, p, 'Offer',               5, '#F59E0B', 'active'),
        (new.id, p, 'Placed',              6, '#10B981', 'placed'),
        (new.id, p, 'Rejected',            7, '#EF4444', 'rejected'),
        (new.id, p, 'Withdrawn',           8, '#6B7280', 'withdrawn');

    insert into public.consent_versions (tenant_id, version, is_current, body) values (new.id, '1.0', true,
        'By submitting this application, I consent to ' || new.name || ' collecting, using and storing the personal '
     || 'information I provide (including my resume, name, email address, phone number and, if provided, LinkedIn '
     || 'profile) for the purpose of evaluating me for this and other employment opportunities, and to sharing it '
     || 'with prospective employers in connection with those opportunities. My information will be retained only as '
     || 'long as needed for these purposes. I can request access to, correction of, or deletion of my information, '
     || 'or withdraw this consent at any time, by contacting ' || new.name || '.');
    return new;
end; $$;
create trigger tenants_bootstrap after insert on public.tenants for each row execute function public.bootstrap_tenant();

-- ─────────────────────────────────────────────────────────────────────────────
-- Row Level Security
-- ─────────────────────────────────────────────────────────────────────────────

alter table public.tenants enable row level security;
create policy tenants_select on public.tenants for select using (public.is_member(id));
create policy tenants_admin  on public.tenants for all using (public.is_platform_admin()) with check (public.is_platform_admin());
create policy tenants_owner_update on public.tenants for update using (public.is_tenant_admin(id));
-- Tenant admins can rebrand but not change their own plan or billing status.
create or replace function public.guard_tenant_billing() returns trigger language plpgsql as $$
begin
    if not public.is_platform_admin() and (new.plan is distinct from old.plan or new.status is distinct from old.status
        or new.stripe_customer_id is distinct from old.stripe_customer_id or new.trial_ends_at is distinct from old.trial_ends_at) then
        raise exception 'Only the platform admin can change billing fields';
    end if;
    return new;
end; $$;
create trigger tenants_guard_billing before update on public.tenants for each row execute function public.guard_tenant_billing();

alter table public.profiles enable row level security;
create policy profiles_self  on public.profiles for select using (id = auth.uid() or public.is_platform_admin()
    or exists (select 1 from public.memberships a join public.memberships b on a.tenant_id = b.tenant_id
               where a.user_id = auth.uid() and b.user_id = profiles.id));
create policy profiles_update_self on public.profiles for update using (id = auth.uid()) with check (id = auth.uid());
-- Nobody can promote themselves to platform admin through the API.
create or replace function public.guard_platform_admin() returns trigger language plpgsql as $$
begin
    if new.is_platform_admin is distinct from old.is_platform_admin and not public.is_platform_admin()
       and current_user not in ('postgres','service_role','supabase_admin') then
        raise exception 'Only the platform admin can change is_platform_admin';
    end if;
    return new;
end; $$;
create trigger profiles_guard_admin before update on public.profiles for each row execute function public.guard_platform_admin();

-- Create a profile row automatically when someone signs up.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, email, full_name)
    values (new.id, new.email, coalesce(new.raw_user_meta_data->>'full_name', new.email))
    on conflict (id) do nothing;
    return new;
end; $$;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

alter table public.memberships enable row level security;
create policy memberships_select on public.memberships for select using (public.is_member(tenant_id));
create policy memberships_manage on public.memberships for all
    using (public.is_tenant_admin(tenant_id)) with check (public.is_tenant_admin(tenant_id));

-- All remaining tenant tables: members of the tenant have full access.
do $$
declare t text;
begin
    foreach t in array array[
        'tenant_settings','clients','client_contacts','pipelines','pipeline_stages','saved_views','jobs',
        'candidates','candidate_documents','applications','application_stage_history','interviews',
        'interview_feedback','activities','mail_accounts','email_messages','email_attachments','inbox_items',
        'ai_feedback','match_scores','import_batches','consent_versions','consent_records']
    loop
        execute format('alter table public.%I enable row level security', t);
        execute format('create policy %I on public.%I for all using (public.is_member(tenant_id)) with check (public.is_member(tenant_id))',
                       t || '_member', t);
    end loop;
end $$;

-- Personal saved views are only visible to their owner.
drop policy saved_views_member on public.saved_views;
create policy saved_views_member on public.saved_views for all
    using (public.is_member(tenant_id) and (user_id is null or user_id = auth.uid()))
    with check (public.is_member(tenant_id) and (user_id is null or user_id = auth.uid()));

-- ─────────────────────────────────────────────────────────────────────────────
-- Public portal view (read by the portal edge function with the service role)
-- ─────────────────────────────────────────────────────────────────────────────

create or replace view public.portal_jobs as
select
    j.id, t.portal_slug, j.tenant_id, j.title, j.reference_code,
    coalesce(j.public_description, j.description) as description,
    case when j.hide_client_name then null else c.name end as client_name,
    j.location, j.city, j.region, j.country, j.work_model, j.employment_type,
    j.salary_min, j.salary_max, j.rate_min, j.rate_max, j.rate_unit, j.currency,
    j.must_have_skills, j.nice_to_have_skills, j.published_at
from public.jobs j
join public.tenants t on t.id = j.tenant_id and t.status = 'active'
left join public.clients c on c.id = j.client_id
where j.is_published and j.status = 'open';

revoke all on public.portal_jobs from anon, authenticated;
