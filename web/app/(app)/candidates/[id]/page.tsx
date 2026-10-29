"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CandidateForm } from "@/components/CandidateForm";
import { FeedbackForm } from "@/components/FeedbackForm";
import { ResumeUpload } from "@/components/ResumeUpload";
import { Drawer, Select, Status, Tags, useToast } from "@/components/ui";
import { api, apiBlobUrl, t } from "@/lib/api";
import { date, fullName, label } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Application, Candidate, Doc, Feedback, Job } from "@/lib/types";

export default function CandidatePage() {
  const { id } = useParams<{ id: string }>();
  const { tenant } = useSession();
  const router = useRouter();
  const toast = useToast();
  const cand = useData<Candidate>(t(tenant.id, `/candidates/${id}`));
  const docs = useData<Doc[]>(t(tenant.id, `/candidates/${id}/documents`));
  const apps = useData<Application[]>(t(tenant.id, `/applications?candidate_id=${id}`));
  const [tab, setTab] = useState<"resume" | "feedback" | "notes">("resume");
  const [drawer, setDrawer] = useState<"none" | "edit" | "job" | "feedback" | "resume">("none");
  const [fbVersion, setFbVersion] = useState(0);

  if (cand.error) return <div className="form-error">{cand.error}</div>;
  if (!cand.data) return <p className="muted">Loading…</p>;
  const c = cand.data;
  const primary = docs.data?.[0];

  async function openDoc(d: Doc) {
    try { window.open(await apiBlobUrl(t(tenant.id, `/documents/${d.id}/download`)), "_blank"); }
    catch (e: any) { toast(e.message, "error"); }
  }
  async function remove() {
    if (!confirm(`Delete ${fullName(c)}? Their resume, job links and feedback are deleted too.`)) return;
    await api(t(tenant.id, `/candidates/${id}`), { method: "DELETE" });
    toast("Candidate deleted");
    router.push("/candidates");
  }

  return (
    <>
      <Link href="/candidates" className="crumb">Candidates</Link>
      <div className="page-head">
        <div>
          <h1>{fullName(c)}</h1>
          <p>{[c.current_title, c.current_company, c.location].filter(Boolean).join(", ")}</p>
        </div>
        <div className="actions">
          <Status value={c.status} text={label(c.status)} />
          <button className="btn" onClick={() => setDrawer("edit")}>Edit</button>
          <button className="btn primary" onClick={() => setDrawer("job")}>Add to a job</button>
        </div>
      </div>

      <div className="two-col">
        <div>
          <div className="tabs" role="tablist">
            {(["resume", "feedback", "notes"] as const).map((k) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>
                {k === "resume" ? "Resume" : k === "feedback" ? "Interview feedback" : "Notes and activity"}
              </button>
            ))}
          </div>
          {tab === "resume" && (
            <div className="panel">
              <div className="panel-head">
                <h2>{primary ? primary.file_name : "No resume on file"}</h2>
                <div className="actions">
                  {primary && <button className="btn small" onClick={() => openDoc(primary)}>Open original</button>}
                  <button className="btn small" onClick={() => setDrawer("resume")}>Upload a resume</button>
                </div>
              </div>
              {primary?.extracted_text ? <div className="resume-text">{primary.extracted_text}</div>
                : <p className="muted">Upload a resume to see it here.</p>}
              {(docs.data?.length ?? 0) > 1 && (
                <p style={{ marginTop: 10 }}>Older files: {docs.data!.slice(1).map((d) => (
                  <button key={d.id} className="link-btn" style={{ marginRight: 10 }} onClick={() => openDoc(d)}>{d.file_name} ({date(d.created_at)})</button>
                ))}</p>
              )}
            </div>
          )}
          {tab === "feedback" && <FeedbackList apps={apps.data ?? []} version={fbVersion} onAdd={() => setDrawer("feedback")} />}
          {tab === "notes" && <Notes candidateId={c.id} />}
        </div>

        <div>
          <div className="panel">
            <h2 style={{ marginBottom: 10 }}>Contact</h2>
            <dl className="facts">
              <dt>Email</dt><dd>{c.email ? <a href={`mailto:${c.email}`}>{c.email}</a> : "None"}</dd>
              <dt>Phone</dt><dd>{c.phone ? <a href={`tel:${c.phone}`}>{c.phone}</a> : "None"}</dd>
              <dt>LinkedIn</dt><dd>{c.linkedin_url ? <a href={c.linkedin_url} target="_blank" rel="noreferrer">Profile</a> : "None"}</dd>
              <dt>Experience</dt><dd>{c.years_experience ? `${Number(c.years_experience)} years` : "Unknown"}</dd>
              <dt>Authorization</dt><dd>{c.work_authorization || "Unknown"}</dd>
              <dt>Desired rate</dt><dd>{c.desired_rate || "Unknown"}</dd>
              <dt>Availability</dt><dd>{c.availability || "Unknown"}</dd>
              <dt>Source</dt><dd>{label(c.source)}</dd>
            </dl>
          </div>
          <div className="panel">
            <h2 style={{ marginBottom: 10 }}>Jobs</h2>
            {apps.data?.length ? apps.data.map((a) => (
              <p key={a.id}><Link href={`/jobs/${a.job_id}`}>{a.job_title}</Link><br />
                <span className="muted">{a.stage_name ?? "No stage"}{a.match_score !== null ? `, match ${a.match_score}` : ""}</span></p>
            )) : <p className="muted">Not on any job yet.</p>}
          </div>
          <div className="panel">
            {c.summary && <><h3>Summary</h3><p className="prose">{c.summary}</p></>}
            {c.systems.length > 0 && <><h3>Systems and modules</h3><p><Tags items={c.systems} tone="system" /></p></>}
            {c.skills.length > 0 && <><h3>Skills</h3><p><Tags items={c.skills} /></p></>}
            {c.certifications.length > 0 && <><h3>Certifications</h3><p><Tags items={c.certifications} /></p></>}
          </div>
          <button className="btn danger small" style={{ marginTop: 14 }} onClick={remove}>Delete candidate</button>
        </div>
      </div>

      <Drawer title="Edit candidate" open={drawer === "edit"} onClose={() => setDrawer("none")}>
        <CandidateForm candidate={c} onCancel={() => setDrawer("none")} onSaved={() => { setDrawer("none"); cand.reload(); }} />
      </Drawer>
      <Drawer title={`Add ${fullName(c)} to a job`} open={drawer === "job"} onClose={() => setDrawer("none")}>
        <AddToJob candidateId={c.id} current={new Set((apps.data ?? []).map((a) => a.job_id))}
                  onDone={() => { setDrawer("none"); apps.reload(); }} />
      </Drawer>
      <Drawer title="Record interview feedback" open={drawer === "feedback"} onClose={() => setDrawer("none")}>
        <FeedbackForm apps={apps.data ?? []} onCancel={() => setDrawer("none")}
                      onSaved={() => { setDrawer("none"); setTab("feedback"); setFbVersion((v) => v + 1); }} />
      </Drawer>
      <Drawer title="Upload a resume" open={drawer === "resume"} onClose={() => setDrawer("none")}>
        <p className="muted">The new file becomes this candidate’s resume if its email matches theirs.</p>
        <ResumeUpload onDone={() => { setDrawer("none"); docs.reload(); cand.reload(); }} />
      </Drawer>
    </>
  );
}

