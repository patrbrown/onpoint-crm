"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ClientForm, ContactForm } from "@/components/ClientForms";
import { Drawer, Status, useToast } from "@/components/ui";
import { api, t } from "@/lib/api";
import { compensation, fullName, label, place } from "@/lib/format";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Client, Contact, Job } from "@/lib/types";

export default function ClientPage() {
  const { id } = useParams<{ id: string }>();
  const { tenant } = useSession();
  const router = useRouter();
  const toast = useToast();
  const client = useData<Client>(t(tenant.id, `/clients/${id}`));
  const contacts = useData<Contact[]>(t(tenant.id, `/contacts?client_id=${id}`));
  const jobs = useData<Job[]>(t(tenant.id, `/jobs?client_id=${id}&limit=1000`));
  const [drawer, setDrawer] = useState<"none" | "edit" | "contact">("none");
  const [contact, setContact] = useState<Contact | undefined>();

  if (client.error) return <div className="form-error">{client.error}</div>;
  if (!client.data) return <p className="muted">Loading…</p>;
  const c = client.data;

  async function remove() {
    if (!confirm(`Delete ${c.name}? Its contacts are deleted; its jobs stay but lose the client link.`)) return;
    await api(t(tenant.id, `/clients/${id}`), { method: "DELETE" });
    toast("Client deleted");
    router.push("/clients");
  }

  return (
    <>
      <Link href="/clients" className="crumb">Clients</Link>
      <div className="page-head">
        <div><h1>{c.name}</h1><p>{[c.industry, place(c)].filter(Boolean).join(", ")}</p></div>
        <div className="actions">
          <Status value={c.status} text={label(c.status)} />
          <button className="btn" onClick={() => setDrawer("edit")}>Edit</button>
          <button className="btn primary" onClick={() => { setContact(undefined); setDrawer("contact"); }}>Add contact</button>
        </div>
      </div>
      <div className="two-col">
        <div>
          <div className="panel">
            <h2 style={{ marginBottom: 10 }}>Contacts</h2>
            {contacts.data?.length ? (
              <table><tbody>
                {contacts.data.map((p) => (
                  <tr key={p.id}>
                    <td><button className="link-btn" onClick={() => { setContact(p); setDrawer("contact"); }}>{fullName(p)}</button>
                      <span className="sub">{[p.title, p.is_hiring_manager && "Hiring manager", p.is_primary && "Primary"].filter(Boolean).join(", ")}</span></td>
                    <td>{p.email && <a href={`mailto:${p.email}`}>{p.email}</a>}<span className="sub">{[p.phone, p.mobile].filter(Boolean).join(", ")}</span></td>
                  </tr>
                ))}
              </tbody></table>
            ) : <p className="muted">No contacts yet.</p>}
          </div>
          <div className="panel">
            <h2 style={{ marginBottom: 10 }}>Jobs</h2>
            {jobs.data?.length ? (
              <table><tbody>
                {jobs.data.map((j) => (
                  <tr key={j.id}><td><Link href={`/jobs/${j.id}`}>{j.title}</Link><span className="sub">{compensation(j)}</span></td>
                    <td className="num"><Status value={j.status} text={label(j.status)} /></td></tr>
                ))}
              </tbody></table>
            ) : <p className="muted">No jobs for this client yet.</p>}
          </div>
        </div>
        <div>
          <div className="panel">
            <dl className="facts">
              <dt>Website</dt><dd>{c.website ? <a href={c.website.startsWith("http") ? c.website : `https://${c.website}`} target="_blank" rel="noreferrer">{c.website}</a> : "None"}</dd>
              <dt>Fee terms</dt><dd>{c.fee_terms || "Not set"}</dd>
            </dl>
            {c.notes && <p className="prose" style={{ marginTop: 10 }}>{c.notes}</p>}
          </div>
          <button className="btn danger small" style={{ marginTop: 14 }} onClick={remove}>Delete client</button>
        </div>
      </div>
      <Drawer title="Edit client" open={drawer === "edit"} onClose={() => setDrawer("none")}>
        <ClientForm client={c} onCancel={() => setDrawer("none")} onSaved={() => { setDrawer("none"); client.reload(); }} />
      </Drawer>
      <Drawer title={contact ? "Edit contact" : "Add contact"} open={drawer === "contact"} onClose={() => setDrawer("none")}>
        <ContactForm key={contact?.id ?? "new"} clientId={c.id} contact={contact} onCancel={() => setDrawer("none")}
                     onSaved={() => { setDrawer("none"); contacts.reload(); }} />
      </Drawer>
    </>
  );
}
