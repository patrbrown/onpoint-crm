-- General application on the careers page: candidates send their resume, contact details and skills without
-- choosing a job. Skills come from a list that grows as applicants add their own.

-- ── Settings ────────────────────────────────────────────────────────────────
alter table public.tenant_settings add column if not exists general_application_enabled boolean not null default true;
alter table public.tenant_settings add column if not exists general_application_title text not null default 'General application';
alter table public.tenant_settings add column if not exists general_application_intro text not null default
    'Don’t see the right role? Send us your resume and tell us your skills. We’ll contact you when a matching opportunity comes up.';
-- A skill an applicant typed joins the public list once this many different applicants have used it.
alter table public.tenant_settings add column if not exists skill_auto_list_after int not null default 2
    check (skill_auto_list_after between 1 and 100);

-- ── Submissions ─────────────────────────────────────────────────────────────
create table if not exists public.general_applications (
    id            uuid primary key default gen_random_uuid(),
    tenant_id     uuid not null references public.tenants(id) on delete cascade,
    candidate_id  uuid not null references public.candidates(id) on delete cascade,
    skills        text[] not null default '{}',     -- what they ticked or typed on the form
    applied_at    timestamptz not null default now(),
    seen_at       timestamptz,
    unique (tenant_id, candidate_id)
);
create index if not exists general_applications_new on public.general_applications (tenant_id) where seen_at is null;
alter table public.general_applications enable row level security;
drop policy if exists general_applications_member on public.general_applications;
create policy general_applications_member on public.general_applications for all
    using (public.is_member(tenant_id)) with check (public.is_member(tenant_id));
grant select, insert, update, delete on public.general_applications to authenticated;

-- ── Skills list ─────────────────────────────────────────────────────────────
-- listed: shown on the website; pending: typed by applicants, not yet shown; hidden: never shown.
create table if not exists public.portal_skills (
    id          uuid primary key default gen_random_uuid(),
    tenant_id   uuid not null references public.tenants(id) on delete cascade,
    name        citext not null,
    category    text not null default 'Other',
    status      text not null default 'listed' check (status in ('listed', 'pending', 'hidden')),
    uses        int not null default 0,                -- applicants who picked it
    added_by_applicant boolean not null default false,
    created_at  timestamptz not null default now(),
    unique (tenant_id, name)
);
alter table public.portal_skills enable row level security;
drop policy if exists portal_skills_member on public.portal_skills;
create policy portal_skills_member on public.portal_skills for all
    using (public.is_member(tenant_id)) with check (public.is_member(tenant_id));
grant select, insert, update, delete on public.portal_skills to authenticated;

