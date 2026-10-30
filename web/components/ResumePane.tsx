"use client";

import { useEffect, useState } from "react";
import { apiBlobUrl, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Doc } from "@/lib/types";
import { useToast } from "./ui";

const isPdf = (d: Doc) => d.mime_type === "application/pdf" || d.file_name.toLowerCase().endsWith(".pdf");

/** The candidate's resume, kept in view beside the notes. PDFs show as the original page; other files as text. */
export function ResumePane({ docs, onUpload }: { docs: Doc[] | null; onUpload: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const [sel, setSel] = useState<string | null>(null);
  const doc = docs?.find((d) => d.id === sel) ?? docs?.[0];
  const [view, setView] = useState<"original" | "text">("original");
  const [url, setUrl] = useState<string | null>(null);
  const showOriginal = !!doc && isPdf(doc) && view === "original";

  useEffect(() => {
    if (!doc || !showOriginal) return;
    let u: string | null = null;
    let live = true;
    setUrl(null);
    apiBlobUrl(t(tenant.id, `/documents/${doc.id}/download`))
      .then((x) => { u = x; if (live) setUrl(x); else URL.revokeObjectURL(x); })
      .catch(() => { if (live) setView("text"); });
    return () => { live = false; if (u) URL.revokeObjectURL(u); };
  }, [doc?.id, showOriginal, tenant.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function open() {
    if (!doc) return;
    try { window.open(await apiBlobUrl(t(tenant.id, `/documents/${doc.id}/download`)), "_blank"); }
    catch (e: any) { toast(e.message, "error"); }
  }

  return (
    <section className="panel resume-pane" aria-label="Resume">
      <div className="panel-head">
        {docs && docs.length > 1 ? (
          <select className="doc-pick" aria-label="Choose a file" value={doc?.id} onChange={(e) => setSel(e.target.value)}>
            {docs.map((d, i) => <option key={d.id} value={d.id}>{d.file_name}{i === 0 ? " (latest)" : `, ${date(d.created_at)}`}</option>)}
          </select>
        ) : <h2 className="doc-name">{doc ? doc.file_name : "No resume on file"}</h2>}
        <div className="actions">
          {doc && isPdf(doc) && (
            <div className="seg" role="group" aria-label="Resume view">
              <button aria-pressed={view === "original"} onClick={() => setView("original")}>Original</button>
              <button aria-pressed={view === "text"} onClick={() => setView("text")}>Text</button>
            </div>
          )}
          {doc && <button className="btn small" onClick={open}>Open</button>}
          <button className="btn small" onClick={onUpload}>Upload</button>
        </div>
      </div>
      {doc && <p className="doc-meta">Uploaded {date(doc.created_at)}{doc.uploaded_by_name ? ` by ${doc.uploaded_by_name}` : ""}</p>}
      <div className="resume-body">
        {!docs ? <p className="muted">Loading…</p>
          : !doc ? <p className="muted">Upload a resume to read it here while you take notes.</p>
          : showOriginal ? (url ? <iframe src={url} title={`Resume: ${doc.file_name}`} /> : <p className="muted">Opening…</p>)
          : doc.extracted_text ? <div className="resume-text">{doc.extracted_text}</div>
          : <p className="muted">No text could be read from this file. Use Open to see the original.</p>}
      </div>
    </section>
  );
}
