# OnPoint CRM

A lightweight, agentic recruiting CRM for OnPoint Personnel, built to be white-labeled for other agencies.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Status

| Phase | What | State |
|---|---|---|
| v1a | Database, clients/contacts, jobs, candidates, pipelines, saved views, interview feedback, notes, resume upload (single + ZIP/CSV bulk), web UI | **Done** |
| v1b | Outlook email agent (read-only), review inbox, feedback that trains the agent, automatic mode | **Done** |
| v1c | Candidate portal + consent | Next |
| v1d | Website job posting (embed for Replit) | Next |

## One-time setup

1. **Supabase database:** *SQL Editor* → paste and run `supabase/migrations/20261029000001_core_schema.sql`.
   Then *Storage* → create a **private** bucket named `documents`.
2. **Your login and workspace:** *Authentication → Users → Add user* (tick *Auto Confirm User*), then in the
   SQL Editor:
   ```sql
   update public.profiles set is_platform_admin = true where email = 'you@onpointpersonnel.com';
   insert into public.tenants (name, portal_slug, website_url, plan)
   values ('OnPoint Personnel', 'onpoint', 'https://www.onpointpersonnel.com', 'internal');
   insert into public.memberships (tenant_id, user_id, role)
   select t.id, p.id, 'owner' from public.tenants t, public.profiles p
   where t.portal_slug = 'onpoint' and p.email = 'you@onpointpersonnel.com';
   ```
3. **Keys:** copy `.env.example` to `.env` and fill it in. Everything Supabase is under *Project Settings*:
   the connection string under *Database* (use the **Session pooler** string), and the URL plus the
   publishable and secret keys under *API Keys*. Add your Anthropic API key, and the Microsoft
   Application (client) ID and Directory (tenant) ID as `MS_CLIENT_ID` and `MS_TENANT_ID`.
4. **Run:** with Docker Desktop open, in this folder:
   ```
   docker compose up -d --build
   ```
   Then open **http://localhost:3000** and sign in. After pulling new code, run the same command again.
5. **AI models (optional):** Claude does everything by default. To cut costs, add `OPENROUTER_API_KEY` (and/or
   `TYPESAFE_API_KEY` for Jev email sorting) to `.env`, run `docker compose up -d`, then choose models per task in
   *Settings → AI models* and *Settings → Email sorting*. Each setting has a **Test** button.
6. **Outlook:** on the *Email inbox* page choose *Connect Outlook*, open the Microsoft link it shows, enter the
   code and sign in. New mail is then checked every 15 minutes (change it in *Settings*) while the app runs.
   The first check looks back 7 days. Access is read-only: nothing in Outlook is moved, flagged or deleted.

## Database updates

When a new file appears in `supabase/migrations/`, paste it into the Supabase SQL Editor and run it once.
Files run in name order; each only needs to run once.

## Development

```bash
# API tests: apply the real migration to a throwaway Postgres (with pgvector) and run with RLS on
cd api && pip install -r requirements.txt
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/crm_test pytest

# Web UI without Supabase login: leave NEXT_PUBLIC_SUPABASE_* empty and set DEV_USER_ID for the API
cd web && npm install && npm run dev
```
