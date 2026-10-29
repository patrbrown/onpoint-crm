"use client";

import { useState } from "react";
import { api, t } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Application } from "@/lib/types";
import { Field, Select, useToast } from "./ui";

const DEFAULT_CRITERIA = ["Technical skills", "Systems experience", "Communication", "Culture fit"];

export function FeedbackForm({ apps, onSaved, onCancel }: { apps: Application[]; onSaved: () => void; onCancel: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const [appId, setAppId] = useState(apps[0]?.id ?? "");
  const [fromName, setFromName] = useState("");
  const [overall, setOverall] = useState("");
  const [rec, setRec] = useState("");
  const [rows, setRows] = useState(DEFAULT_CRITERIA.map((c) => ({ criterion: c, rating: "" })));
  const [strengths, setStrengths] = useState("");
  const [concerns, setConcerns] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await api(t(tenant.id, "/interview-feedback"), {
        method: "POST", json: {
          application_id: appId, from_name: fromName || null, overall_rating: overall ? Number(overall) : null,
          recommendation: rec || null, strengths: strengths || null, concerns: concerns || null, notes: notes || null,
          scorecard: rows.filter((r) => r.criterion && r.rating).map((r) => ({ criterion: r.criterion, rating: Number(r.rating) })),
        },
      });
      toast("Feedback recorded");
      onSaved();
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }

  if (!apps.length) return <p className="muted">Add this candidate to a job first. Feedback is recorded against a job.</p>;
  const ratings: [string, string][] = [["1", "1 — Poor"], ["2", "2"], ["3", "3 — Meets"], ["4", "4"], ["5", "5 — Excellent"]];

  return (
    <form onSubmit={submit}>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="form-grid">
        <Field label="Job"><Select value={appId} onChange={setAppId} options={apps.map((a) => [a.id, a.job_title])} /></Field>
        <Field label="Feedback from" hint="Interviewer or hiring manager"><input value={fromName} onChange={(e) => setFromName(e.target.value)} /></Field>
        <Field label="Overall rating"><Select value={overall} onChange={setOverall} placeholder="Not rated" options={ratings} /></Field>
        <Field label="Recommendation"><Select value={rec} onChange={setRec} placeholder="Not given" options={[["strong_yes", "Strong yes"],
          ["yes", "Yes"], ["maybe", "Maybe"], ["no", "No"], ["strong_no", "Strong no"]]} /></Field>
      </div>
      <h3 style={{ margin: "16px 0 8px" }}>Scorecard</h3>
      {rows.map((r, i) => (
        <div key={i} className="form-grid" style={{ marginBottom: 6 }}>
          <input aria-label="Criterion" value={r.criterion}
                 onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, criterion: e.target.value } : x)))} />
          <Select value={r.rating} placeholder="Not rated" options={ratings}
                  onChange={(v) => setRows(rows.map((x, j) => (j === i ? { ...x, rating: v } : x)))} />
        </div>
      ))}
      <button type="button" className="link-btn" onClick={() => setRows([...rows, { criterion: "", rating: "" }])}>Add a criterion</button>
      <div className="form-grid" style={{ marginTop: 14 }}>
        <Field label="Strengths" wide><textarea value={strengths} onChange={(e) => setStrengths(e.target.value)} /></Field>
        <Field label="Concerns" wide><textarea value={concerns} onChange={(e) => setConcerns(e.target.value)} /></Field>
        <Field label="Other notes" wide><textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      <div className="form-foot">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Record feedback"}</button>
      </div>
    </form>
  );
}
