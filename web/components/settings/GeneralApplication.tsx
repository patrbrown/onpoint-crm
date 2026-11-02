"use client";

import { useEffect, useMemo, useState } from "react";
import { api, t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { PortalSkill, Website } from "@/lib/types";
import { Field, Select, useToast } from "../ui";

/** Settings → Website: the always-open general application and the skills applicants pick from. */
export function GeneralApplication({ general, onSaved }: { general: NonNullable<Website["general"]>; onSaved: () => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const admin = ["owner", "admin", "platform_admin"].includes(tenant.role);
  const [f, setF] = useState(general);
  useEffect(() => setF(general), [general]);
  const changed = f.title !== general.title || f.intro !== general.intro;

  async function save(patch: Partial<typeof general>) {
    try { await api(t(tenant.id, "/website/general"), { method: "PATCH", json: patch }); toast("Saved"); onSaved(); }
    catch (e: any) { toast(e.message, "error"); }
  }

  return (
    <>
      <div className="panel">
        <div className="panel-head"><h2>General application</h2>
          <label className="check"><input type="checkbox" checked={general.enabled} disabled={!admin}
                 onChange={(e) => save({ enabled: e.target.checked })} /> Show on the careers page</label>
        </div>
        <p className="muted">An always-open card on your careers page for people who don’t see the right role. They send their resume,
          contact details and skills; they appear under New applicants and are added as candidates (not to any job).</p>
        <div className="form-grid" style={{ marginTop: 10 }}>
          <Field label="Title" wide><input value={f.title} disabled={!admin} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Introduction" wide><textarea rows={3} value={f.intro} disabled={!admin} onChange={(e) => setF({ ...f, intro: e.target.value })} /></Field>
        </div>
        {admin && <div className="form-foot"><button className="btn primary" disabled={!changed || f.title.trim().length < 2}
                    onClick={() => save({ title: f.title.trim(), intro: f.intro.trim() })}>Save</button></div>}
      </div>
      <SkillsList autoListAfter={general.auto_list_after} admin={admin} onBarChange={(n) => save({ auto_list_after: n })} />
    </>
  );
}

const STATUS: Record<PortalSkill["status"], string> = { listed: "On the website", pending: "Waiting", hidden: "Hidden" };

function SkillsList({ autoListAfter, admin, onBarChange }: { autoListAfter: number; admin: boolean; onBarChange: (n: number) => void }) {
  const { tenant } = useSession();
  const toast = useToast();
  const skills = useData<PortalSkill[]>(t(tenant.id, "/portal-skills"));
  const [q, setQ] = useState("");
  const [show, setShow] = useState<"all" | PortalSkill["status"]>("all");
  const [add, setAdd] = useState({ name: "", category: "" });
  const all = skills.data ?? [];
  const categories = useMemo(() => Array.from(new Set(all.map((s) => s.category))).sort(), [all]);
  const pending = all.filter((s) => s.status === "pending").length;
  const rows = all.filter((s) => (show === "all" || s.status === show)
    && `${s.name} ${s.category}`.toLowerCase().includes(q.toLowerCase()));

  async function patch(s: PortalSkill, p: Partial<PortalSkill>) {
    try {
      const saved = await api<PortalSkill>(t(tenant.id, `/portal-skills/${s.id}`), { method: "PATCH", json: p });
      skills.setData((xs) => (xs ?? []).map((x) => (x.id === s.id ? saved : x)));
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function remove(s: PortalSkill) {
    if (!confirm(`Delete “${s.name}” from the list? Candidates who chose it keep it on their profile.`)) return;
    try { await api(t(tenant.id, `/portal-skills/${s.id}`), { method: "DELETE" }); skills.setData((xs) => (xs ?? []).filter((x) => x.id !== s.id)); }
    catch (e: any) { toast(e.message, "error"); }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api(t(tenant.id, "/portal-skills"), { method: "POST", json: { name: add.name, category: add.category.trim() || "Other" } });
      setAdd({ name: "", category: add.category }); skills.reload();
    } catch (err: any) { toast(err.message, "error"); }
  }

  return (
    <div className="panel">
      <div className="panel-head"><h2>Skills on the general application</h2>
        {pending > 0 && <button className="link-btn" onClick={() => setShow("pending")}>{pending} waiting for review</button>}</div>
      <p className="muted">Applicants pick from this list or type their own. A skill someone types is saved on their profile straight
        away, and joins the list on the website once
        {admin ? <> <select className="inline-select" aria-label="How many applicants before a new skill is listed" value={autoListAfter}
          onChange={(e) => onBarChange(Number(e.target.value))}>
          {[1, 2, 3, 5, 10].map((n) => <option key={n} value={n}>{n}</option>)}</select> </> : ` ${autoListAfter} `}
        different applicant{autoListAfter === 1 ? "" : "s"} have used it. You can list, hide or rename any skill.</p>
      <div className="toolbar" style={{ marginTop: 10 }}>
        <input className="search" type="search" placeholder="Search skills" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search skills" />
        <div style={{ width: 190 }}><Select value={show} onChange={(v) => setShow(v as any)}
          options={[["all", "All skills"], ["listed", "On the website"], ["pending", "Waiting for review"], ["hidden", "Hidden"]]} /></div>
        <span className="muted">{rows.length} of {all.length}</span>
      </div>
      <div className="table-wrap" style={{ maxHeight: 420, overflow: "auto" }}>
        <table>
          <thead><tr><th>Skill</th><th>Group</th><th className="num">Applicants</th><th>Status</th><th /></tr></thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.id}>
                <td>{admin ? <input aria-label={`Rename ${s.name}`} defaultValue={s.name} key={s.name}
                                    onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== s.name) patch(s, { name: v }); }} /> : s.name}
                  {s.added_by_applicant && <span className="sub">Added by an applicant</span>}</td>
                <td>{admin ? <input aria-label={`Group for ${s.name}`} list="skill-groups" defaultValue={s.category} key={s.category}
                                    onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== s.category) patch(s, { category: v }); }} /> : s.category}</td>
                <td className="num">{s.uses}</td>
                <td><span className={`status s-skill-${s.status}`}>{STATUS[s.status]}</span></td>
                <td className="num nowrap">{admin && <>
                  {s.status !== "listed" && <button className="link-btn" onClick={() => patch(s, { status: "listed" })}>List</button>}
                  {s.status !== "hidden" && <button className="link-btn" style={{ marginLeft: 10 }} onClick={() => patch(s, { status: "hidden" })}>Hide</button>}
                  <button className="link-btn danger-text" style={{ marginLeft: 10 }} onClick={() => remove(s)}>Delete</button></>}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="muted">No skills match.</td></tr>}
          </tbody>
        </table>
        <datalist id="skill-groups">{categories.map((c) => <option key={c} value={c} />)}</datalist>
      </div>
      {admin && (
        <form className="stage-add" onSubmit={create}>
          <input placeholder="Add a skill, e.g. Epic Phoenix" value={add.name} onChange={(e) => setAdd({ ...add, name: e.target.value })} aria-label="New skill" />
          <input placeholder="Group (optional)" list="skill-groups" value={add.category} onChange={(e) => setAdd({ ...add, category: e.target.value })}
                 aria-label="Group" style={{ maxWidth: 220 }} />
          <button className="btn small" disabled={add.name.trim().length < 2}>Add skill</button>
        </form>
      )}
    </div>
  );
}
