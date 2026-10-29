-- A model choice per task (Claude, OpenRouter, or a local/private model), each with optional fallback to Claude.
alter table public.tenant_settings add column if not exists model_routes jsonb not null default '{}'::jsonb;

alter table public.tenant_settings drop constraint if exists tenant_settings_llm_provider_check;
alter table public.tenant_settings add constraint tenant_settings_llm_provider_check
    check (llm_provider in ('anthropic', 'openrouter', 'openai_compatible'));
