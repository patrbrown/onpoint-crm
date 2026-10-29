"use client";

import { api, t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { SavedView } from "@/lib/types";
import { useToast } from "./ui";

/** Saved filter/layout presets for a list page. `current` is the page's filter state. */
export function SavedViews<C extends Record<string, any>>({ entity, current, layout, onApply }: {
  entity: string; current: C; layout: string; onApply: (config: C, layout: string) => void;
}) {
  const { tenant } = useSession();
  const toast = useToast();
  const views = useData<SavedView[]>(t(tenant.id, `/views?entity=${entity}`));
  const same = (v: SavedView) => JSON.stringify(v.config) === JSON.stringify(current) && v.layout === layout;

  async function save() {
    const name = prompt("Name this view (for example “Epic analysts – BC”)");
    if (!name) return;
    const shared = confirm("Share this view with everyone in the workspace?\nOK = shared, Cancel = just for me");
    try {
      await api(t(tenant.id, "/views"), { method: "POST", json: { entity, name, layout, config: current, shared } });
      toast(`Saved view “${name}”`);
      views.reload();
    } catch (e: any) { toast(e.message, "error"); }
  }
  async function remove(v: SavedView) {
    if (!confirm(`Delete the view “${v.name}”?`)) return;
    await api(t(tenant.id, `/views/${v.id}`), { method: "DELETE" });
    views.reload();
  }

  return (
    <div className="views">
      {(views.data ?? []).map((v) => (
        <span key={v.id} style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
          <button className="view-chip" aria-pressed={same(v)} onClick={() => onApply(v.config as C, v.layout)}
                  title={v.user_id ? "Only you see this view" : "Shared with the workspace"}>
            {v.name}{v.user_id ? "" : " (shared)"}
          </button>
          <button className="icon-btn" style={{ fontSize: 14 }} aria-label={`Delete view ${v.name}`} onClick={() => remove(v)}>×</button>
        </span>
      ))}
      <button className="link-btn" onClick={save}>Save current view</button>
    </div>
  );
}
