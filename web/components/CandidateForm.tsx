"use client";

import { useState } from "react";
import { api, t } from "@/lib/api";
import { splitList } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Candidate } from "@/lib/types";
import { clean, Field, Select, useToast } from "./ui";

const KEYS = ["first_name", "last_name", "email", "phone", "linkedin_url", "location", "current_title", "current_company",
  "years_experience", "work_authorization", "desired_rate", "availability", "summary", "status"] as const;
const LISTS = ["skills", "systems", "certifications"] as const;

export function CandidateForm({ candidate, onSaved, onCancel }: {
  candidate?: Candidate; onSaved: (c: Candidate) => void; onCancel: () => void;
}) {
  const { tenant } = useSession();
  const toast = useToast();
  const init: Record<string, string> = { status: "active" };
  for (const k of KEYS) if (candidate?.[k] != null) init[k] = String(candidate[k]);
  for (const k of LISTS) init[k] = candidate?.[k]?.join(", ") ?? "";
  const [f, setF] = useState(init);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const on = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const payload: Record<string, any> = clean(Object.fromEntries(KEYS.map((k) => [k, f[k] ?? ""])));
    for (const k of LISTS) payload[k] = splitList(f[k] ?? "");
    if (candidate) for (const k of KEYS) if (!f[k] && candidate[k] != null && k !== "first_name") payload[k] = null;
    try {
      const saved = await api<Candidate>(t(tenant.id, candidate ? `/candidates/${candidate.id}` : "/candidates"),
        { method: candidate ? "PATCH" : "POST", json: payload });
      toast(candidate ? "Candidate saved" : "Candidate added");
      onSaved(saved);
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit}>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="form-grid">
        <Field label="First name"><input required value={f.first_name ?? ""} onChange={on("first_name")} /></Field>
        <Field label="Last name"><input value={f.last_name ?? ""} onChange={on("last_name")} /></Field>
        <Field label="Email"><input type="email" value={f.email ?? ""} onChange={on("email")} /></Field>
        <Field label="Phone"><input type="tel" value={f.phone ?? ""} onChange={on("phone")} /></Field>
        <Field label="LinkedIn profile" wide><input type="url" value={f.linkedin_url ?? ""} onChange={on("linkedin_url")} /></Field>
        <Field label="Current title"><input value={f.current_title ?? ""} onChange={on("current_title")} /></Field>
        <Field label="Current company"><input value={f.current_company ?? ""} onChange={on("current_company")} /></Field>
        <Field label="Location"><input value={f.location ?? ""} onChange={on("location")} /></Field>
        <Field label="Years of experience"><input inputMode="decimal" value={f.years_experience ?? ""} onChange={on("years_experience")} /></Field>
        <Field label="Skills" hint="Separate with commas" wide><input value={f.skills} onChange={on("skills")} /></Field>
        <Field label="Systems and modules"><input value={f.systems} onChange={on("systems")} /></Field>
        <Field label="Certifications"><input value={f.certifications} onChange={on("certifications")} /></Field>
        <Field label="Work authorization"><input value={f.work_authorization ?? ""} onChange={on("work_authorization")} /></Field>
        <Field label="Desired rate or salary"><input value={f.desired_rate ?? ""} onChange={on("desired_rate")} /></Field>
        <Field label="Availability"><input value={f.availability ?? ""} onChange={on("availability")} placeholder="2 weeks notice" /></Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => setF({ ...f, status: v })} options={[["active", "Active"], ["placed", "Placed"],
            ["do_not_contact", "Do not contact"], ["archived", "Archived"]]} />
        </Field>
        <Field label="Summary" wide><textarea value={f.summary ?? ""} onChange={on("summary")} /></Field>
      </div>
      <div className="form-foot">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={busy}>{busy ? "Saving…" : candidate ? "Save candidate" : "Add candidate"}</button>
      </div>
    </form>
  );
}
