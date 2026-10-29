"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { JdImport } from "@/components/JdImport";
import { JobForm } from "@/components/JobForm";
import { Markdown } from "@/components/Markdown";
import { PipelineBoard } from "@/components/PipelineBoard";
import { ResumeUpload } from "@/components/ResumeUpload";
import { Drawer, Status, Tags, useToast } from "@/components/ui";
import { api, t } from "@/lib/api";
import { compensation, date, fullName, label, place } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Application, Candidate, Client, Contact, Job, Pipeline } from "@/lib/types";

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const { tenant } = useSession();
  const router = useRouter();
  const toast = useToast();
  const job = useData<Job>(t(tenant.id, `/jobs/${id}`));
  const apps = useData<Application[]>(t(tenant.id, `/applications?job_id=${id}`));
  const pipelines = useData<Pipeline[]>(t(tenant.id, "/pipelines"));
  const client = useData<Client>(job.data?.client_id ? t(tenant.id, `/clients/${job.data.client_id}`) : null);
  const contact = useData<Contact>(job.data?.hiring_contact_id ? t(tenant.id, `/contacts/${job.data.hiring_contact_id}`) : null);
  const [editing, setEditing] = useState(false);
  const [importing, setImporting] = useState(false);
  const [adding, setAdding] = useState(false);

  const pipeline = useMemo(() => {
    const ps = pipelines.data ?? [];
    return ps.find((p) => p.id === job.data?.pipeline_id) ?? ps.find((p) => p.is_default) ?? ps[0];
  }, [pipelines.data, job.data]);

  if (job.error) return <div className="form-error">{job.error}</div>;
  if (!job.data) return <p className="muted">Loading…</p>;
  const j = job.data;

  async function togglePublish() {
    try {
      await api(t(tenant.id, `/jobs/${id}/publish?published=${!j.is_published}`), { method: "POST" });
      toast(j.is_published ? "Removed from the website" : "Posted to the website");
      job.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function remove() {
    if (!confirm(`Delete “${j.title}”? Its pipeline and interview records are deleted too.`)) return;
    await api(t(tenant.id, `/jobs/${id}`), { method: "DELETE" });
    toast("Job deleted");
    router.push("/jobs");
  }

  return (
    <>
      <Link href="/jobs" className="crumb">Jobs</Link>
      <div className="page-head">
        <div>
          <h1>{j.title}</h1>
          <p>{[client.data?.name, place(j), label(j.work_model), label(j.employment_type), compensation(j)].filter(Boolean).join(", ")}</p>
        </div>
        <div className="actions">
          <Status value={j.status} text={label(j.status)} />
          <button className="btn" onClick={togglePublish} disabled={!j.is_published && j.status !== "open"}
                  title={j.status !== "open" ? "Only open jobs can be posted" : undefined}>
            {j.is_published ? "Remove from website" : "Post to website"}
          </button>
          <button className="btn" onClick={() => setEditing(true)}>Edit</button>
          <button className="btn primary" onClick={() => setAdding(true)}>Add candidates</button>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16, padding: 12 }}>
        {pipeline && apps.data ? (
          <PipelineBoard stages={pipeline.stages} apps={apps.data} onMoved={(a) => apps.setData(a)} />
        ) : <p className="muted">Loading pipeline…</p>}
        {apps.data?.length === 0 && <p className="muted" style={{ margin: "8px 4px 0" }}>
          No candidates on this job yet. Use “Add candidates” to link existing candidates or upload resumes.</p>}
      </div>

      <div className="two-col">
        <div className="panel">
          <div className="panel-head"><h2>Job description</h2>
            <button className="btn small" onClick={() => setImporting(true)}>{j.description ? "Import from a file" : "Add from a JD file"}</button></div>
          {j.description ? <Markdown text={j.description} /> : <p className="muted">No description yet. Add it from the JD attached to the client’s email, or upload the file.</p>}
        </div>
        <div>
          <div className="panel">
            <h2 style={{ marginBottom: 10 }}>Details</h2>
            <dl className="facts">
              <dt>Client</dt><dd>{client.data ? <Link href={`/clients/${client.data.id}`}>{client.data.name}</Link> : "None"}</dd>
              <dt>Hiring contact</dt><dd>{contact.data ? <>{fullName(contact.data)}{contact.data.email && <><br /><a href={`mailto:${contact.data.email}`}>{contact.data.email}</a></>}</> : "None"}</dd>
              <dt>Req number</dt><dd>{j.reference_code || "None"}</dd>
              <dt>Openings</dt><dd>{j.openings}</dd>
              <dt>Fee</dt><dd>{j.fee_percent ? `${Number(j.fee_percent)}%` : "Not set"}</dd>
              <dt>Priority</dt><dd>{label(j.priority)}</dd>
              <dt>Website</dt><dd>{j.is_published ? `Posted ${date(j.published_at)}${j.hide_client_name ? ", client name hidden" : ""}` : "Not posted"}</dd>
              <dt>Source</dt><dd>{label(j.source)}</dd>
            </dl>
          </div>
          <div className="panel">
            <h3>Must-have</h3><p><Tags items={j.must_have_skills} /></p>
            {j.nice_to_have_skills.length > 0 && <><h3>Nice to have</h3><p><Tags items={j.nice_to_have_skills} /></p></>}
            {j.systems.length > 0 && <><h3>Systems and modules</h3><p><Tags items={j.systems} tone="system" /></p></>}
            {j.certifications.length > 0 && <><h3>Certifications</h3><p><Tags items={j.certifications} /></p></>}
          </div>
          <button className="btn danger small" style={{ marginTop: 14 }} onClick={remove}>Delete job</button>
        </div>
      </div>

      <Drawer title="Job description from a file" open={importing} onClose={() => setImporting(false)}>
        <JdImport jobId={j.id} current={j.description} onSaved={() => { setImporting(false); job.reload(); }} />
      </Drawer>
      <Drawer title="Edit job" open={editing} onClose={() => setEditing(false)}>
        <JobForm job={j} onCancel={() => setEditing(false)} onSaved={() => { setEditing(false); job.reload(); }} />
      </Drawer>
      <Drawer title={`Add candidates to ${j.title}`} open={adding} onClose={() => setAdding(false)}>
        <AddCandidates jobId={j.id} linked={new Set((apps.data ?? []).map((a) => a.candidate_id))} onChange={apps.reload} />
      </Drawer>
    </>
  );
}