create or replace function public.seed_portal_skills(t uuid) returns void
language sql security definer set search_path = public as $$
    insert into public.portal_skills (tenant_id, name, category)
    select t, s.name, s.category from (values
        ('Epic Ambulatory','Epic'),('Epic ClinDoc','Epic'),('Epic ASAP','Epic'),('Epic OpTime','Epic'),
        ('Epic Anesthesia','Epic'),('Epic Beaker','Epic'),('Epic Willow','Epic'),('Epic Radiant','Epic'),
        ('Epic Cupid','Epic'),('Epic Beacon','Epic'),('Epic Stork','Epic'),('Epic Cadence','Epic'),
        ('Epic Prelude','Epic'),('Epic Grand Central','Epic'),('Epic Resolute HB','Epic'),('Epic Resolute PB','Epic'),
        ('Epic Tapestry','Epic'),('Epic Healthy Planet','Epic'),('Epic MyChart','Epic'),('Epic Bridges','Epic'),
        ('Epic Clarity','Epic'),('Epic Caboodle','Epic'),('Epic Cogito','Epic'),('Epic Security','Epic'),
        ('Epic Credentialed Trainer','Epic'),
        ('Cerner PowerChart','Oracle Health (Cerner)'),('Cerner FirstNet','Oracle Health (Cerner)'),
        ('Cerner SurgiNet','Oracle Health (Cerner)'),('Cerner PathNet','Oracle Health (Cerner)'),
        ('Cerner PharmNet','Oracle Health (Cerner)'),('Cerner RadNet','Oracle Health (Cerner)'),
        ('Cerner Revenue Cycle','Oracle Health (Cerner)'),('Cerner CCL','Oracle Health (Cerner)'),
        ('MEDITECH Expanse','Other clinical systems'),('MEDITECH Magic / C/S','Other clinical systems'),
        ('Sunquest','Other clinical systems'),('PACS','Other clinical systems'),('Allscripts','Other clinical systems'),
        ('HL7','Integration and data'),('FHIR','Integration and data'),('Rhapsody','Integration and data'),
        ('Cloverleaf','Integration and data'),('Mirth Connect','Integration and data'),('SQL','Integration and data'),
        ('Power BI','Integration and data'),('Crystal Reports','Integration and data'),('Data analysis','Integration and data'),
        ('Project management','Roles'),('Business analysis','Roles'),('Clinical informatics','Roles'),
        ('Application analyst','Roles'),('Training','Roles'),('Go-live support','Roles'),('Testing / QA','Roles'),
        ('Change management','Roles'),('Registered nurse (RN)','Roles'),('Pharmacist','Roles'),
        ('Medical laboratory technologist','Roles'),
        ('ITIL','Infrastructure'),('ServiceNow','Infrastructure'),('Windows Server','Infrastructure'),
        ('Linux / UNIX','Infrastructure'),('Azure','Infrastructure'),('AWS','Infrastructure'),
        ('Networking','Infrastructure'),('Cybersecurity','Infrastructure'),('Citrix','Infrastructure')
    ) as s(name, category)
    on conflict (tenant_id, name) do nothing;
$$;
do $$ begin perform public.seed_portal_skills(id) from public.tenants; end $$;

create or replace function public.tenant_seed_skills() returns trigger
language plpgsql security definer set search_path = public as $$
begin perform public.seed_portal_skills(new.id); return new; end $$;
drop trigger if exists tenants_seed_skills on public.tenants;
create trigger tenants_seed_skills after insert on public.tenants for each row execute function public.tenant_seed_skills();

-- ── What the website reads ──────────────────────────────────────────────────
create or replace function public.portal_general(p_slug text) returns jsonb
language sql stable security definer set search_path = public as $$
    select case when s.general_application_enabled then jsonb_build_object(
        'title', s.general_application_title, 'intro', s.general_application_intro, 'company', t.name,
        'skills', coalesce((select jsonb_agg(jsonb_build_object('name', k.name::text, 'category', k.category)
                                             order by k.category, k.name)
                            from public.portal_skills k where k.tenant_id = t.id and k.status = 'listed'), '[]'::jsonb),
        'consent', (select jsonb_build_object('id', cv.id, 'body', cv.body) from public.consent_versions cv
                    where cv.tenant_id = t.id and cv.is_current)) end
    from public.tenants t join public.tenant_settings s on s.tenant_id = t.id
    where t.portal_slug = p_slug and t.status = 'active';
$$;

-- Tidy what an applicant typed into a usable skill name, or null if it doesn't look like one.
create or replace function public.clean_skill(s text) returns text language sql immutable as $$
    select case when length(c) < 2 or length(c) > 60 or c ~* '(https?:|www\.|[<>@{}])' or c !~ '[[:alpha:]]'
                then null else c end
    from (select btrim(regexp_replace(regexp_replace(coalesce(s, ''), '[[:cntrl:]]', '', 'g'), '\s+', ' ', 'g')) as c) x;
$$;

