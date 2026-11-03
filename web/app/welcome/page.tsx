"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";

/** Where invite and password-reset links land: the link signs the person in, then they choose a password. */
export default function Welcome() {
  const router = useRouter();
  const sb = getSupabase();
  const [state, setState] = useState<"checking" | "ready" | "expired">("checking");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!sb) { router.replace("/jobs"); return; }
    const hash = new URLSearchParams(window.location.hash.slice(1));
    if (hash.get("error")) { setState("expired"); return; }
    let done = false;
    const use = (session: any) => {
      if (done || !session) return;
      done = true;
      setEmail(session.user.email ?? "");
      setName(session.user.user_metadata?.full_name ?? "");
      setState("ready");
      history.replaceState(null, "", "/welcome");   // don't leave the one-time token in the address bar
    };
    const { data: sub } = sb.auth.onAuthStateChange((_e, session) => use(session));
    sb.auth.getSession().then(({ data }) => use(data.session));
    const timer = setTimeout(() => { if (!done) setState("expired"); }, 6000);
    return () => { sub.subscription.unsubscribe(); clearTimeout(timer); };
  }, [sb, router]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (password.length < 8) { setError("Use at least 8 characters."); return; }
    if (password !== confirm) { setError("The two passwords don’t match."); return; }
    setBusy(true); setError(null);
    const { error } = await sb!.auth.updateUser({ password, data: name.trim() ? { full_name: name.trim() } : undefined });
    setBusy(false);
    if (error) setError(error.message);
    else router.replace("/jobs");
  }

  return (
    <div className="login">
      <form onSubmit={save}>
        <div className="brand"><span className="brand-mark" aria-hidden="true"><span /></span>
          <span className="brand-name">OnPoint CRM</span></div>
        {state === "checking" && <p className="muted">Signing you in…</p>}
        {state === "expired" && <>
          <h1>This link has expired</h1>
          <p className="muted">Sign-in links work once and only for a limited time. Ask the person who invited you for a new one, or
            use “Forgot password” on the sign-in page.</p>
          <a className="btn" href="/login">Go to sign in</a>
        </>}
        {state === "ready" && <>
          <h1>Welcome</h1>
          <p className="muted">Choose a password for {email}. You’ll use it to sign in from now on.</p>
          {error && <div className="form-error" role="alert">{error}</div>}
          <label className="field"><span className="field-label">Your name</span>
            <input autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field"><span className="field-label">New password</span>
            <input type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <label className="field"><span className="field-label">Type it again</span>
            <input type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
          <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save and continue"}</button>
        </>}
      </form>
    </div>
  );
}
