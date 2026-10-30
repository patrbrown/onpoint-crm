"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, t } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Note } from "@/lib/types";
import { Select, useToast } from "./ui";

const KIND: Record<string, string> = { note: "Note", call: "Call", email: "Email", meeting: "Meeting", task: "Task", system: "System" };
const KINDS: [string, string][] = [["note", "Note"], ["call", "Call"], ["email", "Email"], ["meeting", "Meeting"]];
const key = (kind: string, body: string) => `${kind}\u0000${body}`;
type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";

/** Notes on a candidate: saved automatically while typing and whenever you leave (switch tab, open another
 *  page, close the window). Each note shows who wrote it and when; the writer or an admin can edit or delete it. */
export function Notes({ candidateId }: { candidateId: string }) {
  const { tenant } = useSession();
  const toast = useToast();
  const list = useData<Note[]>(t(tenant.id, `/activities?candidate_id=${candidateId}`));
  const [composer, setComposer] = useState(0);            // bump to start a fresh note
  const [composerId, setComposerId] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);

  const upsert = useCallback((n: Note) => list.setData((xs) =>
    [n, ...(xs ?? []).filter((x) => x.id !== n.id)].sort((a, b) => b.created_at.localeCompare(a.created_at))), [list]);

  async function remove(n: Note) {
    if (!confirm("Delete this note?")) return;
    try {
      await api(t(tenant.id, `/activities/${n.id}`), { method: "DELETE" });
      list.setData((xs) => (xs ?? []).filter((x) => x.id !== n.id));
    } catch (e: any) { toast(e.message, "error"); }
  }

  const shown = (list.data ?? []).filter((n) => n.id !== composerId);
  return (
    <div className="panel notes">
      <NoteEditor key={composer} candidateId={candidateId} onSaved={(n) => { setComposerId(n.id); upsert(n); }}
                  onDeleted={(id) => { setComposerId(null); list.setData((xs) => (xs ?? []).filter((x) => x.id !== id)); }}
                  onDone={() => { setComposerId(null); setComposer((k) => k + 1); }} />
      {list.error && <p className="err-text">{list.error}</p>}
      {shown.map((n) => (
        <article key={n.id} className="note">
          <header className="note-meta">
            <span><strong>{KIND[n.kind] ?? n.kind}</strong> · {n.author_name ?? "Unknown"} · <time dateTime={n.created_at}>{dateTime(n.created_at)}</time>
              {n.updated_at && <span className="muted"> · edited{n.editor_name && n.editor_name !== n.author_name ? ` by ${n.editor_name}` : ""} {dateTime(n.updated_at)}</span>}
            </span>
            {n.can_edit && editing !== n.id && (
              <span className="note-actions">
                <button className="link-btn" onClick={() => setEditing(n.id)}>Edit</button>
                <button className="link-btn danger-text" onClick={() => remove(n)}>Delete</button>
              </span>
            )}
          </header>
          {editing === n.id
            ? <NoteEditor candidateId={candidateId} note={n} onSaved={upsert} onDone={() => setEditing(null)} />
            : <p className="prose note-body">{n.body}</p>}
        </article>
      ))}
      {list.data && shown.length === 0 && <p className="muted" style={{ marginTop: 10 }}>No notes yet.</p>}
    </div>
  );
}

