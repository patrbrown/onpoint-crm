"use client";

import { useState } from "react";
import { api, t } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { Client, Contact } from "@/lib/types";
import { clean, Field, Select, useToast } from "./ui";

function useForm<T extends Record<string, any>>(initial: T) {
  const [f, setF] = useState(initial);
  const on = (k: keyof T) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return { f, setF, on };
}

const str = (v: any) => (v === null || v === undefined ? "" : String(v));

export type ContactDraft = { first_name: string; last_name: string; title: string; email: string; phone: string; is_hiring_manager: boolean };
export const emptyContact = (): ContactDraft => ({ first_name: "", last_name: "", title: "", email: "", phone: "", is_hiring_manager: true });
const filled = (c: ContactDraft) => [c.first_name, c.last_name, c.email, c.phone, c.title].some((v) => v.trim());

/** Several contacts entered at once, one row each. Empty rows are ignored. */
export function ContactRows({ rows, onChange }: { rows: ContactDraft[]; onChange: (r: ContactDraft[]) => void }) {
  const set = (i: number, patch: Partial<ContactDraft>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="contact-rows">
      {rows.map((r, i) => (
        <fieldset key={i} className="contact-row">
          <legend className="sr-only">Contact {i + 1}</legend>
          <input aria-label="First name" placeholder="First name" value={r.first_name} onChange={(e) => set(i, { first_name: e.target.value })} />
          <input aria-label="Last name" placeholder="Last name" value={r.last_name} onChange={(e) => set(i, { last_name: e.target.value })} />
          <input aria-label="Title" placeholder="Title" value={r.title} onChange={(e) => set(i, { title: e.target.value })} />
          <button type="button" className="icon-btn" aria-label={`Remove contact ${i + 1}`} disabled={rows.length === 1}
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button>
          <input aria-label="Email" type="email" placeholder="Email" value={r.email} onChange={(e) => set(i, { email: e.target.value })} />
          <input aria-label="Phone" type="tel" placeholder="Phone" value={r.phone} onChange={(e) => set(i, { phone: e.target.value })} />
          <label className="check" title="Hiring manager"><input type="checkbox" checked={r.is_hiring_manager}
            onChange={(e) => set(i, { is_hiring_manager: e.target.checked })} /> Hiring manager</label>
        </fieldset>
      ))}
      <button type="button" className="link-btn" onClick={() => onChange([...rows, emptyContact()])}>Add another contact</button>
    </div>
  );
}

/** Saves the filled-in rows for a client. Returns how many were saved. */
export async function saveContacts(tenantId: string, clientId: string, rows: ContactDraft[]): Promise<number> {
  const list = rows.filter(filled);
  for (const r of list) if (!r.first_name.trim()) throw new Error("Each contact needs a first name");
  if (!list.length) return 0;
  await api(t(tenantId, `/clients/${clientId}/contacts`), { method: "POST", json: list.map((r) => clean({ ...r, first_name: r.first_name.trim() })) });
  return list.length;
}

export function ClientForm({ client, onSaved, onCancel }: { client?: Client; onSaved: (c: Client) => void; onCancel: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const { f, setF, on } = useForm({
    name: str(client?.name), industry: str(client?.industry ?? "Healthcare"), website: str(client?.website),
    city: str(client?.city), region: str(client?.region), country: str(client?.country ?? "Canada"),
    fee_terms: str(client?.fee_terms), status: client?.status ?? "active", notes: str(client?.notes),
  });
  const [error, setError] = useState<string | null>(null);
  const [contacts, setContacts] = useState<ContactDraft[]>([emptyContact()]);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!client && contacts.some((r) => filled(r) && !r.first_name.trim())) { setError("Each contact needs a first name"); return; }
    let saved: Client;
    try {
      saved = await api<Client>(t(tenant.id, client ? `/clients/${client.id}` : "/clients"),
        { method: client ? "PATCH" : "POST", json: clean(f) });
    } catch (err: any) { setError(err.message); return; }
    if (!client) {
      try {
        const n = await saveContacts(tenant.id, saved.id, contacts);
        toast(n ? `Client added with ${n} contact${n > 1 ? "s" : ""}` : "Client added");
      } catch (err: any) {
        toast(`Client added, but the contacts weren't saved: ${err.message}. Add them from the client page.`, "error");
      }
    } else toast("Client saved");
    onSaved(saved);
  }
  return (
    <form onSubmit={submit}>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="form-grid">
        <Field label="Client name" wide><input required value={f.name} onChange={on("name")} /></Field>
        <Field label="Industry"><input value={f.industry} onChange={on("industry")} /></Field>
        <Field label="Website"><input value={f.website} onChange={on("website")} /></Field>
        <Field label="City"><input value={f.city} onChange={on("city")} /></Field>
        <Field label="Province or state"><input value={f.region} onChange={on("region")} /></Field>
        <Field label="Country"><input value={f.country} onChange={on("country")} /></Field>
        <Field label="Status"><Select value={f.status} onChange={(v) => setF({ ...f, status: v })}
          options={[["prospect", "Prospect"], ["active", "Active"], ["inactive", "Inactive"]]} /></Field>
        <Field label="Fee terms" hint="e.g. 20% of first-year salary, 90-day guarantee" wide>
          <input value={f.fee_terms} onChange={on("fee_terms")} /></Field>
        <Field label="Notes" wide><textarea value={f.notes} onChange={on("notes")} /></Field>
      </div>
      {!client && <><h3 style={{ margin: "18px 0 8px" }}>Contacts</h3><ContactRows rows={contacts} onChange={setContacts} /></>}
      <div className="form-foot">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary">{client ? "Save client" : "Add client"}</button>
      </div>
    </form>
  );
}