-- ── A general application from the website ──────────────────────────────────
create or replace function public.portal_apply_general(
    p_slug text, p_first text, p_last text, p_email text, p_phone text, p_linkedin text, p_skills text[],
    p_file_name text, p_storage_path text, p_mime text, p_size bigint, p_consent_version uuid,
    p_ip text, p_ip_hash text, p_user_agent text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
    t uuid; st record; v_cand uuid; v_entry uuid; v_consent uuid; v_skills text[]; v_prev text[]; sk text;
    c text; canon text;
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

    -- Skills: cleaned, de-duplicated (ignoring case), at most 40. A typed skill that matches one on the list
    -- takes the list's spelling.
    v_skills := '{}';
    foreach sk in array coalesce(p_skills, '{}') loop
        c := public.clean_skill(sk);
        continue when c is null;
        select k.name::text into canon from portal_skills k where k.tenant_id = t and k.name = c::citext;
        c := coalesce(canon, c);
        canon := null;
        if not exists (select 1 from unnest(v_skills) x where lower(x) = lower(c)) then v_skills := v_skills || c; end if;
        exit when cardinality(v_skills) >= 40;
    end loop;
    -- Skills this person already gave last time aren't counted twice.
    select g.skills into v_prev from general_applications g
     join candidates cc on cc.id = g.candidate_id where g.tenant_id = t and cc.email = p_email::citext;

    select id into v_cand from candidates where tenant_id = t and email = p_email::citext;
    if v_cand is null then
        insert into candidates (tenant_id, first_name, last_name, email, phone, linkedin_url, source, skills)
        values (t, p_first, nullif(p_last, ''), p_email, nullif(p_phone, ''), nullif(p_linkedin, ''), 'portal', v_skills)
        returning id into v_cand;
    else
        update candidates set
            last_name    = coalesce(nullif(last_name, ''), nullif(p_last, '')),
            phone        = coalesce(nullif(phone, ''), nullif(p_phone, '')),
            linkedin_url = coalesce(nullif(linkedin_url, ''), nullif(p_linkedin, '')),
            skills       = (select coalesce(array_agg(x order by x), '{}') from
                              (select distinct on (lower(x)) x from unnest(skills || v_skills) x order by lower(x), x) d)
        where id = v_cand;
    end if;

    update candidate_documents set is_primary = false where candidate_id = v_cand and is_primary;
    insert into candidate_documents (tenant_id, candidate_id, kind, file_name, storage_path, mime_type, size_bytes,
                                     is_primary, needs_parsing)
    values (t, v_cand, 'resume', p_file_name, p_storage_path, p_mime, p_size, true, true);

    insert into general_applications (tenant_id, candidate_id, skills) values (t, v_cand, v_skills)
    on conflict (tenant_id, candidate_id) do update set skills = excluded.skills, applied_at = now(), seen_at = null
    returning id into v_entry;

    -- Count each skill once per applicant; a new typed skill waits until enough people have used it.
    foreach sk in array v_skills loop
        continue when exists (select 1 from unnest(coalesce(v_prev, '{}')) x where lower(x) = lower(sk));
        insert into portal_skills (tenant_id, name, category, status, uses, added_by_applicant)
        values (t, sk, 'Added by applicants', 'pending', 1, true)
        on conflict (tenant_id, name) do update set uses = portal_skills.uses + 1,
            status = case when portal_skills.status = 'pending' and portal_skills.uses + 1 >= st.skill_auto_list_after
                          then 'listed' else portal_skills.status end;
    end loop;
    update portal_skills set status = 'listed'
     where tenant_id = t and status = 'pending' and uses >= st.skill_auto_list_after;

    insert into consent_records (tenant_id, candidate_id, consent_version_id, ip_address, user_agent)
    values (t, v_cand, v_consent, case when p_ip ~ '^[0-9a-fA-F:.]{3,45}$' then p_ip::inet end, left(p_user_agent, 400));
    insert into activities (tenant_id, kind, body, candidate_id)
    values (t, 'system', 'Sent a general application on the website'
               || case when cardinality(v_skills) > 0 then '. Skills: ' || array_to_string(v_skills, ', ') else '' end,
            v_cand);
    return jsonb_build_object('ok', true, 'id', v_entry);
end $$;

revoke all on function public.portal_general(text) from public, anon, authenticated;
revoke all on function public.portal_apply_general(text, text, text, text, text, text, text[], text, text, text, bigint, uuid, text, text, text)
    from public, anon, authenticated;
grant execute on function public.portal_general(text) to service_role;
grant execute on function public.portal_apply_general(text, text, text, text, text, text, text[], text, text, text, bigint, uuid, text, text, text)
    to service_role;
