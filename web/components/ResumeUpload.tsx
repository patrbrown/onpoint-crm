"use client";

import { useRef, useState } from "react";
import { api, t } from "@/lib/api";
import { fullName } from "@/lib/format";
import { useSession } from "@/lib/session";
import { UploadedBy } from "./UploadedBy";
import { useToast } from "./ui";

/** One resume (PDF/DOCX) → candidate. Optional jobId links the new candidate to that job; candidateId attaches the
 *  file to that candidate (it becomes their main resume). */
export function ResumeUpload({ jobId, candidateId, onDone }: { jobId?: string; candidateId?: string; onDone: (candidateId: string) => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [by, setBy] = useState("");

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    for (const file of Array.from(files)) {
      setBusy(file.name);
      const body = new FormData();
      body.append("file", file);
      if (jobId) body.append("job_id", jobId);
      if (candidateId) body.append("candidate_id", candidateId);
      if (by) body.append("uploaded_by", by);
      try {
        const r = await api<any>(t(tenant.id, "/candidates/upload"), { method: "POST", body });
        toast(r.created ? `Added ${fullName(r.candidate)}` : `Updated ${fullName(r.candidate)} (already in the database)`);
        onDone(r.candidate.id);
      } catch (e: any) {
        toast(`${file.name}: ${e.message}`, "error");
      }
    }
    setBusy(null);
  }

  return (
    <>
    <div style={{ maxWidth: 280, marginBottom: 10 }}><UploadedBy value={by} onChange={setBy} /></div>
    <div className={`dropzone${over ? " over" : ""}`}
         onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
         onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}>
      {busy ? <p>Reading {busy}…</p> : <>
        <p>{candidateId ? "Drop a resume here (PDF or Word), or" : "Drop resumes here (PDF or Word), or"}</p>
        <button className="btn" type="button" onClick={() => input.current?.click()}>Choose files</button>
      </>}
      <input ref={input} type="file" multiple={!candidateId} accept=".pdf,.docx,.txt" hidden onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
      <p className="field-hint" style={{ marginTop: 8 }}>
        {candidateId ? "The file becomes this candidate’s main resume; blank details are filled in from it."
          : "Details are read from the resume. If the email matches an existing candidate, their record is updated instead."}
      </p>
    </div>
    </>
  );
}
