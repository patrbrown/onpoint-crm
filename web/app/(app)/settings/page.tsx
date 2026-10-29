"use client";

import { useEffect, useState } from "react";
import { Field, Select, useToast } from "@/components/ui";
import { api, t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Pipeline, Settings, Stage } from "@/lib/types";

export default function SettingsPage() {
  return (
    <>
      <div className="page-head"><div><h1>Settings</h1><p>Pipelines and how the AI assistant works for this workspace.</p></div></div>
      <Pipelines />
      <AiSettings />
    </>
  );
}

function Pipelines() {
  const { tenant } = useSession();
  const toast = useToast();
  const pipes = useData<Pipeline[]>(t(tenant.id, "/pipelines"));
  const [sel, setSel] = useState("");
  const [stages, setStages] = useState<Stage[]>([]);
  const p = pipes.data?.find((x) => x.id === sel) ?? pipes.data?.[0];
  useEffect(() => { if (p) setStages([...p.stages].sort((a, b) => a.position - b.position)); }, [p]);
  if (!p) return null;

  async function saveStage(s: Stage, patch: Partial<Stage>) {
    try { await api(t(tenant.id, `/stages/${s.id}`), { method: "PATCH", json: patch }); }
    catch (e: any) { toast(e.message, "error"); pipes.reload(); }
  }
  async function move(i: number, d: -1 | 1) {
    const next = [...stages];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setStages(next);
    try {
      await api(t(tenant.id, `/pipelines/${p!.id}/stage-order`), { method: "PUT", json: { stage_ids: next.map((s) => s.id) } });
    } catch (e: any) { toast(e.message, "error"); pipes.reload(); }
  }
  async function addStage() {
    const name = prompt("Stage name");
    if (!name) return;
    try {
      await api(t(tenant.id, "/stages"), { method: "POST", json: { pipeline_id: p!.id, name, position: stages.length + 1 } });
      pipes.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function removeStage(s: Stage) {
    if (!confirm(`Delete the “${s.name}” stage? Candidates in it will show in the first stage until you move them.`)) return;
    try {
      await api(t(tenant.id, `/stages/${s.id}`), { method: "DELETE" });
      const rest = stages.filter((x) => x.id !== s.id);
      await api(t(tenant.id, `/pipelines/${p!.id}/stage-order`), { method: "PUT", json: { stage_ids: rest.map((x) => x.id) } });
      pipes.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function newPipeline() {
    const name = prompt("Name the new pipeline (it starts as a copy of the one shown)");
    if (!name) return;
    const np = await api<{ id: string }>(t(tenant.id, `/pipelines?copy_from=${p!.id}`), { method: "POST", json: { name } });
    await pipes.reload();
    setSel(np.id);
  }

  return (
    <div className="panel" style={{ marginBottom: 16 }}>
      <div className="panel-head">
        <h2>Pipeline stages</h2>
        <div className="actions">
          {(pipes.data?.length ?? 0) > 1 && <div style={{ width: 200 }}>
            <Select value={p.id} onChange={setSel} options={pipes.data!.map((x) => [x.id, x.name + (x.is_default ? " (default)" : "")])} /></div>}
          <button className="btn small" onClick={newPipeline}>New pipeline</button>
        </div>
      </div>
      <p className="muted">Rename, recolour and reorder stages. Changes apply to every job using “{p.name}”.</p>
      {stages.map((s, i) => (
        <div className="stage-row" key={s.id}>
          <div className="order-btns">
            <button aria-label={`Move ${s.name} up`} onClick={() => move(i, -1)} disabled={i === 0}>▲</button>
            <button aria-label={`Move ${s.name} down`} onClick={() => move(i, 1)} disabled={i === stages.length - 1}>▼</button>
          </div>
          <input type="color" aria-label={`${s.name} colour`} defaultValue={s.color} onBlur={(e) => saveStage(s, { color: e.target.value })} />
          <input aria-label="Stage name" defaultValue={s.name} onBlur={(e) => e.target.value !== s.name && saveStage(s, { name: e.target.value })} />
          <Select value={s.stage_type} onChange={(v) => { setStages(stages.map((x) => x.id === s.id ? { ...x, stage_type: v } : x)); saveStage(s, { stage_type: v }); }}
                  options={[["active", "In progress"], ["placed", "Counts as placed"], ["rejected", "Counts as rejected"], ["withdrawn", "Counts as withdrawn"]]} />
          <button className="icon-btn" aria-label={`Delete ${s.name}`} onClick={() => removeStage(s)}>×</button>
        </div>
      ))}
      <button className="link-btn" style={{ marginTop: 10 }} onClick={addStage}>Add a stage</button>
    </div>
  );
}

function AiSettings() {
  const { tenant } = useSession();
  const toast = useToast();
  const s = useData<Settings>(t(tenant.id, "/settings"));
  if (!s.data) return null;
  const v = s.data;
  async function save(patch: Partial<Settings>) {
    try { s.setData(await api<Settings>(t(tenant.id, "/settings"), { method: "PATCH", json: patch })); toast("Settings saved"); }
    catch (e: any) { toast(e.message, "error"); }
  }
  return (
    <div className="panel">
      <h2 style={{ marginBottom: 12 }}>AI assistant</h2>
      <div className="form-grid">
        <Field label="Email inbox handling" hint="Start with review. Switch to automatic once the suggestions are reliably right.">
          <Select value={v.inbox_mode} onChange={(m) => save({ inbox_mode: m as Settings["inbox_mode"] })}
                  options={[["review", "I review every item"], ["auto", "Save confident items automatically"]]} />
        </Field>
        <Field label="Confidence needed to save automatically" hint="Only used in automatic mode. 0.90 means 90%.">
          <input type="number" min={0.5} max={1} step={0.01} defaultValue={Number(v.auto_approve_threshold)}
                 onBlur={(e) => save({ auto_approve_threshold: e.target.value })} disabled={v.inbox_mode !== "auto"} />
        </Field>
        <Field label="Check email every (minutes)">
          <input type="number" min={5} max={1440} defaultValue={v.email_scan_minutes} onBlur={(e) => save({ email_scan_minutes: Number(e.target.value) })} />
        </Field>
        <label className="check field">
          <input type="checkbox" checked={v.ai_scoring_enabled} onChange={(e) => save({ ai_scoring_enabled: e.target.checked })} />
          Score candidates against jobs with AI
        </label>
        <Field label="AI model provider">
          <Select value={v.llm_provider} onChange={(p) => save({ llm_provider: p })}
                  options={[["anthropic", "Claude (Anthropic API)"], ["openai_compatible", "Local or private model"]]} />
        </Field>
        <Field label="Model name"><input defaultValue={v.llm_model} onBlur={(e) => e.target.value !== v.llm_model && save({ llm_model: e.target.value })} /></Field>
        {v.llm_provider === "openai_compatible" && (
          <Field label="Model server address" hint="e.g. http://host.docker.internal:11434/v1 for Ollama" wide>
            <input defaultValue={v.llm_base_url ?? ""} onBlur={(e) => save({ llm_base_url: e.target.value || null })} />
          </Field>
        )}
      </div>
    </div>
  );
}
