-- Careers page on the agency website: published jobs are read, and applications received, by the `careers`
-- Edge Function (supabase/functions/careers). It uses the service role and only these two functions.

-- New applicants: an application from the website stays "new" until someone opens it in the CRM.
alter table public.applications add column if not exists seen_at timestamptz;
alter table public.applications add column if not exists applied_at timestamptz;
create index if not exists applications_new_portal on public.applications (tenant_id)
    where source = 'portal' and seen_at is null;

-- Resumes received from the website are read by the CRM (text + AI) the next time it runs.
alter table public.candidate_documents add column if not exists needs_parsing boolean not null default false;
alter table public.candidate_documents add column if not exists parse_attempts int not null default 0;
alter table public.candidate_documents add column if not exists parse_error text;
create index if not exists candidate_documents_to_parse on public.candidate_documents (created_at) where needs_parsing;

-- Light abuse protection: a few applications per visitor per 15 minutes. Only a hash of the IP is kept.
create table if not exists public.portal_submissions (
    id          bigint generated always as identity primary key,
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    ip_hash     text not null,
    created_at  timestamptz not null default now()
);
create index if not exists portal_submissions_recent on public.portal_submissions (tenant_id, ip_hash, created_at desc);
alter table public.portal_submissions enable row level security;   -- no policies: the service role only

