-- Skills on job applications too. The skills list grows from both the general application and job applications,
-- and a new skill is counted once per person, whichever form they used.

alter table public.applications add column if not exists portal_skills text[];   -- what they chose on the website form

-- Who has used which skill (so each person counts once).
create table if not exists public.portal_skill_uses (
    tenant_id     uuid not null references public.tenants(id) on delete cascade,
    skill         citext not null,
    candidate_id  uuid not null references public.candidates(id) on delete cascade,
    primary key (tenant_id, skill, candidate_id)
);
alter table public.portal_skill_uses enable row level security;   -- no policies: written by the website functions only
insert into public.portal_skill_uses (tenant_id, skill, candidate_id)
select g.tenant_id, s, g.candidate_id from public.general_applications g, unnest(g.skills) s
on conflict do nothing;

-- Clean what was sent: tidy, drop junk, take the list's spelling, no repeats (ignoring case), at most 40.
create or replace function public.portal_clean_skills(t uuid, p_skills text[]) returns text[]
language plpgsql stable security definer set search_path = public as $$
declare out text[] := '{}'; sk text; c text; canon text;
begin
    foreach sk in array coalesce(p_skills, '{}') loop
        c := public.clean_skill(sk);
        continue when c is null;
        canon := null;
        select k.name::text into canon from portal_skills k where k.tenant_id = t and k.name = c::citext;
        c := coalesce(canon, c);
        if not exists (select 1 from unnest(out) x where lower(x) = lower(c)) then out := out || c; end if;
        exit when cardinality(out) >= 40;
    end loop;
    return out;
end $$;

-- Count each skill once per person; a skill typed by applicants joins the website list once enough people used it.
create or replace function public.portal_record_skills(t uuid, p_candidate uuid, p_skills text[]) returns void
language plpgsql security definer set search_path = public as $$
declare sk text; bar int;
begin
    select skill_auto_list_after into bar from tenant_settings where tenant_id = t;
    foreach sk in array coalesce(p_skills, '{}') loop
        insert into portal_skill_uses (tenant_id, skill, candidate_id) values (t, sk, p_candidate) on conflict do nothing;
        continue when not found;   -- this person already counted for this skill
        insert into portal_skills (tenant_id, name, category, status, uses, added_by_applicant)
        values (t, sk, 'Added by applicants', case when coalesce(bar, 2) <= 1 then 'listed' else 'pending' end, 1, true)
        on conflict (tenant_id, name) do update set uses = portal_skills.uses + 1,
            status = case when portal_skills.status = 'pending' and portal_skills.uses + 1 >= coalesce(bar, 2)
                          then 'listed' else portal_skills.status end;
    end loop;
end $$;

create or replace function public.portal_merge_candidate_skills(p_candidate uuid, p_skills text[]) returns void
language sql security definer set search_path = public as $$
    update candidates set skills = (select coalesce(array_agg(x order by x), '{}') from
        (select distinct on (lower(x)) x from unnest(skills || coalesce(p_skills, '{}')) x order by lower(x), x) d)
    where id = p_candidate;
$$;

-- The job form now sends skills too; the skills list is offered with each job.
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
               'skills', coalesce((select jsonb_agg(jsonb_build_object('name', k.name::text, 'category', k.category)
                                                    order by k.category, k.name)
                                   from public.portal_skills k where k.tenant_id = t.id and k.status = 'listed'), '[]'::jsonb),
               'company', t.name)
    from public.jobs j join public.tenants t on t.id = j.tenant_id and t.status = 'active'
    where t.portal_slug = p_slug and j.id = p_job_id and j.is_published and j.status = 'open';
$$;

drop function if exists public.portal_apply(text, uuid, text, text, text, text, text, text, text, text, bigint, uuid, text, text, text);
create or replace function public.portal_apply(
    p_slug text, p_job_id uuid, p_first text, p_last text, p_email text, p_phone text, p_linkedin text,
    p_file_name text, p_storage_path text, p_mime text, p_size bigint, p_consent_version uuid,
    p_ip text, p_ip_hash text, p_user_agent text, p_skills text[] default '{}') returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    t uuid; v_job record; v_cand uuid; v_app uuid; v_stage uuid; v_consent uuid; v_skills text[];
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
    if v_consent is null then select id into v_consent from consent_versions where tenant_id = t and is_current; end if;
    if v_consent is null then return jsonb_build_object('ok', false, 'error', 'no_consent_text'); end if;
    v_skills := public.portal_clean_skills(t, p_skills);

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
    perform public.portal_merge_candidate_skills(v_cand, v_skills);

    update candidate_documents set is_primary = false where candidate_id = v_cand and is_primary;
    insert into candidate_documents (tenant_id, candidate_id, kind, file_name, storage_path, mime_type, size_bytes,
                                     is_primary, needs_parsing)
    values (t, v_cand, 'resume', p_file_name, p_storage_path, p_mime, p_size, true, true);

    select st.id into v_stage from pipeline_stages st join pipelines p on p.id = st.pipeline_id
     where p.tenant_id = t and (p.id = v_job.pipeline_id or (v_job.pipeline_id is null and p.is_default and p.job_id is null))
     order by st.position limit 1;
    insert into applications (tenant_id, candidate_id, job_id, stage_id, source, applied_at, portal_skills)
    values (t, v_cand, p_job_id, v_stage, 'portal', now(), v_skills)
    on conflict (candidate_id, job_id) do update set applied_at = now(), seen_at = null, portal_skills = excluded.portal_skills
    returning id into v_app;
    perform public.portal_record_skills(t, v_cand, v_skills);

    insert into consent_records (tenant_id, candidate_id, consent_version_id, application_id, ip_address, user_agent)
    values (t, v_cand, v_consent, v_app,
            case when p_ip ~ '^[0-9a-fA-F:.]{3,45}$' then p_ip::inet end, left(p_user_agent, 400));
    insert into activities (tenant_id, kind, body, candidate_id, job_id, application_id)
    values (t, 'system', 'Applied on the website for ' || v_job.title
               || case when cardinality(v_skills) > 0 then '. Skills: ' || array_to_string(v_skills, ', ') else '' end,
            v_cand, p_job_id, v_app);
    return jsonb_build_object('ok', true, 'application_id', v_app);
