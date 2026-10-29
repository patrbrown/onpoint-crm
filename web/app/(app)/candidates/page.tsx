"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { BulkImport } from "@/components/BulkImport";
import { CandidateForm } from "@/components/CandidateForm";
import { ResumeUpload } from "@/components/ResumeUpload";
import { SavedViews } from "@/components/SavedViews";
import { Drawer, Empty, Select, Status, Tags } from "@/components/ui";
import { t } from "@/lib/api";
import { date, fullName, label } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Candidate } from "@/lib/types";

type Filters = { q: string; status: string; source: string };

export default function CandidatesPage() {
  const { tenant } = useSession();
  const router = useRouter();
  const cands = useData<Candidate[]>(t(tenant.id, "/candidates?limit=1000"));
  const [f, setF] = useState<Filters>({ q: "", status: "", source: "" });
  const [panel, setPanel] = useState<"none" | "upload" | "bulk" | "manual">("none");

  const rows = (cands.data ?? []).filter((c) => {
    const hay = `${fullName(c)} ${c.email ?? ""} ${c.phone ?? ""} ${c.current_title ?? ""} ${c.current_company ?? ""} ${c.location ?? ""} ${c.skills.join(" ")} ${c.systems.join(" ")} ${c.certifications.join(" ")}`.toLowerCase();
    return f.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w)) && (!f.status || c.status === f.status)
      && (!f.source || c.source === f.source);
  });

  return (
    <>
      <div className="page-head">
        <div><h1>Candidates</h1><p>{rows.length} of {cands.data?.length ?? 0} shown</p></div>
        <div className="actions">
          <button className="btn" onClick={() => setPanel("manual")}>Add by hand</button>
          <button className="btn" onClick={() => setPanel("bulk")}>Bulk import</button>
          <button className="btn primary" onClick={() => setPanel("upload")}>Upload resumes</button>
        </div>
      </div>
      <div className="toolbar">
        <input className="search" type="search" placeholder="Search name, skill, system, location" value={f.q}
               onChange={(e) => setF({ ...f, q: e.target.value })} aria-label="Search candidates" />
        <Select value={f.status} onChange={(v) => setF({ ...f, status: v })} placeholder="Any status"
                options={[["active", "Active"], ["placed", "Placed"], ["do_not_contact", "Do not contact"], ["archived", "Archived"]]} />
        <Select value={f.source} onChange={(v) => setF({ ...f, source: v })} placeholder="Any source"
                options={[["manual", "Added manually"], ["import", "Imported"], ["email", "From email"], ["portal", "Applied online"]]} />
      </div>
      <SavedViews entity="candidates" current={f} layout="table" onApply={(c) => setF(c)} />

      {cands.error && <div className="form-error">{cands.error}</div>}
      {cands.data && cands.data.length === 0 ? (
        <Empty title="No candidates yet">
          <p>Upload a few resumes, or bring in your existing database with a ZIP of resumes and a CSV.</p>
          <div className="actions" style={{ justifyContent: "center" }}>
            <button className="btn primary" onClick={() => setPanel("upload")}>Upload resumes</button>
            <button className="btn" onClick={() => setPanel("bulk")}>Bulk import</button>
          </div>
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Current role</th><th>Location</th><th>Systems</th><th>Contact</th><th>Status</th><th>Added</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => router.push(`/candidates/${c.id}`)}>
                  <td><a href={`/candidates/${c.id}`} onClick={(e) => e.preventDefault()}>{fullName(c)}</a>
                    <span className="sub">{label(c.source)}</span></td>
                  <td>{c.current_title}<span className="sub">{c.current_company}</span></td>
                  <td>{c.location}</td>
                  <td><Tags items={c.systems} tone="system" /></td>
                  <td>{c.email}<span className="sub">{c.phone}</span></td>
                  <td><Status value={c.status} text={label(c.status)} /></td>
                  <td className="muted">{date(c.created_at)}</td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={7} className="muted">No candidates match these filters.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      <Drawer title="Upload resumes" open={panel === "upload"} onClose={() => setPanel("none")}>
        <ResumeUpload onDone={() => cands.reload()} />
      </Drawer>
      <Drawer title="Bulk import" open={panel === "bulk"} onClose={() => setPanel("none")}>
        <BulkImport onDone={() => cands.reload()} />
      </Drawer>
      <Drawer title="Add a candidate" open={panel === "manual"} onClose={() => setPanel("none")}>
        <CandidateForm onCancel={() => setPanel("none")} onSaved={(c) => router.push(`/candidates/${c.id}`)} />
      </Drawer>
    </>
  );
}
