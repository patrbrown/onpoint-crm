"use client";

import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { AiStatus, Route, Settings } from "@/lib/types";
import { useToast } from "../ui";

const PROVIDERS: [Route["provider"], string][] = [
  ["anthropic", "Claude"], ["openrouter", "OpenRouter"], ["openai_compatible", "Local or private model"],
];
const TASK_HELP: Record<string, string> = {
  default: "Used for anything without its own choice below.",
  email_triage: "Deciding whether an email is a job req, resume, feedback or something else. Not used when Jev sorts your email.",
  email_extraction: "Pulling job details, candidate details and feedback out of emails. The heaviest job by volume.",
  resume_parsing: "Resumes you upload one at a time or in bulk.",
};

type Draft = { provider: Route["provider"] | ""; model: string; base_url: string; fallback: boolean };
type TestResult = { ok: boolean; seconds?: number; error?: string } | "running";

function toDraft(r?: Route | null): Draft {
  return { provider: r?.provider ?? "", model: r?.model ?? "", base_url: r?.base_url ?? "", fallback: !!r?.fallback };
}

export function ModelSettings({ settings, status, onSaved }: { settings: Settings; status: AiStatus; onSaved: (s: Settings) => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const tasks = Object.keys(status.tasks);
  const initial = () => Object.fromEntries(tasks.map((k) => [k, k === "default"
    ? toDraft(settings.model_routes?.default ?? { provider: settings.llm_provider as Route["provider"], model: settings.llm_model, base_url: settings.llm_base_url })
    : toDraft(settings.model_routes?.[k])]));
  const [d, setD] = useState<Record<string, Draft>>(initial);
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => setD(initial()), [settings]);   // eslint-disable-line react-hooks/exhaustive-deps
  const ro = !status.can_edit;
  const set = (k: string, patch: Partial<Draft>) => setD({ ...d, [k]: { ...d[k], ...patch } });
  const keyMissing = (p: string) => (p === "anthropic" && !status.keys.anthropic) || (p === "openrouter" && !status.keys.openrouter);

  async function test(k: string) {
    const r = d[k].provider ? d[k] : d.default;
    setTests({ ...tests, [k]: "running" });
    try {
      const out = await api<any>(t(tenant.id, "/ai/test-model"), { method: "POST",
        json: { provider: r.provider, model: r.model, base_url: r.base_url || null } });
      setTests((x) => ({ ...x, [k]: out }));
    } catch (e: any) { setTests((x) => ({ ...x, [k]: { ok: false, error: e.message } })); }
  }

  async function save() {
    for (const k of tasks) if (d[k].provider && !d[k].model.trim()) { toast(`Choose a model name for “${status.tasks[k]}”`, "error"); return; }
    if (!d.default.provider) { toast("Choose a default model", "error"); return; }
    const routes: Record<string, Route | null> = {};
    for (const k of tasks) routes[k] = d[k].provider
      ? { provider: d[k].provider as Route["provider"], model: d[k].model.trim(), base_url: d[k].provider === "openai_compatible" ? (d[k].base_url.trim() || null) : null,
          fallback: d[k].provider !== "anthropic" && d[k].fallback }
      : null;
    setBusy(true);
    try {
      const s = await api<Settings>(t(tenant.id, "/settings"), { method: "PATCH", json: {
        model_routes: routes, llm_provider: routes.default!.provider, llm_model: routes.default!.model, llm_base_url: routes.default!.base_url } });
      toast("AI models saved");
      onSaved(s);
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }

  return (
    <div className="panel">
      <div className="panel-head"><h2>AI models</h2>
        <span className="key-chips">
          <KeyChip ok={status.keys.anthropic} label="Claude" envName="ANTHROPIC_API_KEY" />
          <KeyChip ok={status.keys.openrouter} label="OpenRouter" envName="OPENROUTER_API_KEY" />
        </span>
      </div>
      <p className="muted" style={{ maxWidth: "75ch" }}>Choose which model does each job. Open-source models through OpenRouter, or one running
        on your own hardware, cost far less than Claude. Turn on <em>fall back to Claude</em> so that if a cheaper model fails or
        gives an answer the CRM can’t read, Claude handles that email instead.</p>
      {ro && <p className="warn">Only workspace owners and admins can change these.</p>}

      <div className="route-list">
        {tasks.map((k) => {
          const r = d[k];
          const res = tests[k];
          return (
            <section key={k} className="route">
              <div className="route-head">
                <h3>{status.tasks[k]}</h3>
                <p className="muted">{TASK_HELP[k]}</p>
              </div>
              <div className="route-fields">
                <label className="field"><span className="field-label">Provider</span>
                  <select disabled={ro} value={r.provider} onChange={(e) => set(k, { provider: e.target.value as Draft["provider"],
                      model: e.target.value ? (status.suggestions[e.target.value]?.[0] ?? "") : "" })}>
                    {k !== "default" && <option value="">Same as default</option>}
                    {PROVIDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select></label>
                {r.provider && <label className="field"><span className="field-label">Model</span>
                  <input disabled={ro} list={`models-${r.provider}`} value={r.model} onChange={(e) => set(k, { model: e.target.value })} /></label>}
                {r.provider === "openai_compatible" && <label className="field wide"><span className="field-label">Model server address</span>
                  <input disabled={ro} value={r.base_url} placeholder={status.local_base_url} onChange={(e) => set(k, { base_url: e.target.value })} /></label>}
                {r.provider && r.provider !== "anthropic" && (
                  <label className="check field"><input type="checkbox" disabled={ro} checked={r.fallback}
                    onChange={(e) => set(k, { fallback: e.target.checked })} /> Fall back to Claude if it fails</label>
                )}
              </div>
              <div className="route-test">
                <button className="btn small" type="button" onClick={() => test(k)} disabled={res === "running"}>
                  {res === "running" ? "Testing…" : "Test"}</button>
                {res && res !== "running" && (res.ok
                  ? <span className="ok-text">Works ({res.seconds !== undefined && res.seconds < 1 ? "under a second" : `${res.seconds}s`})</span>
                  : <span className="err-text">{res.error ?? "Answered, but not in the format the CRM needs"}</span>)}
                {r.provider && keyMissing(r.provider) && <span className="err-text">No API key in .env for this provider</span>}
              </div>
            </section>
          );
        })}
      </div>
      {Object.entries(status.suggestions).map(([p, list]) => (
        <datalist key={p} id={`models-${p}`}>{list.map((m) => <option key={m} value={m} />)}</datalist>
      ))}
      {!ro && <div className="form-foot"><button className="btn primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save AI models"}</button></div>}
    </div>
  );
}

export function KeyChip({ ok, label, envName }: { ok: boolean; label: string; envName: string }) {
  return <span className={`key-chip ${ok ? "on" : "off"}`} title={ok ? `${envName} is set` : `Add ${envName} to .env, then run docker compose up -d`}>
    {label} key {ok ? "found" : "missing"}</span>;
}
