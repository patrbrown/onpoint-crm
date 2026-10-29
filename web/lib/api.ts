import { getSupabase } from "./supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const sb = getSupabase();
  if (!sb) return {}; // dev mode: the API acts as DEV_USER_ID
  const { data } = await sb.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function messageFrom(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) {
    const d = detail[0];
    const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
    return field ? `${String(field).replace(/_/g, " ")}: ${d.msg}` : d.msg;
  }
  return `Request failed (${status})`;
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(await authHeader()), ...(init.headers as Record<string, string>) };
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError(0, "Couldn’t reach the CRM service. Check it’s running (docker compose ps), then try again.");
  }
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) throw new ApiError(res.status, messageFrom(data, res.status));
  return data as T;
}

export async function apiBlobUrl(path: string): Promise<string> {
  const res = await fetch(`${API}${path}`, { headers: await authHeader() });
  if (!res.ok) throw new ApiError(res.status, `Could not open file (${res.status})`);
  return URL.createObjectURL(await res.blob());
}

export const t = (tenantId: string, path: string) => `/tenants/${tenantId}${path}`;
