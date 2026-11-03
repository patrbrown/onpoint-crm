-- Outlook sign-in tokens, encrypted, so a hosted CRM (where files don't survive restarts) stays connected.
-- Only the CRM's back end reads this (service connection); no one can read it through the app or the API.
create table if not exists public.mail_tokens (
    cache_key   text primary key,                 -- the mail account id
    ciphertext  text not null,                    -- encrypted with TOKEN_ENCRYPTION_KEY (never stored in the database)
    updated_at  timestamptz not null default now()
);
alter table public.mail_tokens enable row level security;   -- no policies: invisible to signed-in users
revoke all on public.mail_tokens from anon, authenticated;
