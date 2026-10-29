"use client";

import { api, t } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Settings } from "@/lib/types";
import { Field, Select, useToast } from "../ui";

/** How the email inbox behaves: review vs automatic, how often to check, AI scoring. */
export function InboxSettings({ settings, onSaved }: { settings: Settings; onSaved: (s: Settings) => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const v = settings;
  async function save(patch: Partial<Settings>) {
    try { onSaved(await api<Settings>(t(tenant.id, "/settings"), { method: "PATCH", json: patch })); toast("Settings saved"); }
    catch (e: any) { toast(e.message, "error"); }
  }
  return (
    <div className="panel">
      <h2 style={{ marginBottom: 12 }}>Email inbox</h2>
      <div className="form-grid">
        <Field label="Email inbox handling" hint="Start with review. Switch to automatic once the suggestions are reliably right.">
          <Select value={v.inbox_mode} onChange={(m) => save({ inbox_mode: m as Settings["inbox_mode"] })}
                  options={[["review", "I review every item"], ["auto", "Save confident items automatically"]]} />
        </Field>
        <Field label="Confidence needed to save automatically" hint="Only used in automatic mode. 0.90 means 90%.">
          <input type="number" min={0.5} max={1} step={0.01} defaultValue={Number(v.auto_approve_threshold)} key={v.auto_approve_threshold}
                 onBlur={(e) => save({ auto_approve_threshold: e.target.value })} disabled={v.inbox_mode !== "auto"} />
        </Field>
        <Field label="Check email every (minutes)">
          <input type="number" min={5} max={1440} defaultValue={v.email_scan_minutes} key={v.email_scan_minutes}
                 onBlur={(e) => Number(e.target.value) !== v.email_scan_minutes && save({ email_scan_minutes: Number(e.target.value) })} />
        </Field>
        <label className="check field">
          <input type="checkbox" checked={v.ai_scoring_enabled} onChange={(e) => save({ ai_scoring_enabled: e.target.checked })} />
          Score candidates against jobs with AI
        </label>
      </div>
    </div>
  );
}
