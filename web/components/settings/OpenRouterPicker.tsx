"use client";

import { useMemo, useState } from "react";
import { t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type M = { id: string; name: string; input_per_m: number; output_per_m: number | null; context: number | null };

// A typical email or resume: ~4,000 tokens in, ~800 out.
const perItem = (m: M) => (4000 * m.input_per_m + 800 * (m.output_per_m ?? 0)) / 1_000_000;
const usd = (n: number) => (n === 0 ? "Free" : n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(3)}`);

/** Searchable OpenRouter catalogue, cheapest first, with an estimated cost per email or resume. */
export function OpenRouterPicker({ current, onPick }: { current: string; onPick: (id: string) => void }) {
  const { tenant } = useSession();
  const list = useData<{ ok: boolean; error?: string; models: M[] }>(t(tenant.id, "/ai/openrouter-models"));
  const [q, setQ] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);
  const rows = useMemo(() => (list.data?.models ?? []).filter((m) => {
    const hay = `${m.id} ${m.name}`.toLowerCase();
    return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w)) && (!freeOnly || perItem(m) === 0);
  }), [list.data, q, freeOnly]);

  if (list.data && !list.data.ok) return <p className="err-text">{list.data.error}</p>;
  return (
    <>
      <p className="muted" style={{ marginBottom: 10 }}>Cheapest first. “Per item” is the estimated cost of reading one typical email or resume. Open models from Qwen, Llama, Mistral and DeepSeek handle extraction well; very small or free models can be
        unreliable, so keep “fall back to Claude” on.</p>
      <div className="toolbar">
        <input className="search" type="search" placeholder="Search, e.g. qwen 72b" value={q} onChange={(e) => setQ(e.target.value)}
               aria-label="Search models" autoFocus />
        <label className="check"><input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} /> Free only</label>
        <span className="muted">{list.data ? `${rows.length} models` : "Loading…"}</span>
      </div>
      <div className="table-wrap" style={{ maxHeight: "60vh", overflow: "auto" }}>
        <table>
          <thead><tr><th>Model</th><th className="num">Per item</th><th className="num">In / out per 1M tokens</th><th className="num">Context</th><th /></tr></thead>
          <tbody>
            {rows.slice(0, 300).map((m) => (
              <tr key={m.id} className={m.id === current ? "picked" : ""}>
                <td>{m.name}<span className="sub">{m.id}</span></td>
                <td className="num">{usd(perItem(m))}</td>
                <td className="num muted">${m.input_per_m} / ${m.output_per_m ?? "?"}</td>
                <td className="num muted">{m.context ? `${Math.round(m.context / 1000)}k` : ""}</td>
                <td className="num">{m.id === current ? <span className="muted">Selected</span>
                  : <button className="btn small" onClick={() => onPick(m.id)}>Use</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
