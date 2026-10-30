"use client";

import { useState } from "react";
import { api, t } from "@/lib/api";
import { splitList } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Client, Contact, Job, Pipeline } from "@/lib/types";
import { clean, Field, Select, useToast } from "./ui";

const EMPTY = {
  title: "", client_id: "", hiring_contact_id: "", pipeline_id: "", reference_code: "", description: "",
  public_description: "", location: "", work_model: "", employment_type: "", salary_min: "", salary_max: "",
  rate_min: "", rate_max: "", rate_unit: "", currency: "CAD", must_have_skills: "", nice_to_have_skills: "",
  systems: "", certifications: "", openings: "1", fee_percent: "", status: "open", priority: "normal",
  hide_client_name: true,
};

function fromJob(j: Job): typeof EMPTY {
  const s = (v: any) => (v === null || v === undefined ? "" : String(v));
  return {
    title: j.title, client_id: s(j.client_id), hiring_contact_id: s(j.hiring_contact_id), pipeline_id: s(j.pipeline_id),
    reference_code: s(j.reference_code), description: s(j.description),
    public_description: s((j as any).public_description), location: s(j.location), work_model: s(j.work_model),
    employment_type: s(j.employment_type), salary_min: s(j.salary_min), salary_max: s(j.salary_max),
    rate_min: s(j.rate_min), rate_max: s(j.rate_max), rate_unit: s(j.rate_unit), currency: s(j.currency) || "CAD",
    must_have_skills: j.must_have_skills.join(", "), nice_to_have_skills: j.nice_to_have_skills.join(", "),
    systems: j.systems.join(", "), certifications: j.certifications.join(", "), openings: s(j.openings),
    fee_percent: s(j.fee_percent), status: j.status, priority: j.priority, hide_client_name: j.hide_client_name,
  };
}

