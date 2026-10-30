"use client";

import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { Batch, BatchProgress, BatchReport, STATUS, doneCount, useBatch } from "./BulkImport";

/** Slim banner on the Candidates page while an import is running. */
export function RunningImports({ onOpen, onChange, nudge }: { onOpen: (id: string) => void; onChange: () => void; nudge: number }) {
  const { tenant } = useSession();
  const [running, setRunning] = useState<Batch[]>([]);
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    let wasRunning = 0;
    const tick = async () => {
      try {
        const all = await api<Batch[]>(t(tenant.id, "/candidates/imports"));
        if (stop) return;
        const r = all.filter((b) => b.status === "processing");
        setRunning(r);
        if (r.length || wasRunning) onChange();          // refresh the candidate list as people arrive
        wasRunning = r.length;
        timer = setTimeout(tick, r.length ? 4000 : 30000);
      } catch { timer = setTimeout(tick, 30000); }
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [tenant.id, nudge]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!running.length) return null;
  return (
    <div className="import-banner">
      {running.map((b) => {
        const pct = b.total ? Math.round((Math.min(doneCount(b), b.total) / b.total) * 100) : 0;
        return (
          <button key={b.id} className="import-row" onClick={() => onOpen(b.id)}>
            <span>Importing resumes: {Math.min(doneCount(b), b.total)} of {b.total}</span>
            <span className="progress small"><span style={{ width: `${pct}%` }} /></span>
            <span className="link-btn">Details</span>
          </button>
        );
      })}
    </div>
  );
}

export function ImportHistory({ openId, onOpenId }: { openId: string | null; onOpenId: (id: string | null) => void }) {
  const { tenant } = useSession();
  const list = useData<Batch[]>(t(tenant.id, "/candidates/imports"));
  const batch = useBatch(openId, list.reload);
  if (openId) return (
    <>
      <button className="link-btn" style={{ marginBottom: 10 }} onClick={() => onOpenId(null)}>All imports</button>
      {batch ? <><BatchProgress b={batch} /><BatchReport b={batch} /></> : <p className="muted">Loading…</p>}
    </>
  );
  if (list.data && !list.data.length) return <p className="muted">No bulk imports yet.</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Started</th><th>Result</th><th className="num">Added</th><th className="num">Updated</th><th className="num">Need attention</th></tr></thead>
        <tbody>
          {(list.data ?? []).map((b) => (
            <tr key={b.id} className="clickable" onClick={() => onOpenId(b.id)}>
              <td>{date(b.created_at)}<span className="sub">{new Date(b.created_at).toLocaleTimeString("en-CA", { hour: "numeric", minute: "2-digit" })}{b.uploaded_by_name ? `, by ${b.uploaded_by_name}` : ""}</span></td>
              <td>{STATUS[b.status]}{b.status === "processing" && ` (${Math.min(doneCount(b), b.total)} of ${b.total})`}</td>
              <td className="num">{b.created_count}</td>
              <td className="num">{b.updated_count}</td>
              <td className="num">{b.error_count || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
