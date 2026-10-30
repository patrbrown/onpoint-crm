"use client";

import { useEffect, useState } from "react";
import { api, ApiError, t } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Pipeline, Stage } from "@/lib/types";
import { Select, useToast } from "./ui";

const TYPES: [string, string][] = [["active", "In progress"], ["placed", "Counts as placed"],
  ["rejected", "Counts as rejected"], ["withdrawn", "Counts as withdrawn"]];

/** Add, rename, recolour, reorder and remove the stages of one pipeline. `counts` (candidates per stage) is optional;
 *  removing a stage that has candidates asks where to move them. */
export function StageEditor({ pipeline, counts, onChanged, ensureOwn }: {
  pipeline: Pipeline; counts?: Record<string, number>; onChanged: () => void;
  /** Set for a job still on shared stages: called before the first change to give the job its own copy. */
  ensureOwn?: () => Promise<Pipeline>;
}) {
  const { tenant } = useSession();
  const toast = useToast();
  const [stages, setStages] = useState<Stage[]>([]);
  const [adding, setAdding] = useState("");
  const [removing, setRemoving] = useState<{ stage: Stage; count: number | null } | null>(null);
  const [moveTo, setMoveTo] = useState("");
  useEffect(() => { setStages([...pipeline.stages].sort((a, b) => a.position - b.position)); }, [pipeline]);

  /** Where a change should go. For a job on shared stages, this first makes the job's own copy and translates
   *  stage ids to the copied stages (the copy keeps the same positions). */
  async function target(): Promise<{ pid: string; id: (stageId: string) => string }> {
    if (!ensureOwn) return { pid: pipeline.id, id: (x) => x };
    const own = await ensureOwn();
    const pos = new Map(pipeline.stages.map((st) => [st.id, st.position]));
    const byPos = new Map(own.stages.map((st) => [st.position, st.id]));
    return { pid: own.id, id: (x) => byPos.get(pos.get(x) ?? -1) ?? x };
  }

  async function saveStage(s: Stage, patch: Partial<Stage>) {
    try {
      const to = await target();
      await api(t(tenant.id, `/stages/${to.id(s.id)}`), { method: "PATCH", json: patch });
      onChanged();
    }
    catch (e: any) { toast(e.message, "error"); onChanged(); }
  }
  async function move(i: number, d: -1 | 1) {
    const next = [...stages];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setStages(next);
    try {
      const to = await target();
      await api(t(tenant.id, `/pipelines/${to.pid}/stage-order`), { method: "PUT", json: { stage_ids: next.map((s) => to.id(s.id)) } });
      onChanged();
    } catch (e: any) { toast(e.message, "error"); onChanged(); }
  }
  async function add(e: React.FormEvent) {
    e.preventDefault();
    const name = adding.trim();
    if (!name) return;
    // New stages go after the last in-progress stage, before Placed / Rejected / Withdrawn.
    const lastActive = stages.reduce((n, s, i) => (s.stage_type === "active" ? i : n), stages.length - 1);
    try {
      const to = await target();
      const created = await api<Stage>(t(tenant.id, "/stages"),
        { method: "POST", json: { pipeline_id: to.pid, name, position: stages.length + 1 } });
      const order = [...stages.slice(0, lastActive + 1).map((s) => to.id(s.id)), created.id,
                     ...stages.slice(lastActive + 1).map((s) => to.id(s.id))];
      await api(t(tenant.id, `/pipelines/${to.pid}/stage-order`), { method: "PUT", json: { stage_ids: order } });
      setAdding("");
      onChanged();
    } catch (err: any) { toast(err.message, "error"); }
  }
  async function remove(s: Stage, moveTarget?: string) {
    try {
      const to = await target();
      const q = moveTarget ? `?move_to=${to.id(moveTarget)}` : "";
      await api(t(tenant.id, `/stages/${to.id(s.id)}${q}`), { method: "DELETE" });
      setRemoving(null); setMoveTo("");
      toast(`Removed “${s.name}”`);
      onChanged();
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409) { setRemoving({ stage: s, count: null }); return; }
      toast(e.message, "error");
    }
  }
  function askRemove(s: Stage) {
    const n = counts?.[s.id] ?? 0;
    if (n > 0) { setRemoving({ stage: s, count: n }); setMoveTo(""); return; }
    if (confirm(`Remove the “${s.name}” stage?`)) remove(s);
  }

  return (
    <div>
      {stages.map((s, i) => (
        <div key={s.id}>
          <div className="stage-row">
            <div className="order-btns">
              <button aria-label={`Move ${s.name} up`} onClick={() => move(i, -1)} disabled={i === 0}>▲</button>
              <button aria-label={`Move ${s.name} down`} onClick={() => move(i, 1)} disabled={i === stages.length - 1}>▼</button>
            </div>
            <input type="color" aria-label={`${s.name} colour`} defaultValue={s.color} onBlur={(e) => e.target.value !== s.color && saveStage(s, { color: e.target.value })} />
            <input aria-label="Stage name" defaultValue={s.name} onBlur={(e) => e.target.value.trim() && e.target.value !== s.name && saveStage(s, { name: e.target.value.trim() })} />
            <Select value={s.stage_type} onChange={(v) => { setStages(stages.map((x) => x.id === s.id ? { ...x, stage_type: v } : x)); saveStage(s, { stage_type: v }); }}
                    options={TYPES} />
            <span className="stage-tail">
              {counts && <span className="muted stage-count" title="Candidates in this stage">{counts[s.id] ?? 0}</span>}
              <button className="icon-btn" aria-label={`Remove ${s.name}`} onClick={() => askRemove(s)} disabled={stages.length <= 1}>×</button>
            </span>
          </div>
          {removing?.stage.id === s.id && (
            <div className="stage-remove" role="group" aria-label={`Remove ${s.name}`}>
              <span>{removing.count ? `${removing.count} candidate${removing.count === 1 ? " is" : "s are"}` : "Candidates are"} in “{s.name}”. Move them to</span>
              <div style={{ width: 200 }}>
                <Select value={moveTo} onChange={setMoveTo} placeholder="Choose a stage"
                        options={stages.filter((x) => x.id !== s.id).map((x) => [x.id, x.name])} /></div>
              <button className="btn small danger" disabled={!moveTo} onClick={() => remove(s, moveTo)}>Move and remove</button>
              <button className="link-btn" onClick={() => setRemoving(null)}>Cancel</button>
            </div>
          )}
        </div>
      ))}
      <form className="stage-add" onSubmit={add}>
        <input value={adding} onChange={(e) => setAdding(e.target.value)} placeholder="New stage, e.g. Client tech test" aria-label="New stage name" />
        <button className="btn small" disabled={!adding.trim()}>Add stage</button>
      </form>
    </div>
  );
}
