"use client";

import { useState } from "react";
import { api, apiBlobUrl, t } from "@/lib/api";
import { date, splitList } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Job } from "@/lib/types";
import { Field, Select, useToast } from "./ui";

export type Match = { type: string; id: string; label: string; reason: string; score: number; contact_id?: string; contact_label?: string; detail?: string };
type Detail = {
  item: { id: string; item_type: string; status: string; confidence: string | null; extracted: Record<string, any>; suggested_matches: Match[] };
  email: { subject: string; from_address: string; from_name: string; received_at: string; body_text: string } | null;
  attachments: { id: string; file_name: string; size_bytes: number }[];
};

type Spec = { key: string; label: string; kind?: "list" | "long" | "select"; options?: [string, string][]; wide?: boolean };
const JOB_FIELDS: Spec[] = [
  { key: "title", label: "Job title", wide: true }, { key: "client_name", label: "Client" },
  { key: "reference_code", label: "Client req number" }, { key: "location", label: "Location" },
  { key: "employment_type", label: "Employment type", kind: "select", options: [["permanent", "Permanent"], ["contract", "Contract"], ["contract_to_hire", "Contract to hire"], ["temporary", "Temporary"]] },
  { key: "work_model", label: "Work model", kind: "select", options: [["onsite", "On-site"], ["hybrid", "Hybrid"], ["remote", "Remote"]] },
  { key: "rate_min", label: "Rate from" }, { key: "rate_max", label: "Rate to" },
  { key: "rate_unit", label: "Rate per", kind: "select", options: [["hour", "Hour"], ["day", "Day"], ["month", "Month"]] },
  { key: "salary_min", label: "Salary from" }, { key: "salary_max", label: "Salary to" }, { key: "currency", label: "Currency" },
  { key: "must_have_skills", label: "Must-have skills", kind: "list", wide: true },
  { key: "nice_to_have_skills", label: "Nice-to-have skills", kind: "list", wide: true },
  { key: "systems", label: "Systems and modules", kind: "list" }, { key: "certifications", label: "Certifications", kind: "list" },
  { key: "description", label: "Job description", kind: "long", wide: true },
];
const RESUME_FIELDS: Spec[] = [
  { key: "first_name", label: "First name" }, { key: "last_name", label: "Last name" }, { key: "email", label: "Email" },
  { key: "phone", label: "Phone" }, { key: "linkedin_url", label: "LinkedIn", wide: true }, { key: "current_title", label: "Current title" },
  { key: "current_company", label: "Current company" }, { key: "location", label: "Location" },
  { key: "years_experience", label: "Years of experience" }, { key: "systems", label: "Systems and modules", kind: "list", wide: true },
  { key: "skills", label: "Skills", kind: "list", wide: true }, { key: "certifications", label: "Certifications", kind: "list", wide: true },
  { key: "summary", label: "Summary", kind: "long", wide: true },
];
const RECS: [string, string][] = [["strong_yes", "Strong yes"], ["yes", "Yes"], ["maybe", "Maybe"], ["no", "No"], ["strong_no", "Strong no"]];
const FEEDBACK_FIELDS: Spec[] = [
  { key: "from_name", label: "Feedback from" }, { key: "overall_rating", label: "Overall rating (1–5)" },
  { key: "recommendation", label: "Recommendation", kind: "select", options: RECS },
  { key: "strengths", label: "Strengths", kind: "long", wide: true }, { key: "concerns", label: "Concerns", kind: "long", wide: true },
  { key: "notes", label: "Other notes", kind: "long", wide: true },
];
export const TYPE_LABEL: Record<string, string> = {
  job_requisition: "Job requisition", resume: "Resume", interview_feedback: "Interview feedback",
  client_correspondence: "Client email", candidate_reply: "Candidate reply", other: "Not relevant",
};

function toForm(specs: Spec[], x: Record<string, any>) {
  const f: Record<string, string> = {};
  for (const s of specs) {
    const v = x[s.key];
    f[s.key] = Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v);
  }
  return f;
}
function fromForm(specs: Spec[], f: Record<string, string>, base: Record<string, any>) {
  const out: Record<string, any> = { ...base };
  for (const s of specs) out[s.key] = s.kind === "list" ? splitList(f[s.key]) : f[s.key] === "" ? null : f[s.key];
  return out;
}

