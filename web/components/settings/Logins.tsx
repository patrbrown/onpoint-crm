"use client";

import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { Field, Select, useToast } from "../ui";

type Member = { user_id: string; role: string; added_at: string; email: string; name: string; last_sign_in_at: string | null; is_me: boolean };
type Invite = { user_id: string; email: string; emailed: boolean; link: string | null; note: string | null };
const ROLES: [string, string][] = [["recruiter", "Recruiter"], ["admin", "Admin"], ["owner", "Owner"]];
const ROLE_HELP = "Admins also manage users, the website and AI settings. Owners can do everything, including adding other owners.";

export type InvitePrefill = { email: string; full_name: string } | null;

/** Settings → Users: people who can sign in. Invite, change role, send a new sign-in link, remove access. */
export function Logins({ prefill, onChanged }: { prefill?: InvitePrefill; onChanged?: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const members = useData<Member[]>(t(tenant.id, "/team/members"));
  const myRole = tenant.role === "platform_admin" ? "owner" : tenant.role;
  const admin = myRole === "owner" || myRole === "admin";
  const [form, setForm] = useState({ email: prefill?.email ?? "", full_name: prefill?.full_name ?? "", role: "recruiter", send_email: false });
  useEffect(() => {   // "Invite" clicked on someone in the Users list below
    if (prefill) setForm((f) => ({ ...f, email: prefill.email, full_name: prefill.full_name }));
  }, [prefill]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<(Invite & { name: string }) | null>(null);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setResult(null);
    try {
      const r = await api<Invite>(t(tenant.id, "/team/invites"), { method: "POST", json: {
        email: form.email.trim(), full_name: form.full_name.trim() || null, role: form.role, send_email: form.send_email } });
      setResult({ ...r, name: form.full_name.trim() || r.email });
      setForm({ email: "", full_name: "", role: "recruiter", send_email: form.send_email });
      members.reload(); onChanged?.();
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  async function newLink(m: Member) {
    try {
      const r = await api<{ email: string; link: string }>(t(tenant.id, `/team/members/${m.user_id}/link`), { method: "POST" });
      setResult({ user_id: m.user_id, email: r.email, emailed: false, link: r.link, note: null, name: m.name });
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function setRole(m: Member, role: string) {
    try { await api(t(tenant.id, `/team/members/${m.user_id}`), { method: "PATCH", json: { role } }); toast(`${m.name} is now ${role === "admin" ? "an admin" : `a ${role}`}`); }
    catch (e: any) { toast(e.message, "error"); }
    members.reload();
  }
  async function remove(m: Member) {
    if (!confirm(`Remove ${m.name}’s access to ${tenant.name}? They won’t be able to sign in to this workspace. Their name stays on past notes and uploads.`)) return;
    try { await api(t(tenant.id, `/team/members/${m.user_id}`), { method: "DELETE" }); toast(`${m.name} no longer has access`); members.reload(); onChanged?.(); }
    catch (e: any) { toast(e.message, "error"); }
  }

  return (
    <div className="panel" style={{ marginBottom: 14 }}>
      <h2 style={{ marginBottom: 6 }}>People with a login</h2>
      <p className="muted">Everyone who can sign in to {tenant.name}. {ROLE_HELP}</p>
      <div className="table-wrap" style={{ margin: "12px 0" }}>
        <table>
          <thead><tr><th>Name</th><th>Role</th><th>Status</th><th /></tr></thead>
          <tbody>
            {(members.data ?? []).map((m) => (
              <tr key={m.user_id}>
                <td>{m.name}{m.is_me && <span className="muted"> (you)</span>}<span className="sub">{m.email}</span></td>
                <td style={{ width: 150 }}>{admin && !m.is_me && (myRole === "owner" || m.role !== "owner")
                  ? <Select value={m.role} onChange={(v) => setRole(m, v)} options={myRole === "owner" ? ROLES : ROLES.filter(([r]) => r !== "owner")} />
                  : ROLES.find(([r]) => r === m.role)?.[1] ?? m.role}</td>
                <td>{m.last_sign_in_at ? <span className="muted">Last signed in {date(m.last_sign_in_at)}</span>
                  : <span className="status s-skill-pending">Invited, hasn’t signed in</span>}</td>
                <td className="num nowrap">{admin && !m.is_me && <>
                  <button className="link-btn" onClick={() => newLink(m)} title="Links expire; this makes a fresh one">New sign-in link</button>
                  {(myRole === "owner" || m.role !== "owner") &&
                    <button className="link-btn danger-text" style={{ marginLeft: 12 }} onClick={() => remove(m)}>Remove access</button>}
                </>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {result && <InviteResult r={result} company={tenant.name} onClose={() => setResult(null)} />}

      {admin && (
        <form onSubmit={invite} id="invite">
          <h3>Invite someone</h3>
          {error && <div className="form-error" role="alert">{error}</div>}
          <div className="form-grid three">
            <Field label="Email"><input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Name"><input value={form.full_name} placeholder="Optional" onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
            <Field label="Role"><Select value={form.role} onChange={(v) => setForm({ ...form, role: v })}
                                        options={myRole === "owner" ? ROLES : ROLES.filter(([r]) => r !== "owner")} /></Field>
          </div>
          <label className="check" style={{ marginTop: 10 }}>
            <input type="checkbox" checked={form.send_email} onChange={(e) => setForm({ ...form, send_email: e.target.checked })} />
            Have Supabase email the invite (only works once you’ve set up your own email service in Supabase; otherwise you get a link to send)
          </label>
          <div className="form-foot"><button className="btn primary" disabled={busy || !form.email.trim()}>{busy ? "Inviting…" : "Invite"}</button></div>
        </form>
      )}
    </div>
  );
}

function InviteResult({ r, company, onClose }: { r: Invite & { name: string }; company: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  if (r.emailed) return (
    <div className="setup-status ok" role="status">Invite emailed to {r.email}. They’ll set a password when they open it.
      <button className="link-btn" style={{ marginLeft: "auto" }} onClick={onClose}>Close</button></div>
  );
  const first = r.name.includes("@") ? "" : ` ${r.name.split(" ")[0]}`;
  const subject = `Your login for the ${company} CRM`;
  const body = `Hi${first},\n\nI’ve given you access to our ${company} CRM. Open this link to set your password and sign in:\n\n${r.link}\n\n` +
    `The link works once and expires after a while. If it has expired, let me know and I’ll send a new one.\n`;
  return (
    <div className="invite-result" role="status">
      {r.note && <p className="warn-inline">{r.note}</p>}
      <p><strong>{r.name}</strong> now has access. Send them this personal sign-in link (it’s just for them; don’t share it):</p>
      <div className="snippet">{r.link}</div>
      <div className="actions" style={{ justifyContent: "flex-start" }}>
        <button className="btn small" onClick={async () => { try { await navigator.clipboard.writeText(r.link!); setCopied(true); } catch {} }}>
          {copied ? "Copied" : "Copy link"}</button>
        <a className="btn small" href={`mailto:${r.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`}>Open an email to {r.email}</a>
        <button className="link-btn" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}
