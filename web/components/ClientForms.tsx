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

export function ClientForm({ client, onSaved, onCancel }: { client?: Client; onSaved: (c: Client) => void; onCancel: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const { f, setF, on } = useForm({
    name: str(client?.name), industry: str(client?.industry ?? "Healthcare"), website: str(client?.website),
    city: str(client?.city), region: str(client?.region), country: str(client?.country ?? "Canada"),
    fee_terms: str(client?.fee_terms), status: client?.status ?? "active", notes: str(client?.notes),
  });
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const saved = await api<Client>(t(tenant.id, client ? `/clients/${client.id}` : "/clients"),
        { method: client ? "PATCH" : "POST", json: clean(f) });
      toast(client ? "Client saved" : "Client added");
      onSaved(saved);
    } catch (err: any) { setError(err.message); }
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
