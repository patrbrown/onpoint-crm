"use client";

import Link from "next/link";
import { useState } from "react";
import { api, t } from "@/lib/api";
import { fullName } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Application, Stage } from "@/lib/types";
import { useToast } from "./ui";

/** Kanban of applications by stage. Drag a card, or use its stage menu (keyboard friendly).
 *  In-progress stages get a column each; closed-out stages (placed, rejected, withdrawn) share the last column. */
export function PipelineBoard({ stages, apps, onMoved }: {
  stages: Stage[]; apps: Application[]; onMoved: (a: Application[]) => void;
}) {
  const { tenant } = useSession();
  const toast = useToast();
  const [over, setOver] = useState<string | null>(null);
  const sorted = [...stages].sort((a, b) => a.position - b.position);
  const active = sorted.filter((s) => s.stage_type === "active");
  const closed = sorted.filter((s) => s.stage_type !== "active");
  const first = sorted[0]?.id;
  const inStage = (s: Stage) => apps.filter((a) => a.stage_id === s.id || (!a.stage_id && s.id === first));

  async function move(appId: string, stageId: string) {
    const before = apps;
    const target = stages.find((s) => s.id === stageId);
    if (!target || apps.find((a) => a.id === appId)?.stage_id === stageId) return;
    onMoved(apps.map((a) => (a.id === appId ? { ...a, stage_id: stageId, stage_name: target.name } : a)));
    try {
      await api(t(tenant.id, `/applications/${appId}`), { method: "PATCH", json: { stage_id: stageId } });
      if (target.stage_type === "placed") toast("Marked as placed");
    } catch (e: any) {
      onMoved(before);
      toast(`Couldn’t move the candidate: ${e.message}`, "error");
    }
  }

  const drop = (s: Stage) => ({
    onDragOver: (e: React.DragEvent) => { e.preventDefault(); setOver(s.id); },
    onDragLeave: () => setOver(null),
    onDrop: (e: React.DragEvent) => { e.preventDefault(); setOver(null); move(e.dataTransfer.getData("text/plain"), s.id); },
  });

  const card = (a: Application) => (
    <article key={a.id} className="card" draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", a.id)}>
      <div className="card-name"><Link href={`/candidates/${a.candidate_id}`}>{fullName(a)}</Link></div>
      {a.current_title && <div className="card-sub">{a.current_title}</div>}
      <div className="card-foot">
        <select aria-label={`Move ${fullName(a)} to stage`} value={a.stage_id ?? first ?? ""} onChange={(e) => move(a.id, e.target.value)}>
          {sorted.map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
        </select>
        {a.match_score !== null && <span className="score" title="AI match score">{a.match_score}</span>}
      </div>
    </article>
  );

  return (
    <div className="board" style={{ gridTemplateColumns: `repeat(${active.length}, minmax(176px, 1fr)) minmax(176px, 0.9fr)` }}>
      {active.map((s) => {
        const items = inStage(s);
        return (
          <section key={s.id} className={`col${over === s.id ? " drop" : ""}`} style={{ ["--stage" as any]: s.color }}
                   aria-label={`${s.name}, ${items.length} candidates`} {...drop(s)}>
            <header className="col-head"><span className="col-name">{s.name}</span><span className="col-count">{items.length}</span></header>
            <div className="col-body">{items.map(card)}</div>
          </section>
        );
      })}
      {closed.length > 0 && (
        <div className="col-stack">
          {closed.map((s) => {
            const items = inStage(s);
            return (
              <section key={s.id} className={`col closed${over === s.id ? " drop" : ""}`} style={{ ["--stage" as any]: s.color }}
                       aria-label={`${s.name}, ${items.length} candidates`} {...drop(s)}>
                <header className="col-head"><span className="col-name">{s.name}</span><span className="col-count">{items.length}</span></header>
                {items.length > 0 && <div className="col-body">{items.map(card)}</div>}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