end $$;

create or replace function public.portal_apply_general(
    p_slug text, p_first text, p_last text, p_email text, p_phone text, p_linkedin text, p_skills text[],
    p_file_name text, p_storage_path text, p_mime text, p_size bigint, p_consent_version uuid,
    p_ip text, p_ip_hash text, p_user_agent text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    t uuid; st record; v_cand uuid; v_entry uuid; v_consent uuid; v_skills text[];
begin
    select tn.id into t from tenants tn where tn.portal_slug = p_slug and tn.status = 'active';
    if t is null then return jsonb_build_object('ok', false, 'error', 'not_found'); end if;
    select * into st from tenant_settings where tenant_id = t;
    if not st.general_application_enabled then return jsonb_build_object('ok', false, 'error', 'closed'); end if;
    if (select count(*) from portal_submissions where tenant_id = t and ip_hash = p_ip_hash
          and created_at > now() - interval '15 minutes') >= 5 then
        return jsonb_build_object('ok', false, 'error', 'too_many');
    end if;
    insert into portal_submissions (tenant_id, ip_hash) values (t, p_ip_hash);
    select id into v_consent from consent_versions where tenant_id = t and id = p_consent_version;
    if v_consent is null then select id into v_consent from consent_versions where tenant_id = t and is_current; end if;
    if v_consent is null then return jsonb_build_object('ok', false, 'error', 'no_consent_text'); end if;
    v_skills := public.portal_clean_skills(t, p_skills);

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
    perform public.portal_merge_candidate_skills(v_cand, v_skills);

    update candidate_documents set is_primary = false where candidate_id = v_cand and is_primary;
    insert into candidate_documents (tenant_id, candidate_id, kind, file_name, storage_path, mime_type, size_bytes,
                                     is_primary, needs_parsing)
    values (t, v_cand, 'resume', p_file_name, p_storage_path, p_mime, p_size, true, true);

    insert into general_applications (tenant_id, candidate_id, skills) values (t, v_cand, v_skills)
    on conflict (tenant_id, candidate_id) do update set skills = excluded.skills, applied_at = now(), seen_at = null
    returning id into v_entry;
    perform public.portal_record_skills(t, v_cand, v_skills);

    insert into consent_records (tenant_id, candidate_id, consent_version_id, ip_address, user_agent)
    values (t, v_cand, v_consent, case when p_ip ~ '^[0-9a-fA-F:.]{3,45}$' then p_ip::inet end, left(p_user_agent, 400));
    insert into activities (tenant_id, kind, body, candidate_id)
    values (t, 'system', 'Sent a general application on the website'
               || case when cardinality(v_skills) > 0 then '. Skills: ' || array_to_string(v_skills, ', ') else '' end,
            v_cand);
    return jsonb_build_object('ok', true, 'id', v_entry);
end $$;

revoke all on function public.portal_clean_skills(uuid, text[]) from public, anon, authenticated;
revoke all on function public.portal_record_skills(uuid, uuid, text[]) from public, anon, authenticated;
revoke all on function public.portal_merge_candidate_skills(uuid, text[]) from public, anon, authenticated;
revoke all on function public.portal_get_job(text, uuid) from public, anon, authenticated;
revoke all on function public.portal_apply(text, uuid, text, text, text, text, text, text, text, text, bigint, uuid, text, text, text, text[])
    from public, anon, authenticated;
revoke all on function public.portal_apply_general(text, text, text, text, text, text, text[], text, text, text, bigint, uuid, text, text, text)
    from public, anon, authenticated;
grant execute on function public.portal_get_job(text, uuid) to service_role;
grant execute on function public.portal_apply(text, uuid, text, text, text, text, text, text, text, text, bigint, uuid, text, text, text, text[])
    to service_role;
grant execute on function public.portal_apply_general(text, text, text, text, text, text, text[], text, text, text, bigint, uuid, text, text, text)
    to service_role;