function AddToJob({ candidateId, current, onDone }: { candidateId: string; current: Set<string>; onDone: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const jobs = useData<Job[]>(t(tenant.id, "/jobs?status=open&limit=1000"));
  const [jobId, setJobId] = useState("");
  const open = (jobs.data ?? []).filter((j) => !current.has(j.id));
  async function add() {
    try {
      await api(t(tenant.id, "/applications"), { method: "POST", json: { candidate_id: candidateId, job_id: jobId } });
      toast("Added to the job’s pipeline");
      onDone();
    } catch (e: any) { toast(e.message, "error"); }
  }
  if (jobs.data && !open.length) return <p className="muted">No other open jobs. Create a job first.</p>;
  return (
    <>
      <Select value={jobId} onChange={setJobId} placeholder="Choose an open job" options={open.map((j) => [j.id, j.title])} />
      <div className="form-foot"><button className="btn primary" disabled={!jobId} onClick={add}>Add to job</button></div>
    </>
  );
}

function FeedbackList({ apps, version, onAdd }: { apps: Application[]; version: number; onAdd: () => void }) {
  const { tenant } = useSession();
  // One request per job the candidate is on; fine at recruiting scale.
  const [all, setAll] = useState<(Feedback & { job: string })[] | null>(null);
  const key = apps.map((a) => a.id).join(",");
  useEffect(() => {
    let live = true;
    Promise.all(apps.map((a) => api<Feedback[]>(t(tenant.id, `/interview-feedback?application_id=${a.id}`))
      .then((fs) => fs.map((f) => ({ ...f, job: a.job_title })))))
      .then((x) => live && setAll(x.flat()));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, version, tenant.id]);
  return (
    <div className="panel">
      <div className="panel-head"><h2>Interview feedback</h2><button className="btn small" onClick={onAdd}>Record feedback</button></div>
      {!all ? <p className="muted">Loading…</p> : all.length === 0 ? <p className="muted">No feedback recorded yet.</p> : all.map((f) => (
        <div key={f.id} style={{ borderTop: "1px solid var(--line-2)", padding: "10px 0" }}>
          <p><strong>{f.job}</strong>{f.from_name ? `, from ${f.from_name}` : ""} <span className="muted">({date(f.received_at)})</span></p>
          <p>{f.overall_rating ? `Overall ${f.overall_rating}/5` : "Not rated"}{f.recommendation ? `, ${label(f.recommendation)}` : ""}</p>
          {f.scorecard.length > 0 && <p className="muted">{f.scorecard.map((s) => `${s.criterion} ${s.rating}/5`).join(", ")}</p>}
          {f.strengths && <p><strong>Strengths:</strong> {f.strengths}</p>}
          {f.concerns && <p><strong>Concerns:</strong> {f.concerns}</p>}
          {f.notes && <p className="prose">{f.notes}</p>}
        </div>
      ))}
    </div>
  );
}

const KIND: Record<string, string> = { note: "Note", call: "Call", email: "Email", meeting: "Meeting", task: "Task", system: "System" };

function Notes({ candidateId }: { candidateId: string }) {
  const { tenant } = useSession();
  const toast = useToast();
  const acts = useData<any[]>(t(tenant.id, `/activities?candidate_id=${candidateId}`));
  const [kind, setKind] = useState("note");
  const [body, setBody] = useState("");
  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    try {
      await api(t(tenant.id, "/activities"), { method: "POST", json: { kind, body, candidate_id: candidateId } });
      setBody("");
      acts.reload();
    } catch (err: any) { toast(err.message, "error"); }
  }
  return (
    <div className="panel">
      <form onSubmit={add} style={{ display: "grid", gap: 8, marginBottom: 12 }}>
        <div style={{ width: 160 }}><Select value={kind} onChange={setKind} options={[["note", "Note"], ["call", "Call"], ["email", "Email"], ["meeting", "Meeting"]]} /></div>
        <textarea placeholder="What happened?" value={body} onChange={(e) => setBody(e.target.value)} aria-label="Note" />
        <div><button className="btn primary small">Add {kind}</button></div>
      </form>
      {(acts.data ?? []).map((a) => (
        <div key={a.id} style={{ borderTop: "1px solid var(--line-2)", padding: "8px 0" }}>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>{KIND[a.kind] ?? a.kind}, {date(a.created_at)}</p>
          <p className="prose" style={{ margin: 0 }}>{a.body}</p>
        </div>
      ))}
      {acts.data?.length === 0 && <p className="muted">No notes yet.</p>}
    </div>
  );
}