function AddCandidates({ jobId, linked, onChange }: { jobId: string; linked: Set<string>; onChange: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const cands = useData<Candidate[]>(t(tenant.id, "/candidates?limit=1000"));
  const [q, setQ] = useState("");
  const matches = (cands.data ?? []).filter((c) => {
    const hay = `${fullName(c)} ${c.email ?? ""} ${c.current_title ?? ""} ${c.skills.join(" ")} ${c.systems.join(" ")}`.toLowerCase();
    return !q || hay.includes(q.toLowerCase());
  }).slice(0, 50);

  async function link(candidateId: string) {
    try {
      await api(t(tenant.id, "/applications"), { method: "POST", json: { candidate_id: candidateId, job_id: jobId } });
      toast("Added to the pipeline");
      onChange();
    } catch (e: any) { toast(e.message, "error"); }
  }

  return (
    <>
      <h3 style={{ marginBottom: 8 }}>Upload new resumes</h3>
      <ResumeUpload jobId={jobId} onDone={onChange} />
      <h3 style={{ margin: "20px 0 8px" }}>Or pick existing candidates</h3>
      <input type="search" placeholder="Search name, title, skill, system" value={q} onChange={(e) => setQ(e.target.value)}
             aria-label="Search candidates" />
      <div className="table-wrap" style={{ marginTop: 8 }}>
        <table><tbody>
          {matches.map((c) => (
            <tr key={c.id}>
              <td>{fullName(c)}<span className="sub">{[c.current_title, c.current_company].filter(Boolean).join(", ")}</span></td>
              <td className="num">{linked.has(c.id) ? <span className="muted">On this job</span>
                : <button className="btn small" onClick={() => link(c.id)}>Add</button>}</td>
            </tr>
          ))}
          {matches.length === 0 && <tr><td className="muted">No candidates match.</td></tr>}
        </tbody></table>
      </div>
    </>
  );
}