export function JobForm({ job, onSaved, onCancel }: { job?: Job; onSaved: (j: Job) => void; onCancel: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const [f, setF] = useState(job ? fromJob(job) : EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const clients = useData<Client[]>(t(tenant.id, "/clients?limit=1000"));
  const contacts = useData<Contact[]>(f.client_id ? t(tenant.id, `/contacts?client_id=${f.client_id}`) : null);
  const pipelines = useData<Pipeline[]>(t(tenant.id, "/pipelines"));
  // A job whose stages were customized on its page uses its own pipeline, which isn't in the shared list.
  const customStages = !!job?.pipeline_id && !!pipelines.data && !pipelines.data.some((p) => p.id === job.pipeline_id);
  const set = (k: keyof typeof EMPTY) => (v: any) => setF((x) => ({ ...x, [k]: v }));
  const on = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(k)(e.target.value);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const payload: Record<string, any> = {
      ...clean(f),
      must_have_skills: splitList(f.must_have_skills), nice_to_have_skills: splitList(f.nice_to_have_skills),
      systems: splitList(f.systems), certifications: splitList(f.certifications),
      openings: Number(f.openings || 1), hide_client_name: f.hide_client_name,
    };
    if (job) for (const k of ["client_id", "hiring_contact_id", "pipeline_id", "work_model", "employment_type", "rate_unit"] as const)
      if (f[k] === "") payload[k] = null;   // let edits clear a selection
    if (customStages) delete payload.pipeline_id;   // stages customized on the job page: leave them alone
    try {
      const saved = await api<Job>(t(tenant.id, job ? `/jobs/${job.id}` : "/jobs"),
        { method: job ? "PATCH" : "POST", json: payload });
      toast(job ? "Job saved" : "Job created");
      onSaved(saved);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const contractish = f.employment_type === "contract" || f.employment_type === "contract_to_hire" || f.employment_type === "temporary";

  return (
    <form onSubmit={submit}>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="form-grid">
        <Field label="Job title" wide><input required value={f.title} onChange={on("title")} /></Field>
        <Field label="Client">
          <Select value={f.client_id} onChange={(v) => setF((x) => ({ ...x, client_id: v, hiring_contact_id: "" }))}
                  placeholder="No client yet" options={(clients.data ?? []).map((c) => [c.id, c.name])} />
        </Field>
        <Field label="Hiring contact">
          <Select value={f.hiring_contact_id} onChange={set("hiring_contact_id")}
                  placeholder={f.client_id ? "Choose a contact" : "Pick a client first"}
                  options={(contacts.data ?? []).map((c) => [c.id, [c.first_name, c.last_name].filter(Boolean).join(" ")])} />
        </Field>
        <Field label="Client req number"><input value={f.reference_code} onChange={on("reference_code")} /></Field>
        <Field label="Status">
          <Select value={f.status} onChange={set("status")} options={[["draft", "Draft"], ["open", "Open"],
            ["on_hold", "On hold"], ["filled", "Filled"], ["closed", "Closed"], ["cancelled", "Cancelled"]]} />
        </Field>
        <Field label="Employment type">
          <Select value={f.employment_type} onChange={set("employment_type")} placeholder="Not set" options={[
            ["permanent", "Permanent"], ["contract", "Contract"], ["contract_to_hire", "Contract to hire"], ["temporary", "Temporary"]]} />
        </Field>
        <Field label="Work model">
          <Select value={f.work_model} onChange={set("work_model")} placeholder="Not set"
                  options={[["onsite", "On-site"], ["hybrid", "Hybrid"], ["remote", "Remote"]]} />
        </Field>
        <Field label="Location" wide><input value={f.location} onChange={on("location")} placeholder="Vancouver, BC" /></Field>
        {contractish ? <>
          <Field label="Rate from"><input inputMode="decimal" value={f.rate_min} onChange={on("rate_min")} /></Field>
          <Field label="Rate to"><input inputMode="decimal" value={f.rate_max} onChange={on("rate_max")} /></Field>
          <Field label="Rate per">
            <Select value={f.rate_unit} onChange={set("rate_unit")} placeholder="Not set"
                    options={[["hour", "Hour"], ["day", "Day"], ["month", "Month"]]} />
          </Field>
        </> : <>
          <Field label="Salary from"><input inputMode="decimal" value={f.salary_min} onChange={on("salary_min")} /></Field>
          <Field label="Salary to"><input inputMode="decimal" value={f.salary_max} onChange={on("salary_max")} /></Field>
        </>}
        <Field label="Currency">
          <Select value={f.currency} onChange={set("currency")} options={[["CAD", "CAD"], ["USD", "USD"], ["EUR", "EUR"], ["GBP", "GBP"]]} />
        </Field>
        <Field label="Must-have skills" hint="Separate with commas" wide>
          <input value={f.must_have_skills} onChange={on("must_have_skills")} /></Field>
        <Field label="Nice-to-have skills" wide><input value={f.nice_to_have_skills} onChange={on("nice_to_have_skills")} /></Field>
        <Field label="Systems and modules" hint="e.g. Epic Ambulatory, Cerner PowerChart">
          <input value={f.systems} onChange={on("systems")} /></Field>
        <Field label="Certifications"><input value={f.certifications} onChange={on("certifications")} /></Field>
        <Field label="Openings"><input type="number" min={1} value={f.openings} onChange={on("openings")} /></Field>
        <Field label="Fee %"><input inputMode="decimal" value={f.fee_percent} onChange={on("fee_percent")} /></Field>
        <Field label="Priority">
          <Select value={f.priority} onChange={set("priority")}
                  options={[["low", "Low"], ["normal", "Normal"], ["high", "High"], ["urgent", "Urgent"]]} />
        </Field>
        <Field label="Pipeline" hint={job ? "To add or remove stages for this job only, use Edit stages above the job’s board" : undefined}>
          {customStages ? <p className="muted" style={{ margin: "6px 0" }}>Customized for this job (Edit stages on the job page)</p>
            : <Select value={f.pipeline_id} onChange={set("pipeline_id")} placeholder="Default pipeline"
                      options={(pipelines.data ?? []).map((p) => [p.id, p.name])} />}
        </Field>
        <Field label="Job description" wide>
          <textarea rows={8} value={f.description} onChange={on("description")} /></Field>
        <Field label="Description for the website" hint="Leave empty to use the job description" wide>
          <textarea rows={5} value={f.public_description} onChange={on("public_description")} /></Field>
        <label className="check field wide">
          <input type="checkbox" checked={f.hide_client_name} onChange={(e) => set("hide_client_name")(e.target.checked)} />
          Hide the client’s name on the website
        </label>
      </div>
      <div className="form-foot">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={busy}>{busy ? "Saving…" : job ? "Save job" : "Create job"}</button>
      </div>
    </form>
  );
}
