# Putting the CRM online (Netlify + Render)

| Part | Where | Cost |
|---|---|---|
| Screens (web folder) | Netlify | Free plan is fine for demos |
| Back end (api folder): API, email assistant, imports | Render, Starter plan | about US$7/month; the free plan sleeps after 15 minutes idle, which stops the email assistant and makes the first click take about a minute |
| Database and files | Supabase (as now) | unchanged |

Your keys go into Render and Netlify's settings pages. They are never put in GitHub.

## 1. Database (once)

In Supabase → SQL Editor, run `supabase/migrations/20261103000002_mail_token_store.sql`
(keeps Outlook signed in on the hosted server, encrypted).

## 2. Back end on Render

1. Sign up at render.com with GitHub and allow it to see the `onpoint-crm` repository.
2. **New → Blueprint**, pick `patrbrown/onpoint-crm`. Render reads `render.yaml`.
3. Fill in the values it asks for, copying them from your `.env`:
   `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` (blank is fine if you
   don't have one), `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` and `TYPESAFE_API_KEY` (if you use them),
   `MS_TENANT_ID`, `MS_CLIENT_ID`.
   For `CORS_ORIGINS` and `APP_URL` type `https://example.com` for now; you'll change them in step 4.
4. **Apply**. When it says Live, open `https://<your-service>.onrender.com/health`: it should show `{"ok":true}`.
   Copy that address (without `/health`).

Do **not** add `DEV_USER_ID` on Render. The server refuses to start if it's set, because it would let anyone in
without signing in.

## 3. Screens on Netlify

1. Sign up at netlify.com with GitHub. **Add new site → Import an existing project → GitHub → onpoint-crm**.
   The build settings come from `netlify.toml`, so leave them as they are.
2. Before deploying, add three environment variables:
   - `NEXT_PUBLIC_API_URL`: the Render address from step 2
   - `NEXT_PUBLIC_SUPABASE_URL`: your `SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`: your `SUPABASE_ANON_KEY` (the publishable key)
3. **Deploy**. Then in **Site configuration → Change site name**, pick something like `onpoint-crm` so the address
   is `https://onpoint-crm.netlify.app`.

## 4. Connect the pieces

1. Render → your service → **Environment**: set `CORS_ORIGINS` and `APP_URL` to your Netlify address
   (e.g. `https://onpoint-crm.netlify.app`, no slash at the end). Save; Render restarts it.
2. Supabase → **Authentication → URL Configuration**: set **Site URL** to the Netlify address, and add
   `https://onpoint-crm.netlify.app/welcome` and `https://onpoint-crm.netlify.app/login` to **Redirect URLs**.

## 5. Try it

Open the Netlify address and sign in with your usual email and password. Then:

- **Email inbox → Connect Outlook** once more (the sign-in on your PC isn't copied over). From then on it stays
  connected through restarts and updates.
- Settings → Website: "Check the connection" should still say Connected.

When the hosted version works, stop the copy on your PC (`docker compose down`) or set
`EMAIL_WORKER_ENABLED=false` in your PC's `.env`, so only one copy checks your Outlook.

## Updates

Every push to GitHub updates both automatically (Render and Netlify each rebuild in a few minutes).
New database files in `supabase/migrations/` still need running once in the SQL Editor.