-- Consent text: also say data may be stored outside Canada (Supabase can host there). Replaces only the
-- untouched default; wording edited in Settings → Website is left alone. New workspaces get the same text.
create or replace function public.default_consent_text(company text) returns text language sql immutable as $$
    select 'By submitting this application, I consent to ' || company || ' collecting, using and storing the personal '
        || 'information I provide (my resume, name, email address, phone number and, if provided, LinkedIn profile) to '
        || 'evaluate me for this and other employment opportunities, and to sharing it with prospective employers in '
        || 'connection with those opportunities. I understand my information may be stored and processed by '
        || company || '''s service providers, which may be located outside Canada. My information is kept only as long '
        || 'as needed for these purposes. I can ask to see, correct or delete my information, or withdraw this consent, '
        || 'at any time by contacting ' || company || '.';
$$;

update public.consent_versions cv set is_current = false
 where cv.is_current and cv.version = '1.0' and cv.body like 'By submitting this application, I consent to %'
   and not exists (select 1 from public.consent_versions x where x.tenant_id = cv.tenant_id and x.version = '1.1');
insert into public.consent_versions (tenant_id, version, is_current, body)
select t.id, '1.1', true, public.default_consent_text(t.name)
from public.tenants t
where not exists (select 1 from public.consent_versions x where x.tenant_id = t.id and x.is_current)
  and not exists (select 1 from public.consent_versions x where x.tenant_id = t.id and x.version = '1.1');

create or replace function public.tenant_default_consent() returns trigger
language plpgsql security definer set search_path = public as $$
begin
    update public.consent_versions set body = public.default_consent_text(new.name)
     where tenant_id = new.id and version = '1.0' and body like 'By submitting this application, I consent to %';
    return new;
end $$;
drop trigger if exists tenants_consent_text on public.tenants;
create trigger tenants_consent_text after insert on public.tenants   -- runs after tenants_bootstrap (name order)
    for each row execute function public.tenant_default_consent();

-- ── What the website may read ───────────────────────────────────────────────
-- Never the client's name, fees, contacts or notes.
create or replace function public.portal_list_jobs(p_slug text) returns jsonb
language sql stable security definer set search_path = public as $$
    select coalesce(jsonb_agg(jsonb_build_object(
               'id', j.id, 'title', j.title,
               'location', coalesce(nullif(j.location, ''), nullif(concat_ws(', ', j.city, j.region), '')),
               'work_model', j.work_model, 'employment_type', j.employment_type,
               'posted', j.published_at) order by j.published_at desc nulls last), '[]'::jsonb)
    from public.jobs j join public.tenants t on t.id = j.tenant_id and t.status = 'active'
    where t.portal_slug = p_slug and j.is_published and j.status = 'open';
$$;

create or replace function public.portal_get_job(p_slug text, p_job_id uuid) returns jsonb
language sql stable security definer set search_path = public as $$
    select jsonb_build_object(
               'job', jsonb_build_object(
                   'id', j.id, 'title', j.title,
                   'location', coalesce(nullif(j.location, ''), nullif(concat_ws(', ', j.city, j.region), '')),
                   'work_model', j.work_model, 'employment_type', j.employment_type, 'posted', j.published_at,
                   'description', coalesce(nullif(j.public_description, ''), j.description)),
               'consent', (select jsonb_build_object('id', cv.id, 'body', cv.body) from public.consent_versions cv
                           where cv.tenant_id = t.id and cv.is_current),
               'company', t.name)
    from public.jobs j join public.tenants t on t.id = j.tenant_id and t.status = 'active'
    where t.portal_slug = p_slug and j.id = p_job_id and j.is_published and j.status = 'open';
$$;

create or replace function public.portal_tenant(p_slug text) returns uuid
language sql stable security definer set search_path = public as $$
    select id from public.tenants where portal_slug = p_slug and status = 'active';
$$;

-- ── An application from the website ─────────────────────────────────────────
-- The resume file is already in Storage (uploaded by the Edge Function). Creates or updates the candidate
-- (details already on file are kept), attaches the resume, links them to the job and records consent.
create or replace function public.portal_apply(
    p_slug text, p_job_id uuid, p_first text, p_last text, p_email text, p_phone text, p_linkedin text,
    p_file_name text, p_storage_path text, p_mime text, p_size bigint, p_consent_version uuid,
    p_ip text, p_ip_hash text, p_user_agent text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    t uuid; v_job record; v_cand uuid; v_app uuid; v_stage uuid; v_consent uuid;
begin
    select id into t from tenants where portal_slug = p_slug and status = 'active';
    if t is null then return jsonb_build_object('ok', false, 'error', 'not_found'); end if;
    select id, title, pipeline_id into v_job from jobs
     where tenant_id = t and id = p_job_id and is_published and status = 'open';
    if not found then return jsonb_build_object('ok', false, 'error', 'job_closed'); end if;
    if (select count(*) from portal_submissions where tenant_id = t and ip_hash = p_ip_hash
          and created_at > now() - interval '15 minutes') >= 5 then
        return jsonb_build_object('ok', false, 'error', 'too_many');
    end if;
    insert into portal_submissions (tenant_id, ip_hash) values (t, p_ip_hash);
    select id into v_consent from consent_versions where tenant_id = t and id = p_consent_version;
    if v_consent is null then
        select id into v_consent from consent_versions where tenant_id = t and is_current;
    end if;
    if v_consent is null then return jsonb_build_object('ok', false, 'error', 'no_consent_text'); end if;

    select id into v_cand from candidates where tenant_id = t and email = p_email::citext;
    if v_cand is null then
        insert into candidates (tenant_id, first_name, last_name, email, phone, linkedin_url, source)
        values (t, p_first, nullif(p_last, ''), p_email, nullif(p_phone, ''), nullif(p_linkedin, ''), 'portal')
        returning id into v_cand;
    else
        update candidates set
            last_name    = coalesce(nullif(last_name, ''), nullif(p_last, '')),
            phone        = coalesce(nullif(phone, ''), nullif(p_phone, '')),
            linkedin_url = coalesce(nullif(linkedin_url, ''), nullif(p_linkedin, ''))
        where id = v_cand;
    end if;

    update candidate_documents set is_primary = false where candidate_id = v_cand and is_primary;
    insert into candidate_documents (tenant_id, candidate_id, kind, file_name, storage_path, mime_type, size_bytes,
                                     is_primary, needs_parsing)
    values (t, v_cand, 'resume', p_file_name, p_storage_path, p_mime, p_size, true, true);

    select st.id into v_stage from pipeline_stages st join pipelines p on p.id = st.pipeline_id
     where p.tenant_id = t and (p.id = v_job.pipeline_id or (v_job.pipeline_id is null and p.is_default and p.job_id is null))
     order by st.position limit 1;
    insert into applications (tenant_id, candidate_id, job_id, stage_id, source, applied_at)
    values (t, v_cand, p_job_id, v_stage, 'portal', now())
    on conflict (candidate_id, job_id) do update set applied_at = now(), seen_at = null
    returning id into v_app;

    insert into consent_records (tenant_id, candidate_id, consent_version_id, application_id, ip_address, user_agent)
    values (t, v_cand, v_consent, v_app,
            case when p_ip ~ '^[0-9a-fA-F:.]{3,45}$' then p_ip::inet end, left(p_user_agent, 400));
    insert into activities (tenant_id, kind, body, candidate_id, job_id, application_id)
    values (t, 'system', 'Applied on the website for ' || v_job.title, v_cand, p_job_id, v_app);
    return jsonb_build_object('ok', true, 'application_id', v_app);
end $$;

revoke all on function public.portal_list_jobs(text) from public, anon, authenticated;
revoke all on function public.portal_get_job(text, uuid) from public, anon, authenticated;
revoke all on function public.portal_tenant(text) from public, anon, authenticated;
revoke all on function public.portal_apply(text, uuid, text, text, text, text, text, text, text, text, bigint, uuid, text, text, text)
    from public, anon, authenticated;
grant execute on function public.portal_list_jobs(text) to service_role;
grant execute on function public.portal_get_job(text, uuid) to service_role;
grant execute on function public.portal_tenant(text) to service_role;
grant execute on function public.portal_apply(text, uuid, text, text, text, text, text, text, text, text, bigint, uuid, text, text, text)
    to service_role;
