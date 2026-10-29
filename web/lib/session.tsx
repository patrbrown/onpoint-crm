"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "./api";
import { getSupabase } from "./supabase";
import type { Me, Tenant } from "./types";

type Session = { me: Me; tenant: Tenant; setTenant: (id: string) => void; signOut: () => Promise<void> };
const Ctx = createContext<Session | null>(null);

export function useSession(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useSession outside SessionProvider");
  return s;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<Me | null>(null);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const sb = getSupabase();
    if (sb) {
      const { data } = await sb.auth.getSession();
      if (!data.session) {
        router.replace("/login");
        return;
      }
    }
    try {
      const m = await api<Me>("/me");
      setMe(m);
      let saved: string | null = null;
      try { saved = localStorage.getItem("tenant"); } catch {}
      setTenantId(m.tenants.find((t) => t.id === saved)?.id ?? m.tenants[0]?.id ?? null);
    } catch (e: any) {
      if (e.status === 401) router.replace("/login");
      else setError(e.message);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  const setTenant = (id: string) => {
    setTenantId(id);
    try { localStorage.setItem("tenant", id); } catch {}
    router.push("/jobs");
  };
  const signOut = async () => {
    await getSupabase()?.auth.signOut();
    router.replace("/login");
  };

  if (error)
    return <div className="center-note"><h1>Can’t reach the CRM service</h1><p>{error}</p>
      <p className="muted">Check that the API is running (docker compose up) and try again.</p>
      <button className="btn" onClick={() => { setError(null); load(); }}>Try again</button></div>;
  if (!me) return <div className="center-note muted">Loading…</div>;
  const tenant = me.tenants.find((t) => t.id === tenantId);
  if (!tenant)
    return <div className="center-note"><h1>No workspace yet</h1>
      <p>Your login works, but it isn’t linked to an agency workspace. Run the setup SQL in the README, then reload.</p></div>;

  return <Ctx.Provider value={{ me, tenant, setTenant, signOut }}>{children}</Ctx.Provider>;
}
