"use client";

import { useEffect, useState } from "react";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { useToast } from "./ui";

type MailStatus = {
  configured: boolean;
  accounts: { id: string; mailbox_address: string; is_enabled: boolean; last_sync_at: string | null; last_error: string | null }[];
  signin: { user_code: string; verification_uri: string; status: "waiting" | "connected" | "failed"; error?: string } | null;
};

function ago(s: string | null) {
  if (!s) return "never";
  const mins = Math.round((Date.now() - new Date(s).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  return date(s);
}

export function OutlookConnection({ onScanned }: { onScanned: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const status = useData<MailStatus>(t(tenant.id, "/mail"));
  const [scanning, setScanning] = useState(false);
  const signin = status.data?.signin;

  // While waiting for the Microsoft sign-in to finish, check every 3 seconds.
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
      onScanned();
    } catch (e: any) { toast(e.message, "error"); }
    finally { setScanning(false); status.reload(); }
  }
  async function toggle(id: string, enabled: boolean) {
    await api(t(tenant.id, `/mail/accounts/${id}?enabled=${enabled}`), { method: "PATCH" });
    status.reload();
  }

  if (!status.data) return null;
  const s = status.data;

  if (!s.configured)
    return <div className="panel conn"><p><strong>Outlook isn’t set up on this computer yet.</strong> Add MS_CLIENT_ID and
      MS_TENANT_ID to the .env file, then restart with <code>docker compose up -d</code>.</p></div>;

  return (
    <div className="panel conn">
      {s.accounts.map((a) => (
        <div key={a.id} className="conn-row">
          <span className={`dot ${a.last_error ? "bad" : a.is_enabled ? "ok" : ""}`} aria-hidden="true" />
          <div className="conn-main">
            <strong>{a.mailbox_address}</strong>
            <span className="muted"> {a.is_enabled ? `checked ${ago(a.last_sync_at)}` : "paused"}</span>
            {a.last_error && <div className="conn-error">{a.last_error}</div>}
          </div>
          <div className="actions">
            <button className="btn small" disabled={scanning || !a.is_enabled} onClick={() => scan(a.id)}>
              {scanning ? "Checking…" : "Check now"}</button>
            <button className="btn small" onClick={() => toggle(a.id, !a.is_enabled)}>{a.is_enabled ? "Pause" : "Resume"}</button>
            {a.last_error?.includes("connect Outlook again") && <button className="btn small primary" onClick={connect}>Reconnect</button>}
          </div>
        </div>
      ))}

      {signin?.status === "waiting" ? (
        <div className="device-code">
          <p>Go to <a href={signin.verification_uri} target="_blank" rel="noreferrer">{signin.verification_uri.replace("https://", "")}</a>,
            enter this code, and sign in with your Outlook account:</p>
          <p className="code" aria-label="Sign-in code">{signin.user_code}</p>
          <p className="muted">This page updates by itself once you’ve signed in. The CRM can only read your email; it can’t
            move, flag, delete or send anything.</p>
        </div>
      ) : s.accounts.length === 0 ? (
        <div className="conn-row">
          <div className="conn-main"><strong>Connect your Outlook inbox</strong>
            <div className="muted">New email is checked automatically. Job reqs, resumes and interview feedback come here for review.</div></div>
          <button className="btn primary" onClick={connect}>Connect Outlook</button>
        </div>
      ) : null}
      {signin?.status === "failed" && <div className="form-error" style={{ marginTop: 10 }}>Sign-in didn’t finish: {signin.error}
        <button className="link-btn" style={{ marginLeft: 8 }} onClick={connect}>Try again</button></div>}
    </div>
  );
}
