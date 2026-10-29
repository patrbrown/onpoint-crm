"use client";

import { useState } from "react";
import { InboxReview, Match, TYPE_LABEL } from "@/components/InboxReview";
import { OutlookConnection } from "@/components/OutlookConnection";
import { Drawer, Empty, Select, useToast } from "@/components/ui";
import { api, t } from "@/lib/api";
import { date } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Item = {
  id: string; item_type: string; status: string; confidence: string | null; extracted: Record<string, any>;
  suggested_matches: Match[]; subject: string | null; from_address: string | null; from_name: string | null;
  received_at: string | null; created_at: string; attachment_count: number; created_entity_type: string | null; created_entity_id: string | null;
};
type List = { items: Item[]; counts: Record<string, number>; ignored_emails: number };

function summary(i: Item) {
  const x = i.extracted;
  if (i.item_type === "job_requisition") return [x.title, x.client_name].filter(Boolean).join(", ");
  if (i.item_type === "resume") return [[x.first_name, x.last_name].filter(Boolean).join(" "), x.current_title].filter(Boolean).join(", ");
  return [x.candidate_name, x.job_title].filter(Boolean).join(", ");
}
const ENTITY_PATH: Record<string, string> = { job: "/jobs/", candidate: "/candidates/" };

export default function InboxPage() {
  const { tenant } = useSession();
  const [tab, setTab] = useState<"pending" | "done" | "ignored">("pending");
  const list = useData<List>(t(tenant.id, `/inbox?status=${tab === "ignored" ? "pending" : tab}`));
  const [open, setOpen] = useState<string | null>(null);
  const [type, setType] = useState("");
  const items = (list.data?.items ?? []).filter((i) => !type || i.item_type === type);
  const pendingCount = list.data?.counts.pending ?? 0;
  const doneCount = ["approved", "auto_approved", "rejected"].reduce((n, k) => n + (list.data?.counts[k] ?? 0), 0);

  return (
    <>
      <div className="page-head"><div><h1>Email inbox</h1>
        <p>Job requisitions, resumes and interview feedback the assistant found in your Outlook.</p></div></div>
      <OutlookConnection onScanned={list.reload} />

      <div className="tabs" role="tablist" style={{ marginTop: 18 }}>
        <button role="tab" aria-selected={tab === "pending"} onClick={() => setTab("pending")}>To review ({pendingCount})</button>
        <button role="tab" aria-selected={tab === "done"} onClick={() => setTab("done")}>Done ({doneCount})</button>
        <button role="tab" aria-selected={tab === "ignored"} onClick={() => setTab("ignored")}>Not recruiting email ({list.data?.ignored_emails ?? 0})</button>
      </div>

      {tab === "ignored" ? <Ignored onChanged={() => { list.reload(); setTab("pending"); }} /> : (
        <>
          <div className="toolbar">
            <Select value={type} onChange={setType} placeholder="All types" options={[["job_requisition", "Job requisitions"],
              ["resume", "Resumes"], ["interview_feedback", "Interview feedback"]]} />
          </div>
          {items.length === 0 ? (
            <Empty title={tab === "pending" ? "Nothing to review" : "Nothing here yet"}>
              <p>{tab === "pending" ? "New job reqs, resumes and interview feedback from your inbox will appear here." : "Items you approve or reject are listed here."}</p>
            </Empty>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Type</th><th>Found</th><th>Email</th><th className="num">Sure</th><th>{tab === "done" ? "Outcome" : "Received"}</th></tr></thead>
                <tbody>
                  {items.map((i) => (
                    <tr key={i.id} className="clickable" onClick={() => setOpen(i.id)}>
                      <td><span className={`type t-${i.item_type}`}>{TYPE_LABEL[i.item_type]}</span></td>
                      <td><strong>{summary(i) || "(no details)"}</strong>
                        {i.suggested_matches?.some((m) => m.reason === "same email" || m.reason === "same req number") &&
                          <span className="sub">Possibly already in the CRM</span>}</td>
                      <td>{i.subject}<span className="sub">{i.from_name || i.from_address}{i.attachment_count ? `, ${i.attachment_count} attachment${i.attachment_count > 1 ? "s" : ""}` : ""}</span></td>
                      <td className="num">{i.confidence ? `${Math.round(Number(i.confidence) * 100)}%` : ""}</td>
                      <td className="muted">{tab === "done" ? (
                        i.created_entity_id && ENTITY_PATH[i.created_entity_type ?? ""]
                          ? <a href={ENTITY_PATH[i.created_entity_type!] + i.created_entity_id} onClick={(e) => e.stopPropagation()}>
                              {i.status === "auto_approved" ? "Saved automatically" : "Saved"}</a>
                          : i.status === "rejected" ? "Rejected" : i.status === "auto_approved" ? "Saved automatically" : "Saved"
                      ) : date(i.received_at ?? i.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
      <Drawer title="Review" open={!!open} onClose={() => setOpen(null)}>
        {open && <InboxReview id={open} onDone={() => { setOpen(null); list.reload(); }} />}
      </Drawer>
    </>
  );
}

function Ignored({ onChanged }: { onChanged: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const rows = useData<any[]>(t(tenant.id, "/inbox/ignored"));
  async function fix(id: string, correct: string) {
    if (!correct) return;
    try {
      await api(t(tenant.id, `/inbox/emails/${id}/reprocess`), { method: "POST", json: { reason: "wrong_type", correct_type: correct } });
      toast(`Re-read as ${TYPE_LABEL[correct].toLowerCase()}; it’s in To review`);
      onChanged();
    } catch (e: any) { toast(e.message, "error"); }
  }
  if (!rows.data?.length) return <Empty title="No skipped email"><p>Emails the assistant decides aren’t recruiting-related are listed here so you can catch anything it missed.</p></Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Email</th><th>Assistant’s call</th><th>Received</th><th>Actually a…</th></tr></thead>
        <tbody>
          {rows.data.map((e) => (
            <tr key={e.id}>
              <td>{e.subject}<span className="sub">{e.from_name || e.from_address}</span></td>
              <td>{e.error ? <span style={{ color: "var(--red)" }}>Couldn’t read: {e.error}</span> : TYPE_LABEL[e.classification] ?? e.classification}</td>
              <td className="muted">{date(e.received_at)}</td>
              <td style={{ width: 190 }}>
                <Select value="" onChange={(v) => fix(e.id, v)} placeholder="Correct it…" options={[["job_requisition", "Job requisition"],
                  ["resume", "Resume"], ["interview_feedback", "Interview feedback"]]} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
