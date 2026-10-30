"use client";

import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useSession } from "@/lib/session";
import { Field } from "./ui";

export type Batch = {
  id: string; kind: string; status: "processing" | "completed" | "completed_with_errors" | "failed"; total: number;
  created_count: number; updated_count: number; error_count: number; created_at: string; finished_at: string | null;
  report?: { item?: string; file?: string; status: string; match?: string; warnings?: string[]; error?: string; reason?: string }[];
};

const MATCH: Record<string, string> = { exact: "Matched by file name", fuzzy: "Matched by name", resume_only: "Resume only", none: "No resume" };
export const STATUS: Record<Batch["status"], string> = {
  processing: "Importing", completed: "Finished", completed_with_errors: "Finished, some need attention", failed: "Stopped",
};
export const doneCount = (b: Batch) => b.created_count + b.updated_count +
  (b.report ?? []).filter((r) => r.status === "error").length;

/** Polls an import every 2 seconds until it finishes. */
export function useBatch(batchId: string | null, onFinished?: () => void) {
  const { tenant } = useSession();
  const [b, setB] = useState<Batch | null>(null);
  useEffect(() => {
    if (!batchId) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const x = await api<Batch>(t(tenant.id, `/candidates/imports/${batchId}`));
        if (stop) return;
        setB(x);
        if (x.status === "processing") timer = setTimeout(tick, 2000);
        else onFinished?.();
      } catch { if (!stop) timer = setTimeout(tick, 4000); }
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [batchId, tenant.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  return b;
}

export function BatchProgress({ b }: { b: Batch }) {
  const done = Math.min(doneCount(b), b.total);
  const pct = b.total ? Math.round((done / b.total) * 100) : 100;
  return (
    <div>
      <p><strong>{STATUS[b.status]}</strong>{b.status === "processing" ? `: ${done} of ${b.total} resumes` : ""}
        <span className="muted">, started {date(b.created_at)}</span></p>
      <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pct}%` }} className={b.status === "failed" ? "bad" : ""} /></div>
      <p className="muted" style={{ marginTop: 6 }}>{b.created_count} added, {b.updated_count} updated, {b.error_count} need attention
        {b.status === "processing" && ". You can close this; the import carries on and candidates appear as they're read."}</p>
    </div>
  );
}

export function BatchReport({ b }: { b: Batch }) {
  const rows = [...(b.report ?? [])].sort((x, y) => Number(y.status === "error") - Number(x.status === "error"));
  if (!rows.length) return null;
  return (
    <div className="table-wrap report" style={{ marginTop: 12, maxHeight: "50vh", overflow: "auto" }}>
      <table>
        <thead><tr><th>Item</th><th>Result</th><th>Notes</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.item ?? r.file}</td>
              <td>{r.status === "error" ? <span className="err-text">Error</span> : r.status === "skipped" ? "Skipped"
                : r.status === "created" ? "Added" : "Updated"}</td>
              <td className="muted">{[r.match && MATCH[r.match], r.reason, r.error, ...(r.warnings ?? [])].filter(Boolean).join("; ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function BulkImport({ onDone }: { onDone: () => void }) {
  const { tenant } = useSession();
  const [zip, setZip] = useState<File | null>(null);
  const [csv, setCsv] = useState<File | null>(null);
  const [parseUnmatched, setParseUnmatched] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const batch = useBatch(batchId, onDone);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!zip && !csv) { setError("Choose a ZIP of resumes, a CSV, or both."); return; }
    setUploading(true); setError(null);
    const body = new FormData();
    if (zip) body.append("zip_file", zip);
    if (csv) body.append("csv_file", csv);
    body.append("parse_unmatched", String(parseUnmatched));
    try {
      const r = await api<{ batch_id: string }>(t(tenant.id, "/candidates/bulk-import"), { method: "POST", body });
      setBatchId(r.batch_id);
      onDone();
    } catch (err: any) { setError(err.message); } finally { setUploading(false); }
  }

  if (batchId) return (
    <>
      {batch ? <><BatchProgress b={batch} /><BatchReport b={batch} /></> : <p className="muted">Starting…</p>}
      {batch && batch.status !== "processing" && (
        <div className="form-foot"><button className="btn" onClick={() => { setBatchId(null); setZip(null); setCsv(null); }}>Import another batch</button></div>
      )}
    </>
  );

  return (
    <form onSubmit={run}>
      {error && <div className="form-error" role="alert">{error}</div>}
      <p className="muted">
        Upload a ZIP of resumes, a CSV of candidates, or both. With both, each CSV row is matched to a resume by a
        <em> resume_file</em> column if you have one, otherwise by the candidate’s name in the file name. CSV values
        (name, email, phone…) take priority over what’s read from the resume.
      </p>
      <div className="form-grid">
        <Field label="ZIP of resumes" hint="PDF, Word or text files, up to 300 MB">
          <input type="file" accept=".zip" onChange={(e) => setZip(e.target.files?.[0] ?? null)} /></Field>
        <Field label="CSV of candidates" hint="Columns like First Name, Last Name, Email, Phone, LinkedIn">
          <input type="file" accept=".csv" onChange={(e) => setCsv(e.target.files?.[0] ?? null)} /></Field>
        <label className="check field wide">
          <input type="checkbox" checked={parseUnmatched} onChange={(e) => setParseUnmatched(e.target.checked)} />
          Also create candidates from resumes that have no CSV row
        </label>
      </div>
      <div className="form-foot">
        <button className="btn primary" disabled={uploading}>{uploading ? "Uploading…" : "Import candidates"}</button>
      </div>
    </form>
  );
}
