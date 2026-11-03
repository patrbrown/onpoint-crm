"use client";

import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { useToast } from "./ui";

type Account = {
  id: string; mailbox_address: string; is_enabled: boolean; last_sync_at: string | null; last_error: string | null;
  is_mine: boolean; can_read: boolean; owner_name: string | null;
  shared_with?: { user_id: string; name: string; email: string }[];
};
type MailStatus = {
  configured: boolean;
  accounts: Account[];
  signin: { user_code: string; verification_uri: string; status: "waiting" | "connected" | "failed"; error?: string } | null;
};

function ago(s: string | null) {
  if (!s) return "never";
  const mins = Math.round((Date.now() - new Date(s).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  return date(s);
}

/** Your mailbox(es): connect, check, pause, and choose who else can see it. With `showOthers` (Settings), workspace
 *  admins also see that other people's mailboxes are connected; their email stays private. */
export function OutlookConnection({ onScanned, showOthers }: { onScanned?: () => void; showOthers?: boolean }) {
  const { tenant, refresh } = useSession();
  const toast = useToast();
  const status = useData<MailStatus>(t(tenant.id, "/mail"));
  const [scanning, setScanning] = useState(false);
  const signin = status.data?.signin;

  // While waiting for the Microsoft sign-in to finish, check every 3 seconds.
  useEffect(() => { if (signin?.status === "connected" && !tenant.inbox_access) refresh(); }, [signin?.status]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (signin?.status !== "waiting") return;
    const id = setInterval(status.reload, 3000);
    return () => clearInterval(id);
  }, [signin?.status, status.reload]);

  async function connect() {
    try {
      await api(t(tenant.id, "/mail/connect"), { method: "POST" });
      status.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function scan(id: string) {
    setScanning(true);
    try {
      const r = await api<any>(t(tenant.id, `/mail/accounts/${id}/scan`), { method: "POST" });
      toast(r.new ? `${r.new} new emails: ${r.queued} to review, ${r.auto_approved} saved automatically, ${r.ignored} not relevant`
        : "No new email since the last check");
      onScanned?.();
    } catch (e: any) { toast(e.message, "error"); }
    finally { setScanning(false); status.reload(); }
  }
  async function toggle(id: string, enabled: boolean) {
    try { await api(t(tenant.id, `/mail/accounts/${id}?enabled=${enabled}`), { method: "PATCH" }); }
    catch (e: any) { toast(e.message, "error"); }
    status.reload();
  }

  if (!status.data) return null;
  const s = status.data;

  if (!s.configured)
    return <div className="panel conn"><p><strong>Outlook isn’t set up on this computer yet.</strong> Add MS_CLIENT_ID and
      MS_TENANT_ID to the .env file, then restart with <code>docker compose up -d</code>.</p></div>;

  const readable = s.accounts.filter((a) => a.can_read);
  const others = s.accounts.filter((a) => !a.can_read);
  const hasOwn = s.accounts.some((a) => a.is_mine);

  return (
    <div className="panel conn">
      {readable.map((a) => (
        <div key={a.id}>
          <div className="conn-row">
            <span className={`dot ${a.last_error ? "bad" : a.is_enabled ? "ok" : ""}`} aria-hidden="true" />
            <div className="conn-main">
              <strong>{a.mailbox_address}</strong>
              <span className="muted"> {a.is_enabled ? `checked ${ago(a.last_sync_at)}` : "paused"}
                {!a.is_mine && a.owner_name ? `, shared with you by ${a.owner_name}` : ""}</span>
              {a.last_error && <div className="conn-error">{a.last_error}</div>}
            </div>
            <div className="actions">
              <button className="btn small" disabled={scanning || !a.is_enabled} onClick={() => scan(a.id)}>
                {scanning ? "Checking…" : "Check now"}</button>
              {a.is_mine && <button className="btn small" onClick={() => toggle(a.id, !a.is_enabled)}>{a.is_enabled ? "Pause" : "Resume"}</button>}
              {a.is_mine && a.last_error?.includes("connect Outlook again") && <button className="btn small primary" onClick={connect}>Reconnect</button>}
            </div>
          </div>
          {a.is_mine && <Sharing account={a} onChanged={status.reload} />}
        </div>
      ))}
      {showOthers && others.length > 0 && (
        <div className="others">
          {others.map((a) => (
            <p key={a.id} className="muted">{`${a.mailbox_address}, connected by ${a.owner_name ?? "someone else"}. Private: only they, and people they share it with, can see its email.`}</p>
          ))}
        </div>
      )}

      {signin?.status === "waiting" ? (
        <div className="device-code">
          <p>Go to <a href={signin.verification_uri} target="_blank" rel="noreferrer">{signin.verification_uri.replace("https://", "")}</a>,
            enter this code, and sign in with your Outlook account:</p>
          <p className="code" aria-label="Sign-in code">{signin.user_code}</p>
          <p className="muted">This page updates by itself once you’ve signed in. The CRM can only read your email; it can’t
            move, flag, delete or send anything.</p>
        </div>
      ) : !hasOwn ? (
        <div className="conn-row">
          <div className="conn-main"><strong>Connect your Outlook inbox</strong>
            <div className="muted">New email is checked automatically, and job reqs, resumes and interview feedback come in for review.
              Your mailbox stays private to you unless you share it.</div></div>
          <button className="btn primary" onClick={connect}>Connect Outlook</button>
        </div>
      ) : null}
      {signin?.status === "failed" && <div className="form-error" style={{ marginTop: 10 }}>Sign-in didn’t finish: {signin.error}
        <button className="link-btn" style={{ marginLeft: 8 }} onClick={connect}>Try again</button></div>}
    </div>
  );
}

/** The mailbox owner chooses who else in the workspace can see it. */
function Sharing({ account, onChanged }: { account: Account; onChanged: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [pick, setPick] = useState("");
  const people = useData<{ user_id: string; name: string; email: string; role: string }[]>(open ? t(tenant.id, "/mail/people") : null);
  const shared = account.shared_with ?? [];
  const candidates = (people.data ?? []).filter((p) => !shared.some((x) => x.user_id === p.user_id));

  async function add() {
    try { await api(t(tenant.id, `/mail/accounts/${account.id}/access`), { method: "POST", json: { user_id: pick } }); setPick(""); onChanged(); }
    catch (e: any) { toast(e.message, "error"); }
  }
  async function remove(userId: string, name: string) {
    if (!confirm(`Stop sharing ${account.mailbox_address} with ${name}?`)) return;
    try { await api(t(tenant.id, `/mail/accounts/${account.id}/access/${userId}`), { method: "DELETE" }); onChanged(); }
    catch (e: any) { toast(e.message, "error"); }
  }
  return (
    <div className="sharing">
      <span className="muted">{shared.length ? "Also visible to: " : "Private: only you can see this inbox."}</span>
      {shared.map((x) => (
        <span key={x.user_id} className="tag removable">{x.name}
          <button type="button" aria-label={`Stop sharing with ${x.name}`} onClick={() => remove(x.user_id, x.name)}>×</button></span>
      ))}
      {!open ? <button className="link-btn" onClick={() => setOpen(true)}>{shared.length ? "Share with someone else" : "Share with someone"}</button> : (
        <span className="share-add">
          {people.data && candidates.length === 0 ? <span className="muted">No one else in this workspace has a login yet.</span> : <>
            <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Person to share with">
              <option value="">Choose a person</option>
              {candidates.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}
            </select>
            <button className="btn small" disabled={!pick} onClick={add}>Share</button></>}
          <button className="link-btn" onClick={() => { setOpen(false); setPick(""); }}>Done</button>
        </span>
      )}
    </div>
  );
}
