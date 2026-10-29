"use client";

import { useEffect, useState } from "react";
import { Field, Select, useToast } from "@/components/ui";
import { api, t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { AiStatus, Pipeline, Settings, Stage } from "@/lib/types";
import { InboxSettings } from "@/components/settings/InboxSettings";
import { JevSettings } from "@/components/settings/JevSettings";
import { ModelSettings } from "@/components/settings/ModelSettings";

const TABS = [["pipelines", "Pipelines"], ["models", "AI models"], ["sorting", "Email sorting"], ["inbox", "Email inbox"]] as const;
type Tab = (typeof TABS)[number][0];

export default function SettingsPage() {
  const { tenant } = useSession();
  const [tab, setTab] = useState<Tab>("pipelines");
  const settings = useData<Settings>(t(tenant.id, "/settings"));
  const status = useData<AiStatus>(t(tenant.id, "/ai/status"));
  useEffect(() => {
    const h = window.location.hash.slice(1) as Tab;
    if (TABS.some(([k]) => k === h)) setTab(h);
  }, []);
  const go = (k: Tab) => { setTab(k); history.replaceState(null, "", `#${k}`); };
  const ready = settings.data && status.data;
  return (
    <>
      <div className="page-head"><div><h1>Settings</h1><p>Pipelines, AI models and how the email assistant works for this workspace.</p></div></div>
      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => go(k)}>{l}</button>)}
      </div>
      {tab === "pipelines" && <Pipelines />}
      {tab !== "pipelines" && !ready && <p className="muted">{settings.error || status.error || "Loading…"}</p>}
      {ready && tab === "models" && <ModelSettings settings={settings.data!} status={status.data!} onSaved={settings.setData} />}
      {ready && tab === "sorting" && <JevSettings settings={settings.data!} status={status.data!} onSaved={settings.setData} />}
      {ready && tab === "inbox" && <InboxSettings settings={settings.data!} onSaved={settings.setData} />}
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
