"use client";

import { useCallback, useEffect, useState } from "react";
import { api, t } from "./api";

const EVENT = "crm:applicants-changed";
/** Tell the sidebar count to refresh (after marking applicants as seen). */
export const applicantsChanged = () => window.dispatchEvent(new Event(EVENT));

/** Number of website applicants nobody has opened yet. Refreshes every minute and when you come back to the tab. */
export function useNewApplicantCount(tenantId: string) {
  const [n, setN] = useState(0);
  const load = useCallback(async () => {
    try { setN((await api<{ new: number }>(t(tenantId, "/applicants/count"))).new); } catch { /* keep the last count */ }
  }, [tenantId]);
  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    const focus = () => { if (document.visibilityState === "visible") load(); };
    window.addEventListener(EVENT, load);
    document.addEventListener("visibilitychange", focus);
    return () => { clearInterval(timer); window.removeEventListener(EVENT, load); document.removeEventListener("visibilitychange", focus); };
  }, [load]);
  return n;
}
