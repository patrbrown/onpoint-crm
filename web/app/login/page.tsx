"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSupabase } from "@/lib/supabase";

export default function Login() {
  const router = useRouter();
  const sb = getSupabase();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!sb) router.replace("/jobs"); }, [sb, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!sb) return;
    setBusy(true);
    setError(null);
    const { error } = await sb.auth.signInWithPassword({ email, password });
    setBusy(false);
    if (error) setError(error.message === "Invalid login credentials" ? "Email or password is incorrect." : error.message);
    else router.replace("/jobs");
  }

  async function reset() {
    if (!sb || !email) { setError("Enter your email first, then choose “Forgot password”."); return; }
    await sb.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin + "/login" });
    setError(null);
    alert("If that email has an account, a reset link is on its way.");
  }

  return (
    <div className="login">
      <form onSubmit={submit}>
        <div className="brand"><span className="brand-mark" aria-hidden="true"><span /></span>
          <span className="brand-name">OnPoint CRM</span></div>
        <h1>Sign in</h1>
        {error && <div className="form-error" role="alert">{error}</div>}
        <label className="field"><span className="field-label">Email</span>
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label className="field"><span className="field-label">Password</span>
          <input type="password" autoComplete="current-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} /></label>
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <button type="button" className="link-btn" onClick={reset}>Forgot password</button>
      </form>
    </div>
  );
}
