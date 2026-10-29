"use client";

import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { AiStatus, JevConfig, Settings } from "@/lib/types";
import { TYPE_LABEL } from "../InboxReview";
import { Field, useToast } from "../ui";
import { KeyChip } from "./ModelSettings";

const ORDER = ["job_requisition", "resume", "interview_feedback", "client_correspondence", "candidate_reply", "other"];
const pct = (x: number) => `${Math.round(x * 100)}%`;
const secs = (s?: number) => (s === undefined ? "" : s < 1 ? "under a second" : `${s}s`);

type TestOut = { ok: boolean; error?: string; classification?: string; confidence?: number; probabilities?: Record<string, number>;
  would_review_anyway?: boolean; seconds?: number; model?: string };

export function JevSettings({ settings, status, onSaved }: { settings: Settings; status: AiStatus; onSaved: (s: Settings) => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const defaults = status.jev_defaults;
  const build = () => ({
    provider: settings.triage_provider ?? "llm",
    model: settings.jev_model || "jev-latest",
    floor: Number(settings.review_below_confidence ?? 0.6),
    instructions: settings.jev_config?.instructions ?? defaults.instructions,
    categories: { ...defaults.categories, ...(settings.jev_config?.categories ?? {}) },
    use_corrections: settings.jev_config?.use_corrections ?? defaults.use_corrections,
    body_chars: settings.jev_config?.body_chars ?? defaults.body_chars,
  });
  const [f, setF] = useState(build);
  useEffect(() => setF(build()), [settings]);   // eslint-disable-line react-hooks/exhaustive-deps
  const models = useData<{ ok: boolean; models: string[]; error?: string }>(status.keys.typesafe ? t(tenant.id, "/jev/models") : null);
  const recent = useData<any[]>(t(tenant.id, "/jev/recent"));
  const [busy, setBusy] = useState(false);
  const [sample, setSample] = useState({ subject: "", sender: "", body: "" });
  const [out, setOut] = useState<TestOut | "running" | null>(null);
  const ro = !status.can_edit;

  // Only send what differs from the defaults, so improved defaults reach you automatically.
  function config(): JevConfig {
    const cats = Object.fromEntries(Object.entries(f.categories).filter(([k, v]) => v.trim() && v.trim() !== defaults.categories[k]));
    const c: JevConfig = {};
    if (f.instructions.trim() && f.instructions.trim() !== defaults.instructions) c.instructions = f.instructions.trim();
    if (Object.keys(cats).length) c.categories = cats;
    if (f.use_corrections !== defaults.use_corrections) c.use_corrections = f.use_corrections;
    if (Number(f.body_chars) !== defaults.body_chars) c.body_chars = Number(f.body_chars);
    return c;
  }

  async function save() {
    if (f.provider === "jev" && !status.keys.typesafe) { toast("Add TYPESAFE_API_KEY to .env before switching to Jev", "error"); return; }
    setBusy(true);
    try {
      const s = await api<Settings>(t(tenant.id, "/settings"), { method: "PATCH", json: {
        triage_provider: f.provider, jev_model: f.model.trim() || "jev-latest", review_below_confidence: f.floor, jev_config: config() } });
      toast("Email sorting saved");
      onSaved(s);
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }

  async function runTest() {
    if (!sample.body.trim()) { toast("Paste an email body to test", "error"); return; }
    setOut("running");
    try {
      setOut(await api<TestOut>(t(tenant.id, "/jev/test"), { method: "POST", json: { ...sample, model: f.model, config: config() } }));
    } catch (e: any) { setOut({ ok: false, error: e.message }); }
  }

  return (
    <div className="panel">
      <div className="panel-head"><h2>Email sorting</h2><KeyChip ok={status.keys.typesafe} label="Jev" envName="TYPESAFE_API_KEY" /></div>
      <p className="muted" style={{ maxWidth: "75ch" }}>Every new email is first sorted into a type. <strong>Jev</strong> (TypeSafe AI) is built for
        decisions like this: it returns a calibrated probability for every type instead of a written answer, costs a tiny
        fraction of a cent per email, and the probabilities tell the CRM when it’s unsure. Details are still read out by the
        model chosen under <em>AI models</em>.</p>
      {ro && <p className="warn">Only workspace owners and admins can change these.</p>}

      <fieldset className="radio-row" disabled={ro}>
        <legend className="field-label">Sort emails with</legend>
        <label className="check"><input type="radio" checked={f.provider === "llm"} onChange={() => setF({ ...f, provider: "llm" })} />
          The AI model (“Sorting emails” under AI models)</label>
        <label className="check"><input type="radio" checked={f.provider === "jev"} onChange={() => setF({ ...f, provider: "jev" })} />
          Jev</label>
      </fieldset>
      {!status.keys.typesafe && <p className="field-hint">To use Jev, add <code>TYPESAFE_API_KEY=…</code> to your .env file (key from the
        TypeSafe console), then run <code>docker compose up -d</code>. If Jev is ever unreachable, the AI model sorts that email instead.</p>}

      <div className="form-grid" style={{ marginTop: 14 }}>
        <Field label="Jev model" hint="jev-latest follows TypeSafe’s newest release; pick a version to keep behaviour fixed">
          <input disabled={ro} list="jev-models" value={f.model} onChange={(e) => setF({ ...f, model: e.target.value })} />
        </Field>
        <Field label={`Still review if Jev is under ${pct(f.floor)} sure an email isn’t recruiting-related`}
               hint="Catches near-misses: the email goes to your review list instead of being skipped. Higher = fewer misses, more to review.">
          <input disabled={ro} type="range" min={0.3} max={0.95} step={0.05} value={f.floor} onChange={(e) => setF({ ...f, floor: Number(e.target.value) })} />
        </Field>
      </div>
      <datalist id="jev-models">{["jev-latest", ...(models.data?.models ?? [])].map((m) => <option key={m} value={m} />)}</datalist>
      {models.data && !models.data.ok && <p className="err-text">Couldn’t list Jev models: {models.data.error}</p>}

      <h3 style={{ margin: "18px 0 4px" }}>What each type means</h3>
      <p className="muted" style={{ marginBottom: 8 }}>Jev reads these literally. Describe your own inbox: who sends reqs, which alerts to ignore.</p>
      <div className="cat-grid">
        {ORDER.map((k) => (
          <label key={k} className="field">
            <span className="field-label">{TYPE_LABEL[k]}
              {f.categories[k] !== defaults.categories[k] && !ro &&
                <button type="button" className="link-btn" style={{ marginLeft: 8, fontWeight: 400 }}
                        onClick={() => setF({ ...f, categories: { ...f.categories, [k]: defaults.categories[k] } })}>Reset</button>}</span>
            <textarea disabled={ro} rows={3} value={f.categories[k]} onChange={(e) => setF({ ...f, categories: { ...f.categories, [k]: e.target.value } })} />
          </label>
        ))}
      </div>
      <details style={{ marginTop: 12 }}>
        <summary className="link-btn">Advanced</summary>
        <div className="form-grid" style={{ marginTop: 10 }}>
          <Field label="Question asked of every email" wide>
            <textarea disabled={ro} rows={3} value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} /></Field>
          <label className="check field"><input type="checkbox" disabled={ro} checked={f.use_corrections}
            onChange={(e) => setF({ ...f, use_corrections: e.target.checked })} /> Include my past corrections from the inbox</label>
          <Field label="Characters of each email body to read"><input disabled={ro} type="number" min={500} max={30000} step={500}
            value={f.body_chars} onChange={(e) => setF({ ...f, body_chars: Number(e.target.value) })} /></Field>
        </div>
      </details>
      {!ro && <div className="form-foot"><button className="btn primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save email sorting"}</button></div>}

      <h3 style={{ margin: "18px 0 8px" }}>Try it on an email</h3>
      {!status.keys.typesafe ? <p className="muted">Available once the Jev key is in .env.</p> : (
        <div className="jev-test">
          <div className="form-grid">
            <Field label="From"><input value={sample.sender} onChange={(e) => setSample({ ...sample, sender: e.target.value })} placeholder="Dana Leung <dana@client.ca>" /></Field>
            <Field label="Subject"><input value={sample.subject} onChange={(e) => setSample({ ...sample, subject: e.target.value })} /></Field>
            <Field label="Body" wide><textarea rows={5} value={sample.body} onChange={(e) => setSample({ ...sample, body: e.target.value })} /></Field>
          </div>
          <div className="actions" style={{ marginTop: 8 }}>
            <button className="btn" disabled={out === "running"} onClick={runTest}>{out === "running" ? "Asking Jev…" : "Test with these settings"}</button>
            <span className="muted">Uses the settings above, even before you save.</span>
          </div>
          {out && out !== "running" && (out.ok ? (
            <div className="probs">
              <p><strong>{TYPE_LABEL[out.classification!]}</strong>, {pct(out.confidence!)} sure ({secs(out.seconds)}, {out.model})
                {out.would_review_anyway && <span className="warn-inline"> Not sure enough to skip: it would go to your review list.</span>}</p>
              {ORDER.map((k) => <Bar key={k} label={TYPE_LABEL[k]} value={out.probabilities?.[k] ?? 0} top={k === out.classification} />)}
            </div>
          ) : <p className="err-text">{out.error}</p>)}
        </div>
      )}

      <h3 style={{ margin: "22px 0 8px" }}>Recent decisions</h3>
      {!recent.data?.length ? <p className="muted">Emails sorted from now on are listed here with the reasoning behind them.</p> : (
        <div className="table-wrap"><table>
          <thead><tr><th>Email</th><th>Sorted as</th><th>By</th><th>Runner-up</th></tr></thead>
          <tbody>{recent.data.map((e) => {
            const p: Record<string, number> = e.triage?.probabilities ?? {};
            const second = Object.entries(p).filter(([k]) => k !== e.classification).sort((a, b) => b[1] - a[1])[0];
            return (
              <tr key={e.id}>
                <td>{e.subject}<span className="sub">{e.from_address}, {date(e.received_at)}</span></td>
                <td>{TYPE_LABEL[e.classification] ?? e.classification}{e.confidence != null && ` (${pct(Number(e.confidence))})`}
                  {e.triage?.unsure && <span className="sub">Jev leaned “{TYPE_LABEL[e.triage.unsure.was]}” but wasn’t sure, so it was queued</span>}</td>
                <td>{e.triage?.provider === "jev" ? "Jev" : "AI model"}{e.triage?.jev_error && <span className="sub err-text">Jev unavailable</span>}</td>
                <td className="muted">{second ? `${TYPE_LABEL[second[0]]} ${pct(second[1])}` : ""}</td>
              </tr>
            );
          })}</tbody>
        </table></div>
      )}
    </div>
  );
}

function Bar({ label, value, top }: { label: string; value: number; top: boolean }) {
  return (
    <div className="bar-row">
      <span>{label}</span>
      <span className="bar"><span style={{ width: `${Math.max(1, value * 100)}%` }} className={top ? "top" : ""} /></span>
      <span className="num">{pct(value)}</span>
    </div>
  );
}
