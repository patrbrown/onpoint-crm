# OnPoint CRM

A lightweight, agentic recruiting CRM for OnPoint Personnel, built to be white-labeled for other agencies.
See [ARCHITECTURE.md](ARCHITECTURE.md) for the design.

## Status

| Phase | What | State |
|---|---|---|
| v1a | Database, clients/contacts, jobs, candidates, applications, custom pipelines, saved layouts, interviews + feedback, resume upload (single + ZIP/CSV bulk) | **API built and tested** — web UI next |
| v1b | Outlook email agent (read-only), review inbox, feedback, auto-mode toggle | Waiting on Microsoft app registration |
| v1c | Candidate portal + consent | Not started |
| v1d | Website job posting (embed for Replit) | Not started |

## One-time setup

1. **Supabase:** create a project → *SQL Editor* → paste and run
   `supabase/migrations/20261029000001_core_schema.sql`.
   Then *Storage* → create a **private** bucket named `documents`.
2. **Sign up** in the Supabase dashboard (*Authentication → Users → Add user*) with your email, then in
   the SQL Editor:
   ```sql
   update public.profiles set is_platform_admin = true where email = 'you@onpointpersonnel.com';
   insert into public.tenants (name, portal_slug, website_url, plan)
   values ('OnPoint Personnel', 'onpoint', 'https://www.onpointpersonnel.com', 'internal');
   insert into public.memberships (tenant_id, user_id, role)
   select t.id, p.id, 'owner' from public.tenants t, public.profiles p
   where t.portal_slug = 'onpoint' and p.email = 'you@onpointpersonnel.com';
   ```
3. Copy `.env.example` to `.env` and fill it in (set `DEV_USER_ID` to your user id from step 2).
4. `docker compose up -d --build`, then open http://localhost:8000/docs to try every endpoint.

## Tests

```bash
cd api
pip install -r requirements.txt
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/crm_test pytest
```
The API tests apply the real migration to a throwaway Postgres (with pgvector) and run with Row Level
Security on, so cross-tenant access is tested exactly as in production.
