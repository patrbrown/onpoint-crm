-- Job descriptions from email attachments are kept as Markdown, word for word.
alter table public.email_attachments add column if not exists markdown text;

-- Jev (TypeSafe AI) for email triage, configurable per workspace by its admins.
alter table public.tenant_settings
    add column if not exists triage_provider text not null default 'llm',
    add column if not exists jev_model text not null default 'jev-latest',
    add column if not exists jev_config jsonb not null default '{}'::jsonb,
    add column if not exists review_below_confidence numeric(3,2) not null default 0.60;

do $$ begin
    alter table public.tenant_settings add constraint tenant_settings_triage_provider_check
        check (triage_provider in ('llm', 'jev'));
exception when duplicate_object then null; end $$;

-- How each email was triaged (which provider, and Jev's probability for every type) for review and tuning.
alter table public.email_messages add column if not exists triage jsonb;