function NoteEditor({ candidateId, note, onSaved, onDone, onDeleted }: {
  candidateId: string; note?: Note; onSaved: (n: Note) => void; onDone: () => void; onDeleted?: (id: string) => void;
}) {
  const { tenant } = useSession();
  const isNew = !note;
  const draftKey = `crm-note-draft:${tenant.id}:${candidateId}`;
  const [kind, setKind] = useState(note?.kind ?? "note");
  const [body, setBody] = useState(note?.body ?? "");
  const [state, setState] = useState<SaveState>("idle");
  const [error, setError] = useState("");
  const d = useRef({ id: note?.id ?? null as string | null, kind, body, saved: key(note?.kind ?? "note", note?.body ?? "") });
  const chain = useRef<Promise<void>>(Promise.resolve());
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const cb = useRef({ onSaved, onDeleted });
  cb.current = { onSaved, onDeleted };

  const flush = useCallback((keepalive = false) => {
    clearTimeout(timer.current);
    const run = async () => {
      const x = d.current;
      const k = key(x.kind, x.body);
      if (k === x.saved) return;
      if (!x.body.trim()) {
        if (isNew && x.id) {             // a new note that was emptied again: drop it
          const id = x.id;
          await api(t(tenant.id, `/activities/${id}`), { method: "DELETE", keepalive });
          x.id = null; x.saved = k; cb.current.onDeleted?.(id); setState("idle");
        } else if (!isNew) { setState("error"); setError("A note can’t be empty. Use Delete to remove it."); }
        else x.saved = k;
        return;
      }
      setState("saving");
      const json = { kind: x.kind, body: x.body };
      const n = x.id
        ? await api<Note>(t(tenant.id, `/activities/${x.id}`), { method: "PATCH", json, keepalive })
        : await api<Note>(t(tenant.id, "/activities"), { method: "POST", json: { ...json, candidate_id: candidateId }, keepalive });
      x.id = n.id; x.saved = k;
      if (isNew && key(d.current.kind, d.current.body) === k) { try { localStorage.removeItem(draftKey); } catch {} }
      cb.current.onSaved(n);
      setState(key(d.current.kind, d.current.body) === k ? "saved" : "dirty");
      setError("");
    };
    chain.current = chain.current.then(run).catch((e: any) => { setState("error"); setError(`Not saved: ${e.message}`); });
    return chain.current;
  }, [tenant.id, candidateId, isNew, draftKey]);

  // A draft left behind (e.g. the window closed mid-save) comes back and saves itself.
  useEffect(() => {
    if (!isNew) return;
    try {
      const saved = JSON.parse(localStorage.getItem(draftKey) || "null");
      if (saved?.body) {
        d.current = { id: saved.id ?? null, kind: saved.kind || "note", body: saved.body, saved: "" };
        setKind(d.current.kind); setBody(saved.body); setState("dirty");
        timer.current = setTimeout(() => flush(), 300);
      }
    } catch {}
  }, [isNew, draftKey, flush]);

  // Save when leaving: switching tab or page (unmount), hiding or closing the window.
  useEffect(() => {
    const away = () => { flush(true); };
    const hidden = () => { if (document.visibilityState === "hidden") flush(true); };
    window.addEventListener("pagehide", away);
    window.addEventListener("beforeunload", away);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pagehide", away);
      window.removeEventListener("beforeunload", away);
      document.removeEventListener("visibilitychange", hidden);
      flush(true);
    };
  }, [flush]);

  function change(next: { kind?: string; body?: string }) {
    const x = d.current;
    if (next.kind !== undefined) { x.kind = next.kind; setKind(next.kind); }
    if (next.body !== undefined) { x.body = next.body; setBody(next.body); }
    if (isNew) { try { localStorage.setItem(draftKey, JSON.stringify({ id: x.id, kind: x.kind, body: x.body })); } catch {} }
    setState(key(x.kind, x.body) === x.saved ? "saved" : "dirty");
    clearTimeout(timer.current);
    timer.current = setTimeout(() => flush(), 1200);
  }
  async function done() {
    await flush();
    if (d.current.saved === key(d.current.kind, d.current.body) || !d.current.body.trim()) onDone();
  }

  const status = state === "saving" ? "Saving…" : state === "saved" ? "Saved" : state === "dirty" ? "Saving shortly…"
    : state === "error" ? error : "Saves automatically";
  return (
    <div className={`note-editor${isNew ? "" : " editing"}`}>
      <textarea placeholder={isNew ? "Add a note. It saves as you type." : undefined} value={body} rows={isNew ? 4 : 5}
                aria-label={isNew ? "New note" : "Edit note"} autoFocus={!isNew}
                onChange={(e) => change({ body: e.target.value })} onBlur={() => flush()}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); done(); } }} />
      <div className="note-bar">
        <div style={{ width: 130 }}><Select value={kind} onChange={(v) => change({ kind: v })} options={KINDS} /></div>
        <span className={`save-state ${state}`} role="status" aria-live="polite">{status}</span>
        <button className="btn small primary" type="button" onClick={done} disabled={isNew && !body.trim()}>
          {isNew ? "Done" : "Done editing"}</button>
      </div>
    </div>
  );
}
