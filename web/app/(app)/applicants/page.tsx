"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Empty, Tags, useToast } from "@/components/ui";
import { api, t } from "@/lib/api";
import { applicantsChanged } from "@/lib/applicants";
import { dateTime, fullName } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Applicant } from "@/lib/types";

/** People who applied on the website careers page. "New" until someone opens them. */
export default function ApplicantsPage() {
  const { tenant } = useSession();
  const router = useRouter();
  const toast = useToast();
  const [show, setShow] = useState<"new" | "all">("new");
  const list = useData<Applicant[]>(t(tenant.id, `/applicants${show === "new" ? "?only_new=true" : ""}`));
  const rows = list.data ?? [];

  async function open(a: Applicant) {
    if (!a.seen_at) {
      try { await api(t(tenant.id, `/applicants/${a.id}/seen`), { method: "POST" }); applicantsChanged(); } catch { /* still open it */ }
    }
    router.push(`/candidates/${a.candidate_id}`);
  }
  async function setSeen(a: Applicant, seen: boolean) {
    try {
      await api(t(tenant.id, `/applicants/${a.id}/seen?seen=${seen}`), { method: "POST" });
      applicantsChanged(); list.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function allSeen() {
    try {
      const r = await api<{ updated: number }>(t(tenant.id, "/applicants/seen-all"), { method: "POST" });
      toast(`${r.updated} marked as seen`); applicantsChanged(); list.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>New applicants</h1><p>People who applied on your website’s careers page, to a posted job or through the general application. Everyone is added as a candidate; job applicants also go into the job’s first stage.</p></div>
        <div className="actions">
          {show === "new" && rows.length > 0 && <button className="btn" onClick={allSeen}>Mark all as seen</button>}
        </div>
      </div>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={show === "new"} onClick={() => setShow("new")}>New</button>
        <button role="tab" aria-selected={show === "all"} onClick={() => setShow("all")}>All website applicants</button>
      </div>
      {list.error && <div className="form-error">{list.error}</div>}
      {list.data && rows.length === 0 ? (
        <Empty title={show === "new" ? "No new applicants" : "No one has applied on the website yet"}>
          <p>{show === "new" ? "You’re all caught up." : <>Post a job to your website from the job’s page, then people can apply on your careers page. Set-up is in <Link href="/settings#website">Settings → Website</Link>.</>}</p>
        </Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Applicant</th><th>Applied for</th><th>Applied</th><th>Contact</th><th>Stage</th><th /></tr></thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className={`clickable${a.seen_at ? "" : " unseen"}`} onClick={() => open(a)}>
                  <td>{!a.seen_at && <span className="new-dot" aria-label="New" />}
                    <a href={`/candidates/${a.candidate_id}`} onClick={(e) => e.preventDefault()}>{fullName(a)}</a>
                    <span className="sub">{a.reading_resume ? "Reading resume…" : [a.current_title, a.location].filter(Boolean).join(", ")}</span></td>
                  <td>{a.kind === "general"
                    ? <span className="general-label">General application</span>
                    : <Link href={`/jobs/${a.job_id}`} onClick={(e) => e.stopPropagation()}>{a.job_title}</Link>}
                    {(a.skills ?? []).length > 0 && <span className="sub"><Tags items={a.skills!.slice(0, 6)} />{a.skills!.length > 6 ? ` +${a.skills!.length - 6}` : ""}</span>}</td>
                  <td className="muted">{dateTime(a.applied_at)}</td>
                  <td>{a.email}<span className="sub">{a.phone}</span></td>
                  <td>{a.kind === "general" ? <span className="muted">Not on a job</span> : a.stage_name}</td>
                  <td className="num">
                    <button className="link-btn" onClick={(e) => { e.stopPropagation(); setSeen(a, !a.seen_at); }}>
                      {a.seen_at ? "Mark as new" : "Mark as seen"}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
