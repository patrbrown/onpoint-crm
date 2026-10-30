"use client";

import { useState } from "react";
import { api, t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Member } from "@/lib/types";
import { Field, useToast } from "../ui";

const ROLE: Record<string, string> = { owner: "Owner", admin: "Admin", recruiter: "Recruiter", viewer: "Viewer" };

/** Settings → Users: the people you can tag as the uploader of a resume, and who appear on notes. */
export function TeamSettings() {
  const { tenant } = useSession();
  const toast = useToast();
  const [showRemoved, setShowRemoved] = useState(false);
  const team = useData<Member[]>(t(tenant.id, `/team${showRemoved ? "?include_inactive=true" : ""}`));
  const admin = ["owner", "admin", "platform_admin"].includes(tenant.role);
  const [f, setF] = useState({ full_name: "", email: "", title: "" });
  const [error, setError] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api(t(tenant.id, "/team"), { method: "POST", json: {
        full_name: f.full_name.trim(), email: f.email.trim() || null, title: f.title.trim() || null } });
      setF({ full_name: "", email: "", title: "" });
      toast("Added to the team");
      team.reload();
    } catch (err: any) { setError(err.message); }
  }
  async function save(m: Member, patch: Partial<Member>) {
    try { await api(t(tenant.id, `/team/${m.id}`), { method: "PATCH", json: patch }); team.reload(); }
    catch (e: any) { toast(e.message, "error"); team.reload(); }
  }
  const field = (m: Member, k: "full_name" | "email" | "title", label: string) => {
    const editable = admin || m.is_me;
    if (!editable || (k === "email" && m.has_login)) return <span>{m[k] || <span className="muted">None</span>}</span>;
    return <input aria-label={`${label} for ${m.full_name}`} defaultValue={m[k] ?? ""} key={`${m.id}-${m[k]}`}
                  onBlur={(e) => { const v = e.target.value.trim(); if (v !== (m[k] ?? "") && (v || k !== "full_name")) save(m, { [k]: v || null }); }} />;
  };

  return (
    <div className="panel">
      <div className="panel-head"><h2>Users</h2>
        <label className="check"><input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} /> Show removed</label>
      </div>
      <p className="muted">Everyone at the agency you can tag as the person who uploaded a resume. Notes show who wrote them.
        People who sign in are added here automatically; people you add by hand can be tagged but don’t get a login.</p>
      <div className="table-wrap" style={{ margin: "12px 0" }}>
        <table className="team">
          <thead><tr><th>Name</th><th>Email</th><th>Title</th><th>Sign-in</th><th /></tr></thead>
          <tbody>
            {(team.data ?? []).map((m) => (
              <tr key={m.id} className={m.is_active ? "" : "muted"}>
                <td>{field(m, "full_name", "Name")}{m.is_me && <span className="sub">You</span>}</td>
                <td>{field(m, "email", "Email")}</td>
                <td>{field(m, "title", "Title")}</td>
                <td>{m.has_login ? (ROLE[m.role ?? ""] ?? "Can sign in") : <span className="muted">No login</span>}</td>
                <td className="num">{admin && !m.is_me && (m.is_active
                  ? <button className="link-btn danger-text" onClick={() => confirm(`Remove ${m.full_name}? Their past uploads and notes keep their name.`) && save(m, { is_active: false })}>Remove</button>
                  : <button className="link-btn" onClick={() => save(m, { is_active: true })}>Restore</button>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {admin && (
        <form onSubmit={add}>
          <h3>Add someone</h3>
          {error && <div className="form-error" role="alert">{error}</div>}
          <div className="form-grid three">
            <Field label="Name"><input required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
            <Field label="Email (optional)"><input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Title (optional)"><input value={f.title} placeholder="Recruiter" onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          </div>
          <div className="form-foot"><button className="btn primary" disabled={!f.full_name.trim()}>Add to team</button></div>
        </form>
      )}
    </div>
  );
}
