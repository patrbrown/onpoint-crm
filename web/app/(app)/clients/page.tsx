"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ClientForm } from "@/components/ClientForms";
import { Drawer, Empty, Status } from "@/components/ui";
import { t } from "@/lib/api";
import { label, place } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Client, Job } from "@/lib/types";

export default function ClientsPage() {
  const { tenant } = useSession();
  const router = useRouter();
  const clients = useData<Client[]>(t(tenant.id, "/clients?limit=1000"));
  const jobs = useData<Job[]>(t(tenant.id, "/jobs?status=open&limit=1000"));
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const openJobs = (id: string) => (jobs.data ?? []).filter((j) => j.client_id === id).length;
  const rows = (clients.data ?? []).filter((c) => !q || `${c.name} ${c.industry ?? ""} ${place(c)}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <>
      <div className="page-head">
        <div><h1>Clients</h1><p>{clients.data?.length ?? 0} clients</p></div>
        <div className="actions">
          <input className="search" type="search" placeholder="Search clients" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search clients" />
          <button className="btn primary" onClick={() => setCreating(true)}>New client</button>
        </div>
      </div>
      {clients.data && clients.data.length === 0 ? (
        <Empty title="No clients yet"><p>Add the organizations you recruit for, then their hiring managers as contacts.</p>
          <button className="btn primary" onClick={() => setCreating(true)}>New client</button></Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Client</th><th>Location</th><th>Fee terms</th><th className="num">Open jobs</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => router.push(`/clients/${c.id}`)}>
                  <td><a href={`/clients/${c.id}`} onClick={(e) => e.preventDefault()}>{c.name}</a><span className="sub">{c.industry}</span></td>
                  <td>{place(c)}</td>
                  <td>{c.fee_terms}</td>
                  <td className="num">{openJobs(c.id) || ""}</td>
                  <td><Status value={c.status} text={label(c.status)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Drawer title="New client" open={creating} onClose={() => setCreating(false)}>
        <ClientForm onCancel={() => setCreating(false)} onSaved={(c) => router.push(`/clients/${c.id}`)} />
      </Drawer>
    </>
  );
}
