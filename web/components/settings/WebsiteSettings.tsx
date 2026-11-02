"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Website } from "@/lib/types";
import { useToast } from "../ui";
import { GeneralApplication } from "./GeneralApplication";

function Copy({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="btn small" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1800); } catch { /* clipboard blocked */ }
    }}>{done ? "Copied" : label}</button>
  );
}

/** Settings → Website: putting posted jobs and an apply form on the agency's careers page. */
export function WebsiteSettings() {
  const { tenant } = useSession();
  const toast = useToast();
  const w = useData<Website>(t(tenant.id, "/website"));
  const [consent, setConsent] = useState("");
  const [check, setCheck] = useState<{ ok: boolean; text: string } | null>(null);
  const admin = ["owner", "admin", "platform_admin"].includes(tenant.role);
  useEffect(() => { if (w.data?.consent) setConsent(w.data.consent.body); }, [w.data?.consent]);
  if (!w.data) return <p className="muted">{w.error || "Loading…"}</p>;
  const d = w.data;
  const url = d.careers_url ?? "https://YOUR-PROJECT.supabase.co/functions/v1/careers";
  const snippet = `<div id="onpoint-jobs"></div>\n<script src="${url}/embed.js" data-site="${d.site}" async></script>`;
  const replitPrompt =
`On the /careers page, show our job listings using this embed. Add an empty container where the listings should appear (below the page intro):

<div id="onpoint-jobs"></div>

and load this script on the site (once):

<script src="${url}/embed.js" data-site="${d.site}" async></script>

If the site is React, don't put the <script> tag inside JSX: add it to index.html just before </body>, or append it with a useEffect that creates a script element with that src and the attribute data-site="${d.site}". Keep the <div id="onpoint-jobs"></div> in the Careers page component. The script draws the job list, each job's details and the application form by itself, so don't add, restyle or replace anything inside that div.`;

  async function test() {
    setCheck(null);
    try {
      const r = await fetch(`${url}/jobs?site=${encodeURIComponent(d.site)}`);
      const b = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(r.status === 401 ? "Supabase refused the request: turn off “Verify JWT” for the careers function (step 2)."
        : r.status === 404 ? "The careers function isn’t deployed yet (step 2)." : (b.error || `Error ${r.status}`));
      const n = (b.jobs ?? []).length;
      setCheck({ ok: true, text: `Connected. ${n} job${n === 1 ? " is" : "s are"} showing on your careers page.` });
    } catch (e: any) {
      setCheck({ ok: false, text: e.message === "Failed to fetch" ? "Couldn’t reach the careers function. Check it’s deployed (step 2)." : e.message });
    }
  }
  async function saveConsent() {
    try {
      await api(t(tenant.id, "/website/consent"), { method: "PUT", json: { body: consent } });
      toast("Consent wording saved"); w.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-head"><h2>Careers page</h2><button className="btn small" onClick={test} disabled={!d.careers_url}>Check the connection</button></div>
        {check && <div className={`setup-status ${check.ok ? "ok" : "bad"}`} role="status">{check.text}</div>}
        <p className="muted">Jobs you post from a job’s page appear on your website with the job title, location and work type only,
          never the client’s name. People apply with their resume, name, email, phone and (optionally) LinkedIn, and show up
          under <Link href="/applicants">New applicants</Link>.</p>
        <h3 style={{ marginTop: 14 }}>Set up (once)</h3>
        <ol className="steps">
          <li><strong>Database:</strong> run <code>supabase/migrations/20261102000001_careers_portal.sql</code> in the Supabase SQL Editor
            (if you haven’t already).</li>
          <li><strong>Careers function:</strong> in Supabase, open <em>Edge Functions → Deploy a new function → Via Editor</em>. Name it
            <code> careers</code>. Replace the sample code with everything in <code>supabase/functions/careers/index.ts</code> from your
            onpoint-crm folder (open it in Notepad, Ctrl+A, Ctrl+C), then <em>Deploy</em>. Then open the function’s settings, turn
            <strong> off “Verify JWT”</strong> (the page is public; the function checks every application itself) and save.</li>
          <li><strong>Website:</strong> paste this where the jobs should appear on onpointpersonnel.com/careers:
            <div className="snippet">{snippet}</div>
            <div className="actions" style={{ justifyContent: "flex-start" }}>
              <Copy text={snippet} label="Copy code" /><Copy text={replitPrompt} label="Copy instructions for Replit Agent" />
            </div>
            <p className="field-hint">If Replit built your site, the easiest way is to paste the Replit Agent instructions into the Agent chat.</p>
          </li>
          <li><strong>Check:</strong> click <em>Check the connection</em> above, then post a job and open your careers page.</li>
        </ol>
        {!d.careers_url && <p className="err-text">SUPABASE_URL isn’t set in .env, so the code above has a placeholder address.</p>}
      </div>

      <div className="panel">
        <h2 style={{ marginBottom: 8 }}>On your website now</h2>
        {d.posted.length === 0 ? <p className="muted">No jobs posted. Open a job and click “Post to website”.</p> : (
          <ul className="plain-list">
            {d.posted.map((p) => (
              <li key={p.id}><Link href={`/jobs/${p.id}`}>{p.title}</Link>
                {p.mentions_client && <span className="warn-inline"> The description mentions “{p.client_name}”. Add a “Description for the website” in Edit to hide it.</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      {d.general && <GeneralApplication general={d.general} onSaved={w.reload} />}

      <div className="panel">
        <h2 style={{ marginBottom: 8 }}>Consent wording</h2>
        <p className="muted">Shown above the apply button; applicants must tick that they agree. Each applicant’s record keeps the exact version
          they agreed to. Adding a contact email for privacy requests is a good idea (e.g. “…by contacting privacy@onpointpersonnel.com”).
          {d.consent && ` Current version ${d.consent.version}, saved ${date(d.consent.created_at)}.`}</p>
        <textarea rows={7} value={consent} onChange={(e) => setConsent(e.target.value)} aria-label="Consent wording" disabled={!admin} style={{ width: "100%" }} />
        {admin && <div className="form-foot"><button className="btn primary" onClick={saveConsent}
                    disabled={!consent.trim() || consent.trim() === d.consent?.body.trim()}>Save wording</button></div>}
      </div>
    </>
  );
}
