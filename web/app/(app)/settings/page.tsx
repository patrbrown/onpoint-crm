"use client";

import { useEffect, useState } from "react";
import { Select } from "@/components/ui";
import { StageEditor } from "@/components/StageEditor";
import { TeamSettings } from "@/components/settings/TeamSettings";
import { api, t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { AiStatus, Pipeline, Settings } from "@/lib/types";
import { InboxSettings } from "@/components/settings/InboxSettings";
import { JevSettings } from "@/components/settings/JevSettings";
import { ModelSettings } from "@/components/settings/ModelSettings";

const TABS = [["pipelines", "Pipelines"], ["users", "Users"], ["models", "AI models"], ["sorting", "Email sorting"], ["inbox", "Email inbox"]] as const;
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
      <div className="page-head"><div><h1>Settings</h1><p>Pipelines, users, AI models and how the email assistant works for this workspace.</p></div></div>
      <div className="tabs" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => go(k)}>{l}</button>)}
      </div>
      {tab === "pipelines" && <Pipelines />}
      {tab === "users" && <TeamSettings />}
      {tab !== "pipelines" && tab !== "users" && !ready && <p className="muted">{settings.error || status.error || "Loading…"}</p>}
      {ready && tab === "models" && <ModelSettings settings={settings.data!} status={status.data!} onSaved={settings.setData} />}
      {ready && tab === "sorting" && <JevSettings settings={settings.data!} status={status.data!} onSaved={settings.setData} />}
      {ready && tab === "inbox" && <InboxSettings settings={settings.data!} onSaved={settings.setData} />}
    </>
  );
}

function Pipelines() {
  const { tenant } = useSession();
  const pipes = useData<Pipeline[]>(t(tenant.id, "/pipelines"));
  const [sel, setSel] = useState("");
  const p = pipes.data?.find((x) => x.id === sel) ?? pipes.data?.[0];
  if (!p) return null;

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
      <p className="muted">Rename, recolour, reorder, add and remove stages. Changes apply to every job using “{p.name}”,
        except jobs whose stages were customized on the job page.</p>
      <StageEditor pipeline={p} onChanged={pipes.reload} />
    </div>
  );
}
