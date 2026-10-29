-- Email agent: feedback can point at an email directly (for emails the agent ignored but shouldn't have).
alter table public.ai_feedback
    add column if not exists email_id uuid references public.email_messages(id) on delete cascade;
create index if not exists ai_feedback_email on public.ai_feedback (email_id);
create index if not exists inbox_items_email on public.inbox_items (email_id);
create index if not exists email_attachments_email on public.email_attachments (email_id);
