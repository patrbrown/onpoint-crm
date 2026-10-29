"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { JobForm } from "@/components/JobForm";
import { SavedViews } from "@/components/SavedViews";
import { Drawer, Empty, Select, Status, Tags } from "@/components/ui";
import { t } from "@/lib/api";
import { compensation, date, label, place } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Client, Job } from "@/lib/types";

type Filters = { q: string; status: string; client: string };

export default function JobsPage() {
  const { tenant } = useSession();
  const router = useRouter();
  const jobs = useData<Job[]>(t(tenant.id, "/jobs?limit=1000"));
  const clients = useData<Client[]>(t(tenant.id, "/clients?limit=1000"));
  const [f, setF] = useState<Filters>({ q: "", status: "open", client: "" });
  const [creating, setCreating] = useState(false);
  const clientName = useMemo(() => new Map((clients.data ?? []).map((c) => [c.id, c.name])), [clients.data]);

  const rows = (jobs.data ?? []).filter((j) => {
    const hay = `${j.title} ${j.reference_code ?? ""} ${clientName.get(j.client_id ?? "") ?? ""} ${j.systems.join(" ")} ${j.must_have_skills.join(" ")}`.toLowerCase();
    return (!f.q || hay.includes(f.q.toLowerCase())) && (!f.status || j.status === f.status) && (!f.client || j.client_id === f.client);
  });

  return (
    <>
      <div className="page-head">
        <div><h1>Jobs</h1><p>{rows.length} of {jobs.data?.length ?? 0} shown</p></div>
        <div className="actions"><button className="btn primary" onClick={() => setCreating(true)}>New job</button></div>
      </div>
      <div className="toolbar">
        <input className="search" type="search" placeholder="Search title, client, skill" value={f.q}
               onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Search jobs" />
        <Select value={f.status} onChange={(v) => setF({ ...f, status: v })} placeholder="Any status"
                options={[["open", "Open"], ["on_hold", "On hold"], ["draft", "Draft"], ["filled", "Filled"], ["closed", "Closed"]]} />
        <Select value={f.client} onChange={(v) => setF({ ...f, client: v })} placeholder="Any client"
                options={(clients.data ?? []).map((c) => [c.id, c.name])} />
      </div>
      <SavedViews entity="jobs" current={f} layout="table" onApply={(c) => setF(c)} />

      {jobs.error && <div className="form-error">{jobs.error}</div>}
      {jobs.data && jobs.data.length === 0 ? (
        <Empty title="No jobs yet">
          <p>Create one by hand now. Once Outlook is connected, job requisitions from email will show up in the inbox for you to approve.</p>
          <button className="btn primary" onClick={() => setCreating(true)}>New job</button>
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Job</th><th>Client</th><th>Type</th><th>Compensation</th><th>Systems</th><th>Status</th><th>Website</th><th>Created</th></tr></thead>
            <tbody>
              {rows.map((j) => (
                <tr key={j.id} className="clickable" onClick={() => router.push(`/jobs/${j.id}`)}>
                  <td><a href={`/jobs/${j.id}`} onClick={(e) => e.preventDefault()}>{j.title}</a>
                    <span className="sub">{[j.reference_code, place(j), label(j.work_model)].filter(Boolean).join(", ")}</span></td>
                  <td>{clientName.get(j.client_id ?? "") ?? <span className="muted">None</span>}</td>
                  <td>{label(j.employment_type)}</td>
                  <td className="num">{compensation(j)}</td>
                  <td><Tags items={j.systems} tone="system" /></td>
                  <td><Status value={j.status} text={label(j.status)} /></td>
                  <td>{j.is_published ? <Status value="published" text="Posted" /> : <span className="muted">Not posted</span>}</td>
                  <td className="muted">{date(j.created_at)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={8} className="muted">No jobs match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      <Drawer title="New job" open={creating} onClose={() => setCreating(false)}>
        <JobForm onCancel={() => setCreating(false)} onSaved={(j) => { setCreating(false); router.push(`/jobs/${j.id}`); }} />
      </Drawer>
    </>
  );
}