export function ContactForm({ clientId, contact, onSaved, onCancel }: {
  clientId: string; contact?: Contact; onSaved: () => void; onCancel: () => void;
}) {
  const { tenant } = useSession();
  const toast = useToast();
  const { f, setF, on } = useForm({
    first_name: str(contact?.first_name), last_name: str(contact?.last_name), title: str(contact?.title),
    email: str(contact?.email), phone: str(contact?.phone), mobile: str(contact?.mobile),
    linkedin_url: str(contact?.linkedin_url), notes: str(contact?.notes),
    is_hiring_manager: contact?.is_hiring_manager ?? true, is_primary: contact?.is_primary ?? false,
  });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const payload: Record<string, any> = { ...clean(f), is_hiring_manager: f.is_hiring_manager, is_primary: f.is_primary };
    if (!contact) payload.client_id = clientId;
    try {
      await api(t(tenant.id, contact ? `/contacts/${contact.id}` : "/contacts"), { method: contact ? "PATCH" : "POST", json: payload });
      toast(contact ? "Contact saved" : "Contact added");
      onSaved();
    } catch (err: any) { setError(err.message); }
  }
  async function remove() {
    if (!contact || !confirm("Delete this contact?")) return;
    await api(t(tenant.id, `/contacts/${contact.id}`), { method: "DELETE" });
    onSaved();
  }
  return (
    <form onSubmit={submit}>
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="form-grid">
        <Field label="First name"><input required value={f.first_name} onChange={on("first_name")} /></Field>
        <Field label="Last name"><input value={f.last_name} onChange={on("last_name")} /></Field>
        <Field label="Title" wide><input value={f.title} onChange={on("title")} placeholder="Director, Clinical Applications" /></Field>
        <Field label="Email"><input type="email" value={f.email} onChange={on("email")} /></Field>
        <Field label="Work phone"><input type="tel" value={f.phone} onChange={on("phone")} /></Field>
        <Field label="Mobile"><input type="tel" value={f.mobile} onChange={on("mobile")} /></Field>
        <Field label="LinkedIn"><input type="url" value={f.linkedin_url} onChange={on("linkedin_url")} /></Field>
        <label className="check field"><input type="checkbox" checked={f.is_hiring_manager}
          onChange={(e) => setF({ ...f, is_hiring_manager: e.target.checked })} /> Hiring manager</label>
        <label className="check field"><input type="checkbox" checked={f.is_primary}
          onChange={(e) => setF({ ...f, is_primary: e.target.checked })} /> Primary contact</label>
        <Field label="Notes" wide><textarea value={f.notes} onChange={on("notes")} /></Field>
      </div>
      <div className="form-foot">
        {contact && <button type="button" className="btn danger" style={{ marginRight: "auto" }} onClick={remove}>Delete</button>}
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary">{contact ? "Save contact" : "Add contact"}</button>
      </div>
    </form>
  );
}

/** Add several contacts to an existing client. */
export function AddContacts({ clientId, onSaved, onCancel }: { clientId: string; onSaved: () => void; onCancel: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const [rows, setRows] = useState<ContactDraft[]>([emptyContact(), emptyContact()]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const n = await saveContacts(tenant.id, clientId, rows);
      if (!n) { setError("Fill in at least one contact"); return; }
      toast(`${n} contact${n > 1 ? "s" : ""} added`);
      onSaved();
    } catch (err: any) { setError(err.message); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit}>
      {error && <div className="form-error" role="alert">{error}</div>}
      <p className="muted" style={{ marginBottom: 10 }}>Add as many as you like; empty rows are skipped. Open a contact afterwards to add notes or LinkedIn.</p>
      <ContactRows rows={rows} onChange={setRows} />
      <div className="form-foot">
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save contacts"}</button>
      </div>
    </form>
  );
}
