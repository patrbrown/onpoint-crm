"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CandidateForm } from "@/components/CandidateForm";
import { ContactDetails } from "@/components/ContactDetails";
import { FeedbackForm } from "@/components/FeedbackForm";
import { Notes } from "@/components/Notes";
import { ResumePane } from "@/components/ResumePane";
import { ResumeUpload } from "@/components/ResumeUpload";
import { TagEditor } from "@/components/TagEditor";
import { Drawer, Select, Status, useToast } from "@/components/ui";
import { api, t } from "@/lib/api";
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
  const [tab, setTab] = useState<"notes" | "details" | "jobs">("notes");
  const [drawer, setDrawer] = useState<"none" | "edit" | "job" | "feedback" | "resume">("none");
  const [fbVersion, setFbVersion] = useState(0);

  if (cand.error) return <div className="form-error">{cand.error}</div>;
  if (!cand.data) return <p className="muted">Loading…</p>;
  const c = cand.data;

  async function setList(k: "skills" | "systems" | "certifications", next: string[]) {
    const before = c;
    cand.setData({ ...c, [k]: next });
    try { cand.setData(await api<Candidate>(t(tenant.id, `/candidates/${id}`), { method: "PATCH", json: { [k]: next } })); }
    catch (e: any) { cand.setData(before); toast(e.message, "error"); }
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

      <div className="review">
        <ResumePane docs={docs.data} onUpload={() => setDrawer("resume")} />
        <div>
          <div className="tabs" role="tablist">
            {([["notes", "Notes"], ["details", "Details and skills"], ["jobs", `Jobs and feedback${apps.data?.length ? ` (${apps.data.length})` : ""}`]] as const).map(([k, l]) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>
          {tab === "notes" && <Notes candidateId={c.id} />}
          {tab === "details" && (
            <>
              <ContactDetails candidate={c} onSaved={(saved) => cand.setData(saved)} />
              <div className="panel">
                {c.summary && <><h3>Summary</h3><p className="prose">{c.summary}</p></>}
                <TagEditor label="Skills" items={c.skills} onChange={(v) => setList("skills", v)} placeholder="Add a skill, then press Enter" />
                <TagEditor label="Systems and modules" tone="system" items={c.systems} onChange={(v) => setList("systems", v)}
                           placeholder="e.g. Epic Beaker" />
                <TagEditor label="Certifications" items={c.certifications} onChange={(v) => setList("certifications", v)}
                           placeholder="e.g. Epic Certified - Ambulatory" />
              </div>
              <button className="btn danger small" style={{ marginTop: 14 }} onClick={remove}>Delete candidate</button>
            </>
          )}
          {tab === "jobs" && (
            <>
              <div className="panel">
                <div className="panel-head"><h2>Jobs</h2><button className="btn small" onClick={() => setDrawer("job")}>Add to a job</button></div>
                {apps.data?.length ? apps.data.map((a) => (
                  <p key={a.id}><Link href={`/jobs/${a.job_id}`}>{a.job_title}</Link><br />
                    <span className="muted">{a.stage_name ?? "No stage"}{a.match_score !== null ? `, match ${a.match_score}` : ""}</span></p>
                )) : <p className="muted">Not on any job yet.</p>}
              </div>
              <FeedbackList apps={apps.data ?? []} version={fbVersion} onAdd={() => setDrawer("feedback")} />
            </>
          )}
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
                      onSaved={() => { setDrawer("none"); setTab("jobs"); setFbVersion((v) => v + 1); }} />
      </Drawer>
      <Drawer title="Upload a resume" open={drawer === "resume"} onClose={() => setDrawer("none")}>
        <ResumeUpload candidateId={c.id} onDone={() => { setDrawer("none"); docs.reload(); cand.reload(); }} />
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