export function InboxReview({ id, onDone }: { id: string; onDone: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const d = useData<Detail>(t(tenant.id, `/inbox/${id}`));
  if (!d.data) return <p className="muted">Loading…</p>;
  return <ReviewForm key={id} detail={d.data} tenantId={tenant.id} onDone={onDone} toast={toast} />;
}

function ReviewForm({ detail, tenantId, onDone, toast }: { detail: Detail; tenantId: string; onDone: () => void; toast: ReturnType<typeof useToast> }) {
  const { item, email, attachments } = detail;
  const kind = item.item_type;
  const specs = kind === "job_requisition" ? JOB_FIELDS : kind === "resume" ? RESUME_FIELDS : FEEDBACK_FIELDS;
  const ex = item.extracted;
  const [f, setF] = useState(() => {
    const base = toForm(specs, ex);
    if (kind === "job_requisition") { base.hc_name = ex.hiring_contact?.name ?? email?.from_name ?? ""; base.hc_email = ex.hiring_contact?.email ?? email?.from_address ?? ""; }
    return base;
  });
  const matches = item.suggested_matches ?? [];
  const of = (type: string) => matches.filter((m) => m.type === type);
  const [clientId, setClientId] = useState(of("client")[0]?.id ?? "");
  const [candidateId, setCandidateId] = useState(of("candidate").find((m) => m.reason === "same email")?.id ?? "");
  const [jobId, setJobId] = useState(of("job")[0]?.id ?? "");
  const [appId, setAppId] = useState(of("application")[0]?.id ?? "");
  const [comment, setComment] = useState("");
  const [showBody, setShowBody] = useState(false);
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const pending = item.status === "pending";
  const openJobs = useData<Job[]>(kind === "resume" ? t(tenantId, "/jobs?status=open&limit=1000") : null);
  const apps = useData<any[]>(kind === "interview_feedback" ? t(tenantId, "/applications") : null);

  async function approve() {
    setBusy(true);
    const final = fromForm(specs, f, {});
    const links: Record<string, any> = {};
    if (kind === "job_requisition") {
      final.hiring_contact = { name: f.hc_name || null, email: f.hc_email || null, phone: ex.hiring_contact?.phone ?? null, title: ex.hiring_contact?.title ?? null };
      final.scorecard = undefined;
      if (clientId) {
        const m = of("client").find((x) => x.id === clientId);
        links.client_id = clientId;
        if (m?.contact_id) links.contact_id = m.contact_id;
      }
    }
    if (kind === "resume") { if (candidateId) links.candidate_id = candidateId; if (jobId) links.job_id = jobId; }
    if (kind === "interview_feedback") { final.scorecard = ex.scorecard ?? []; final.from_email = ex.from_email; links.application_id = appId || undefined; }
    try {
      const r = await api<any>(t(tenantId, `/inbox/${item.id}/approve`), { method: "POST", json: { final, links, comment: comment || null } });
      toast(r.entity_type === "job" ? "Job created" : r.entity_type === "candidate" ? "Candidate saved" : "Feedback recorded");
      onDone();
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }

  const dupJobs = kind === "job_requisition" ? of("job") : [];

  return (
    <div className="review">
      {email && (
        <section className="email-card">
          <div className="email-head">
            <strong>{email.subject || "(no subject)"}</strong>
            <span className="muted">{email.from_name ? `${email.from_name} <${email.from_address}>` : email.from_address}, {date(email.received_at)}</span>
          </div>
          {attachments.length > 0 && <p className="atts">{attachments.map((a) => (
            <button key={a.id} className="link-btn" onClick={async () => window.open(await apiBlobUrl(t(tenantId, `/attachments/${a.id}/download`)), "_blank")}>
              {a.file_name}</button>))}</p>}
          <button className="link-btn" onClick={() => setShowBody(!showBody)}>{showBody ? "Hide email" : "Show email"}</button>
          {showBody && <div className="resume-text" style={{ marginTop: 8 }}>{email.body_text}</div>}
        </section>
      )}

      <p className="muted" style={{ margin: "12px 0" }}>
        The assistant read this as {kind === "interview_feedback" ? "" : "a "}<strong>{TYPE_LABEL[kind].toLowerCase()}</strong>
        {item.confidence ? ` (${Math.round(Number(item.confidence) * 100)}% sure)` : ""}. Check the details, fix anything that’s off, then save.
      </p>

      {dupJobs.length > 0 && <div className="warn">This may already be in the CRM as {dupJobs.map((j) => <a key={j.id} href={`/jobs/${j.id}`} target="_blank" rel="noreferrer">“{j.label}”</a>)} ({dupJobs[0].reason}). If so, reject it as a duplicate.</div>}

      {kind === "job_requisition" && (
        <div className="form-grid" style={{ marginBottom: 12 }}>
          <Field label="Save under client" hint={clientId ? of("client").find((m) => m.id === clientId)?.reason : "A new client is created from the name below"}>
            <Select value={clientId} onChange={setClientId} placeholder="Create a new client"
                    options={of("client").map((m) => [m.id, m.label])} />
          </Field>
          <div />
          <Field label="Hiring contact name"><input value={f.hc_name} onChange={(e) => setF({ ...f, hc_name: e.target.value })} /></Field>
          <Field label="Hiring contact email"><input value={f.hc_email} onChange={(e) => setF({ ...f, hc_email: e.target.value })} /></Field>
        </div>
      )}
      {kind === "resume" && (
        <div className="form-grid" style={{ marginBottom: 12 }}>
          <Field label="Candidate" hint={candidateId ? "Blank fields on the existing record are filled in; nothing is overwritten" : undefined}>
            <Select value={candidateId} onChange={setCandidateId} placeholder="Add as a new candidate"
                    options={of("candidate").map((m) => [m.id, `Merge into ${m.label} (${m.reason})`])} />
          </Field>
          <Field label="Add to job" hint={of("job").find((m) => m.id === jobId)?.reason}>
            <Select value={jobId} onChange={setJobId} placeholder="Don’t add to a job yet"
                    options={(openJobs.data ?? []).map((j) => [j.id, j.title])} />
          </Field>
        </div>
      )}
      {kind === "interview_feedback" && (
        <div className="form-grid" style={{ marginBottom: 12 }}>
          <Field label="Feedback is about" wide hint={ex.candidate_name ? `The email mentions ${ex.candidate_name}${ex.job_title ? ` for ${ex.job_title}` : ""}` : undefined}>
            <Select value={appId} onChange={setAppId} placeholder="Choose the candidate and job"
                    options={[...of("application").map((m) => [m.id, `${m.label} (suggested)`] as [string, string]),
                      ...(apps.data ?? []).filter((a) => !of("application").some((m) => m.id === a.id))
                        .map((a) => [a.id, `${a.first_name} ${a.last_name ?? ""}, ${a.job_title}`] as [string, string])]} />
          </Field>
          {(ex.scorecard ?? []).length > 0 && <p className="field wide muted">Scorecard: {(ex.scorecard as any[]).map((s) => `${s.criterion} ${s.rating}/5`).join(", ")}</p>}
        </div>
      )}

      <div className="form-grid">
        {specs.map((s) => (
          <Field key={s.key} label={s.label} wide={s.wide}>
            {s.kind === "long" ? <textarea rows={s.key === "description" ? 8 : 3} value={f[s.key]} onChange={(e) => setF({ ...f, [s.key]: e.target.value })} />
              : s.kind === "select" ? <Select value={f[s.key]} onChange={(v) => setF({ ...f, [s.key]: v })} placeholder="Not set" options={s.options!} />
              : <input value={f[s.key]} onChange={(e) => setF({ ...f, [s.key]: e.target.value })} />}
          </Field>
        ))}
        <Field label="Note to the assistant (optional)" hint="What it got wrong or should do differently next time. Used to improve future suggestions." wide>
          <input value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
      </div>

      {pending ? (
        <div className="form-foot">
          <button className="btn danger" style={{ marginRight: "auto" }} onClick={() => setRejecting(true)}>Reject</button>
          <button className="btn primary" disabled={busy || (kind === "interview_feedback" && !appId)} onClick={approve}>
            {busy ? "Saving…" : kind === "job_requisition" ? "Create job" : kind === "resume" ? (candidateId ? "Update candidate" : "Add candidate") : "Record feedback"}
          </button>
        </div>
      ) : <p className="muted" style={{ marginTop: 14 }}>This item was {item.status.replace("_", " ")}.</p>}

      {rejecting && <RejectForm itemId={item.id} kind={kind} tenantId={tenantId} onDone={onDone} toast={toast} onCancel={() => setRejecting(false)} />}
    </div>
  );
}

function RejectForm({ itemId, kind, tenantId, onDone, onCancel, toast }: {
  itemId: string; kind: string; tenantId: string; onDone: () => void; onCancel: () => void; toast: ReturnType<typeof useToast>;
}) {
  const [reason, setReason] = useState("wrong_type");
  const [correct, setCorrect] = useState(kind === "resume" ? "job_requisition" : "resume");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      const r = await api<any>(t(tenantId, `/inbox/${itemId}/reject`), { method: "POST",
        json: { reason, correct_type: reason === "wrong_type" ? correct : null, comment: comment || null } });
      toast(r.new_items?.length ? `Re-read as ${TYPE_LABEL[correct].toLowerCase()}: check the new item` : "Rejected. Thanks, the assistant will learn from this.");
      onDone();
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  return (
    <div className="panel" style={{ marginTop: 14 }}>
      <h3 style={{ marginBottom: 10 }}>Why reject it?</h3>
      <div className="form-grid">
        <Field label="Reason">
          <Select value={reason} onChange={setReason} options={[["wrong_type", `It isn’t a ${TYPE_LABEL[kind].toLowerCase()}`],
            ["not_relevant", "Not relevant to recruiting"], ["duplicate", "Already in the CRM"], ["other", "Something else"]]} />
        </Field>
        {reason === "wrong_type" && (
          <Field label="It’s actually" hint={["job_requisition", "resume", "interview_feedback"].includes(correct) ? "The email is re-read as this type" : undefined}>
            <Select value={correct} onChange={setCorrect} options={Object.entries(TYPE_LABEL).filter(([k]) => k !== kind) as [string, string][]} />
          </Field>
        )}
        <Field label="Note to the assistant (optional)" wide>
          <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. Emails from jobs@indeed are job alerts, not reqs" />
        </Field>
      </div>
      <div className="form-foot">
        <button className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn danger" disabled={busy} onClick={submit}>{busy ? "Saving…" : "Reject"}</button>
      </div>
    </div>
  );
}
