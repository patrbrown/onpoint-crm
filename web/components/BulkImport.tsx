"use client";

import { useState } from "react";
import { api, t } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Field } from "./ui";

type Report = { created: number; updated: number; errors: number; skipped: number; status: string;
  report: { item?: string; file?: string; status: string; match?: string; match_score?: number; warnings?: string[]; error?: string; reason?: string }[] };

const MATCH: Record<string, string> = { exact: "Matched by file name", fuzzy: "Matched by name", resume_only: "Resume only", none: "No resume" };

export function BulkImport({ onDone }: { onDone: () => void }) {
  const { tenant } = useSession();
  const [zip, setZip] = useState<File | null>(null);
  const [csv, setCsv] = useState<File | null>(null);
  const [parseUnmatched, setParseUnmatched] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Report | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    if (!zip && !csv) { setError("Choose a ZIP of resumes, a CSV, or both."); return; }
    setBusy(true); setError(null); setResult(null);
    const body = new FormData();
    if (zip) body.append("zip_file", zip);
    if (csv) body.append("csv_file", csv);
    body.append("parse_unmatched", String(parseUnmatched));
    try {
      setResult(await api<Report>(t(tenant.id, "/candidates/bulk-import"), { method: "POST", body }));
      onDone();
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }

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
        <button className="btn primary" disabled={busy}>{busy ? "Importing… this can take a few minutes" : "Import candidates"}</button>
      </div>

      {result && (
        <div style={{ marginTop: 16 }}>
          <h3>{result.created} added, {result.updated} updated, {result.errors} need attention</h3>
          <div className="table-wrap report" style={{ marginTop: 8 }}>
            <table>
              <thead><tr><th>Item</th><th>Result</th><th>Notes</th></tr></thead>
              <tbody>
                {result.report.map((r, i) => (
                  <tr key={i}>
                    <td>{r.item ?? r.file}</td>
                    <td>{r.status === "error" ? <span style={{ color: "var(--red)" }}>Error</span> : r.status === "skipped" ? "Skipped"
                      : r.status === "created" ? "Added" : "Updated"}</td>
                    <td className="muted">{[r.match && MATCH[r.match], r.reason, r.error, ...(r.warnings ?? [])].filter(Boolean).join("; ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </form>
  );
}
