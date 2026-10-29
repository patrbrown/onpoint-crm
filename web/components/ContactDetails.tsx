"use client";

import { useState } from "react";
import { api, t } from "@/lib/api";
import { label } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Candidate } from "@/lib/types";
import { useToast } from "./ui";

const FIELDS: { key: keyof Candidate; label: string; type?: string; placeholder?: string }[] = [
  { key: "email", label: "Email", type: "email" },
  { key: "phone", label: "Phone", type: "tel" },
  { key: "linkedin_url", label: "LinkedIn", type: "url", placeholder: "https://linkedin.com/in/…" },
  { key: "location", label: "Location", placeholder: "Vancouver, BC" },
  { key: "years_experience", label: "Experience (years)" },
  { key: "work_authorization", label: "Authorization", placeholder: "Canadian citizen, TN visa…" },
  { key: "desired_rate", label: "Desired rate" },
  { key: "availability", label: "Availability", placeholder: "2 weeks notice" },
];

/** The candidate's contact panel, editable in place. */
export function ContactDetails({ candidate, onSaved }: { candidate: Candidate; onSaved: (c: Candidate) => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [f, setF] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function start() {
    setF(Object.fromEntries(FIELDS.map(({ key }) => [key, candidate[key] == null ? "" : String(candidate[key])])));
    setError(null);
    setEditing(true);
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    const patch: Record<string, string | null> = {};
    for (const { key } of FIELDS) {
      const was = candidate[key] == null ? "" : String(candidate[key]);
      if (f[key].trim() !== was) patch[key] = f[key].trim() || null;
    }
    if (!Object.keys(patch).length) { setEditing(false); return; }
    setBusy(true);
    try {
      const saved = await api<Candidate>(t(tenant.id, `/candidates/${candidate.id}`), { method: "PATCH", json: patch });
      toast("Contact details saved");
      setEditing(false);
      onSaved(saved);
    } catch (err: any) {
      setError(err.status === 409 ? "Another candidate already has that email address." : err.message);
    } finally { setBusy(false); }
  }

  if (editing) return (
    <form className="panel" onSubmit={save} onKeyDown={(e) => e.key === "Escape" && setEditing(false)}>
      <h2 style={{ marginBottom: 10 }}>Contact</h2>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="facts-edit">
        {FIELDS.map(({ key, label: l, type, placeholder }, i) => (
          <label key={key}>
            <span>{l}</span>
            <input type={type ?? "text"} value={f[key]} placeholder={placeholder} autoFocus={i === 0}
                   inputMode={key === "years_experience" ? "decimal" : undefined}
                   onChange={(e) => setF({ ...f, [key]: e.target.value })} />
          </label>
        ))}
      </div>
      <div className="form-foot" style={{ marginTop: 12 }}>
        <button type="button" className="btn small" onClick={() => setEditing(false)}>Cancel</button>
        <button className="btn primary small" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
      </div>
    </form>
  );

  const c = candidate;
  return (
    <div className="panel">
      <div className="panel-head"><h2>Contact</h2><button className="link-btn" onClick={start}>Edit</button></div>
      <dl className="facts">
        <dt>Email</dt><dd>{c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : <span className="muted">None</span>}</dd>
        <dt>Phone</dt><dd>{c.phone ? <a href={`tel:${c.phone}`}>{c.phone}</a> : <span className="muted">None</span>}</dd>
        <dt>LinkedIn</dt><dd>{c.linkedin_url ? <a href={c.linkedin_url} target="_blank" rel="noreferrer">Profile</a> : <span className="muted">None</span>}</dd>
        <dt>Location</dt><dd>{c.location || <span className="muted">Unknown</span>}</dd>
        <dt>Experience</dt><dd>{c.years_experience ? `${Number(c.years_experience)} years` : <span className="muted">Unknown</span>}</dd>
        <dt>Authorization</dt><dd>{c.work_authorization || <span className="muted">Unknown</span>}</dd>
        <dt>Desired rate</dt><dd>{c.desired_rate || <span className="muted">Unknown</span>}</dd>
        <dt>Availability</dt><dd>{c.availability || <span className="muted">Unknown</span>}</dd>
        <dt>Source</dt><dd>{label(c.source)}</dd>
      </dl>
    </div>
  );
}
