-- Verifies tenant bootstrap and tenant isolation. Run after the stub and migrations.
\set ON_ERROR_STOP on
begin;

insert into auth.users (id, email) values
    ('00000000-0000-0000-0000-00000000000a', 'patty@onpoint.test'),
    ('00000000-0000-0000-0000-00000000000b', 'other@agency.test');
update public.profiles set is_platform_admin = true where id = '00000000-0000-0000-0000-00000000000a';

insert into public.tenants (id, name, portal_slug) values
    ('10000000-0000-0000-0000-000000000001', 'OnPoint Personnel', 'onpoint'),
    ('10000000-0000-0000-0000-000000000002', 'Other Agency', 'other');
insert into public.memberships (tenant_id, user_id, role) values
    ('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-00000000000a', 'owner'),
    ('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-00000000000b', 'owner');

-- Bootstrap created settings, 8 stages, consent text
do $$ begin
    assert (select count(*) from public.tenant_settings) = 2, 'settings not bootstrapped';
    assert (select count(*) from public.pipeline_stages where tenant_id = '10000000-0000-0000-0000-000000000001') = 8, 'stages';
    assert (select count(*) from public.consent_versions where is_current) = 2, 'consent';
end $$;

insert into public.jobs (tenant_id, title, is_published, status) values
    ('10000000-0000-0000-0000-000000000001', 'Epic Ambulatory Analyst', true, 'open'),
    ('10000000-0000-0000-0000-000000000002', 'Other Agency Job', true, 'open');

-- Act as the other agency's owner
set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', true);
do $$ begin
    assert (select count(*) from public.jobs) = 1, 'tenant B should see only its own job';
    assert (select count(*) from public.tenants) = 1, 'tenant B should see only its own tenant';
end $$;

-- Tenant B cannot insert into tenant A
do $$ begin
    begin
        insert into public.jobs (tenant_id, title) values ('10000000-0000-0000-0000-000000000001', 'Sneaky');
        raise exception 'cross-tenant insert was allowed';
    exception when insufficient_privilege then null;
    end;
end $$;

-- Tenant B cannot make itself platform admin
do $$ begin
    begin
        update public.profiles set is_platform_admin = true where id = '00000000-0000-0000-0000-00000000000b';
        raise exception 'self-promotion was allowed';
    exception when raise_exception then
        if sqlerrm = 'self-promotion was allowed' then raise; end if;
    end;
end $$;

-- Tenant B cannot change its own plan
do $$ begin
    begin
        update public.tenants set plan = 'enterprise' where id = '10000000-0000-0000-0000-000000000002';
        raise exception 'plan change was allowed';
    exception when raise_exception then
        if sqlerrm = 'plan change was allowed' then raise; end if;
    end;
end $$;

-- Platform admin sees everything
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000a', true);
do $$ begin
    assert (select count(*) from public.jobs) = 2, 'platform admin should see all jobs';
end $$;

reset role;
do $$ begin
    assert (select count(*) from public.portal_jobs where portal_slug = 'onpoint') = 1, 'portal view';
end $$;

-- Stage history trigger
insert into public.candidates (id, tenant_id, first_name, email) values
    ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'Ana', 'ana@test.com');
insert into public.applications (id, tenant_id, candidate_id, job_id, stage_id)
select '30000000-0000-0000-0000-000000000001', j.tenant_id, '20000000-0000-0000-0000-000000000001', j.id,
       (select id from public.pipeline_stages s where s.tenant_id = j.tenant_id and position = 1)
from public.jobs j where j.title = 'Epic Ambulatory Analyst';
update public.applications set stage_id = (select id from public.pipeline_stages
    where tenant_id = '10000000-0000-0000-0000-000000000001' and position = 2)
where id = '30000000-0000-0000-0000-000000000001';
do $$ begin
    assert (select count(*) from public.application_stage_history) = 1, 'stage history';
end $$;

rollback;
\echo 'ALL RLS TESTS PASSED'
