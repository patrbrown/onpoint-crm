"use client";

import { useState } from "react";
import { splitList } from "@/lib/format";

/** A list of tags you can add to (type and press Enter, or paste a comma-separated list) and remove from. */
export function TagEditor({ label, items, onChange, tone, placeholder }: {
  label: string; items: string[]; onChange: (next: string[]) => void; tone?: "system"; placeholder?: string;
}) {
  const [v, setV] = useState("");
  function add() {
    const have = new Set(items.map((x) => x.toLowerCase()));
    const fresh: string[] = [];
    for (const x of splitList(v)) {
      if (!have.has(x.toLowerCase())) { have.add(x.toLowerCase()); fresh.push(x); }
    }
    setV("");
    if (fresh.length) onChange([...items, ...fresh]);
  }
  return (
    <div className="tag-editor">
      <h3>{label}</h3>
      <div className="tags">
        {items.map((x) => (
          <span key={x} className={`tag removable${tone ? " " + tone : ""}`}>{x}
            <button type="button" aria-label={`Remove ${x}`} onClick={() => onChange(items.filter((i) => i !== x))}>×</button>
          </span>
        ))}
        {items.length === 0 && <span className="muted" style={{ fontSize: 12 }}>None yet</span>}
      </div>
      <input className="tag-input" value={v} placeholder={placeholder ?? "Add, then press Enter"} aria-label={`Add to ${label}`}
             onChange={(e) => setV(e.target.value)} onBlur={add}
             onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} />
    </div>
  );
}
