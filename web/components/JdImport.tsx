"use client";

import { useRef, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { Markdown } from "./Markdown";
import { useToast } from "./ui";

type Source = { id: string; file_name: string; size_bytes: number; subject: string; received_at: string; suggested: boolean };

/** Fill a job's description from a JD file, copied word for word as Markdown. */
export function JdImport({ jobId, current, onSaved }: { jobId: string; current: string | null; onSaved: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const sources = useData<{ attachments: Source[] }>(t(tenant.id, `/jobs/${jobId}/jd-sources`));
  const fileInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<{ markdown: string; file_name: string } | null>(null);
  const [mode, setMode] = useState<"replace" | "append">(current ? "append" : "replace");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  async function fromAttachment(id: string) {
    setBusy(true);
    try { setPreview(await api(t(tenant.id, `/jobs/${jobId}/jd-preview/attachment/${id}`), { method: "POST" })); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  async function fromFile(f: File | undefined) {
    if (!f) return;
    setBusy(true);
    const body = new FormData();
    body.append("file", f);
    try { setPreview(await api(t(tenant.id, `/jobs/${jobId}/jd-preview/file`), { method: "POST", body })); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  }
  async function save() {
    if (!preview) return;
    const description = mode === "append" && current ? `${current.trim()}\n\n${preview.markdown}` : preview.markdown;
    try {
      await api(t(tenant.id, `/jobs/${jobId}`), { method: "PATCH", json: { description } });
      toast("Job description updated");
      onSaved();
    } catch (e: any) { toast(e.message, "error"); }
  }

  if (preview) return (
    <>
      <p className="muted">From <strong>{preview.file_name}</strong>, copied word for word. Check it, edit if needed, then save.</p>
      <div className="actions" style={{ margin: "8px 0 12px" }}>
        <button className={`view-chip`} aria-pressed={!editing} onClick={() => setEditing(false)}>Preview</button>
        <button className={`view-chip`} aria-pressed={editing} onClick={() => setEditing(true)}>Edit text</button>
      </div>
      {editing ? <textarea rows={22} value={preview.markdown} onChange={(e) => setPreview({ ...preview, markdown: e.target.value })} />
        : <div className="panel" style={{ maxHeight: 460, overflow: "auto" }}><Markdown text={preview.markdown} /></div>}
      {current && (
        <div className="actions" style={{ marginTop: 12 }}>
          <label className="check"><input type="radio" checked={mode === "replace"} onChange={() => setMode("replace")} /> Replace the current description</label>
          <label className="check"><input type="radio" checked={mode === "append"} onChange={() => setMode("append")} /> Add below it</label>
        </div>
      )}
      <div className="form-foot">
        <button className="btn" onClick={() => setPreview(null)}>Back</button>
        <button className="btn primary" onClick={save}>Save description</button>
      </div>
    </>
  );

  const atts = sources.data?.attachments ?? [];
  return (
    <>
      <h3 style={{ marginBottom: 8 }}>From the email this job came from</h3>
      {sources.data && atts.length === 0 && <p className="muted">No Word, PDF or text attachments on that email.</p>}
      {atts.map((a) => (
        <div key={a.id} className="conn-row" style={{ padding: "6px 0", borderBottom: "1px solid var(--line-2)" }}>
          <div className="conn-main"><strong>{a.file_name}</strong>{a.suggested && <span className="muted"> (looks like the JD)</span>}
            <div className="muted" style={{ fontSize: 12 }}>{a.subject}, {date(a.received_at)}</div></div>
          <button className="btn small" disabled={busy} onClick={() => fromAttachment(a.id)}>Use this file</button>
        </div>
      ))}
      <h3 style={{ margin: "20px 0 8px" }}>Or upload a JD file</h3>
      <div className="dropzone">
        <button className="btn" disabled={busy} onClick={() => fileInput.current?.click()}>{busy ? "Converting…" : "Choose a Word, PDF or text file"}</button>
        <input ref={fileInput} type="file" accept=".docx,.pdf,.txt,.md" hidden onChange={(e) => { fromFile(e.target.files?.[0]); e.target.value = ""; }} />
      </div>
    </>
  );
}
