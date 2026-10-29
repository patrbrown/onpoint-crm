"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

/* ── Toasts ─────────────────────────────────────────────────────────────── */

type Toast = { id: number; text: string; kind: "ok" | "error" };
const ToastCtx = createContext<(text: string, kind?: "ok" | "error") => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

/* ── Drawer (side panel for create/edit forms) ──────────────────────────── */

export function Drawer({ title, open, onClose, children }: {
  title: string; open: boolean; onClose: () => void; children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); prev?.focus(); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="drawer" role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <header className="drawer-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}

/* ── Form fields ────────────────────────────────────────────────────────── */

export function Field({ label, hint, children, wide }: {
  label: string; hint?: string; children: React.ReactNode; wide?: boolean;
}) {
  return (
    <label className={`field${wide ? " wide" : ""}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Select({ value, onChange, options, placeholder }: {
  value: string; onChange: (v: string) => void; options: [string, string][]; placeholder?: string;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

export function Tags({ items, tone }: { items?: string[] | null; tone?: "system" }) {
  if (!items?.length) return null;
  return <span className="tags">{items.map((x) => <span key={x} className={`tag${tone ? " " + tone : ""}`}>{x}</span>)}</span>;
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return <div className="empty"><p className="empty-title">{title}</p>{children}</div>;
}

export function Status({ value, text }: { value: string; text: string }) {
  return <span className={`status s-${value}`}>{text}</span>;
}

/** Turns an object of form state into a clean payload: empty strings → omitted. */
export function clean<T extends Record<string, any>>(o: T): Partial<T> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(o)) if (v !== "" && v !== undefined) out[k] = v;
  return out as Partial<T>;
}
