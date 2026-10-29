# OnPoint CRM — Architecture

A lightweight, agentic recruiting CRM. Built first for OnPoint Personnel, designed from day one to be
white-labeled and sold to other small agencies on a monthly subscription.

## Components

```
                        ┌──────────────────────────── Supabase (cloud) ────────────────────────────┐
                        │  Postgres + pgvector   │   Storage (resumes)   │   Auth   │  Edge Functions │
                        └───────▲───────────────────────▲──────────────────────────────────▲─────────┘
                                │                       │                                  │
            ┌───────────────────┴───────┐               │                 ┌────────────────┴───────────────┐
            │  Desktop (Docker Compose)  │               │                 │  Public (no PC required)       │
            │                            │               │                 │                                │
            │  web/   Next.js CRM UI     │               │                 │  portal-api  (edge function)   │
            │  api/   FastAPI            │───────────────┘                 │   GET  /jobs   JSON + XML feed │
            │  worker Email agent (15m)  │                                 │   POST /apply  application     │
            └─────────────┬──────────────┘                                 │  embed.js  → onpointpersonnel  │
                          │ Microsoft Graph (Mail.Read, delegated)         └────────────────────────────────┘
                          ▼
                    Outlook inbox (read-only)
```

| Component | Runs on (v1) | Moves to (later) | Purpose |
|---|---|---|---|
| Database / storage / auth | Supabase | — | Single source of truth, multi-tenant via `tenant_id` + RLS |
| `api/` | Desktop Docker | Fly.io / Render / Azure | CRUD, uploads, imports, AI scoring, inbox review |
| `worker` | Desktop Docker | Same host as api, or scheduled cloud job | Polls Outlook every 15 min, classifies, extracts |
| `web/` | Desktop Docker | Vercel | Recruiter UI |
| `supabase/functions/portal-api` | Supabase | — | Public job list, job-board feed, application intake |
| `portal/embed.js` | Supabase Storage (public) | CDN | Script tag pasted into the Replit site |

**Why the database is cloud from day one:** a website cannot reach an app on a home PC, and the
product must become multi-tenant SaaS. Putting data in Supabase now means no migration later, and
applications arrive even when the PC is off.

## Multi-tenancy and white-labeling

- Every business table carries `tenant_id`. Row Level Security limits each user to tenants they are a
  member of (`memberships`).
- `profiles.is_platform_admin` marks the platform owner, who can see and onboard all tenants.
- `tenants` holds branding (name, logo, colours, portal slug, custom domain) and billing fields
  (`plan`, `status`, `stripe_customer_id`, `trial_ends_at`). Stripe wiring comes later; the columns exist now.
- The portal and embed resolve the tenant from `portal_slug`, so each agency gets its own branded job board.

## Email agent (Outlook)

1. Microsoft Graph, **delegated `Mail.Read` + `offline_access` + `User.Read`**, device-code sign-in once.
   Mail.Read is read-only, so the agent physically cannot move, flag, delete or send mail.
2. Every 15 minutes the worker fetches new messages since the last checkpoint (`mail_accounts.last_sync_at`).
3. Each message and its attachments (PDF/DOCX text extracted) go to the LLM with a classification prompt:
   `job_requisition | resume | interview_feedback | client_correspondence | candidate_reply | other`.
4. Relevant ones get structured extraction (job fields, or candidate fields) and become `inbox_items`.
5. **Review mode (default):** items wait in the Inbox for approve / edit / reject.
   **Auto mode (toggle):** items at or above `auto_approve_threshold` confidence are committed directly.
6. Every review decision and every correction is stored in `ai_feedback`, which is fed back as
   few-shot examples so the agent improves over time.
7. `email_messages` stores Graph message IDs, so nothing is processed twice.
8. `mail_accounts` is one-per-inbox, so adding colleagues' inboxes later is a data change, not a rewrite.

## Swappable LLM

`api/app/llm/` defines one `LLMProvider` interface with `complete()` and `complete_json()`.
Implementations:
- `AnthropicProvider` — Claude API (default).
- `OpenAICompatibleProvider` — any OpenAI-compatible endpoint: Ollama, vLLM, LM Studio, a sovereign on-prem model.

Selected per tenant (`tenant_settings.llm_provider`, `llm_model`), with env defaults. All prompts live in
`api/app/agent/prompts/`, independent of the provider.

## AI resume scoring

- Toggle per tenant: `tenant_settings.ai_scoring_enabled`.
- Scores a candidate against a job (0–100) with strengths, gaps and a short rationale, stored on `match_scores`.
- Recruiter thumbs up/down plus a corrected score go to `ai_feedback` (target `match_score`).

## Candidate import

- **One-off:** PDF or DOCX → text extraction → LLM extraction → candidate draft.
- **Bulk:** ZIP of resumes + CSV. The CSV rows are matched to files by a `resume_file` column if present,
  otherwise by fuzzy name match (`First Last` vs the file name). Unmatched files and rows are reported,
  not dropped. Progress is tracked in `import_batches`.

## Portal and website

- `GET  /portal-api/{slug}/jobs` — published jobs (JSON). `?format=xml` gives an Indeed-style XML feed
  for job boards later.
- `POST /portal-api/{slug}/apply` — multipart: name, email, phone, resume (required), LinkedIn (optional),
  consent checkbox (required). Stores the resume, creates or matches the candidate, creates the application,
  records consent text, version, timestamp and IP.
- `embed.js` renders the job list and application form inside any website:
  `<div id="onpoint-jobs"></div><script src=".../embed.js" data-tenant="onpoint"></script>`
- Consent text is PIPEDA-oriented with GDPR-compatible wording, stored versioned in `consent_versions`.

## Pipelines and layouts

- `pipelines` + `pipeline_stages` are per tenant and editable (rename, reorder, colour, mark as
  "placed"/"rejected" terminal stages). A job can use the default pipeline or its own.
- `saved_views` stores the user's layouts (columns, filters, sort, board vs table) per entity.

## Interview feedback and contacts

- `interviews` (who, when, round, type) and `interview_feedback` (scorecard ratings per criterion,
  overall rating, recommendation, notes, submitted by). Interview feedback found in email becomes an
  inbox item linked to the right application.
- `client_contacts` plus `activities` (calls, emails, notes, meetings) on clients, contacts, candidates and jobs.

## Roadmap

1. **v1a — Database + manual CRM:** schema, auth, clients/contacts, jobs, candidates, applications,
   pipelines, uploads (one-off + bulk).
2. **v1b — Outlook agent:** Graph sign-in, 15-minute polling, classification/extraction, Inbox review,
   feedback, auto-mode toggle.
3. **v1c — Portal:** edge function, embed.js, consent, application intake.
4. **v1d — Website posting:** publish/unpublish from the CRM, Replit embed instructions.
5. **Later:** hosted portal on Vercel, job-board XML feeds, cloud worker, multi-inbox, Stripe billing,
   tenant onboarding, fraud checks and natural-language agent interface from the earlier ATS.
