export const fullName = (p: { first_name: string; last_name?: string | null }) =>
  [p.first_name, p.last_name].filter(Boolean).join(" ");

export const labels: Record<string, string> = {
  onsite: "On-site", hybrid: "Hybrid", remote: "Remote",
  permanent: "Permanent", contract: "Contract", contract_to_hire: "Contract to hire", temporary: "Temporary",
  draft: "Draft", open: "Open", on_hold: "On hold", filled: "Filled", closed: "Closed", cancelled: "Cancelled",
  low: "Low", normal: "Normal", high: "High", urgent: "Urgent",
  active: "Active", placed: "Placed", do_not_contact: "Do not contact", archived: "Archived",
  prospect: "Prospect", inactive: "Inactive",
  strong_yes: "Strong yes", yes: "Yes", maybe: "Maybe", no: "No", strong_no: "Strong no",
  manual: "Added manually", email: "From email", import: "Imported", portal: "Applied online", api: "API",
};
export const label = (v?: string | null) => (v ? labels[v] ?? v : "");

export function money(n?: string | number | null, currency = "CAD") {
  if (n === null || n === undefined || n === "") return "";
  return new Intl.NumberFormat("en-CA", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(n));
}

export function compensation(j: {
  salary_min: any; salary_max: any; rate_min: any; rate_max: any; rate_unit: any; currency: any;
}) {
  const c = j.currency || "CAD";
  const range = (a: any, b: any) => (a && b ? `${money(a, c)}–${money(b, c)}` : money(a || b, c));
  if (j.rate_min || j.rate_max) return `${range(j.rate_min, j.rate_max)} / ${j.rate_unit || "hour"}`;
  if (j.salary_min || j.salary_max) return `${range(j.salary_min, j.salary_max)} / year`;
  return "";
}

export function place(x: { location?: string | null; city?: string | null; region?: string | null }) {
  return x.location || [x.city, x.region].filter(Boolean).join(", ");
}

export function date(s?: string | null) {
  if (!s) return "";
  return new Date(s).toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric" });
}

export const splitList = (s: string) => s.split(/[,;\n]/).map((x) => x.trim()).filter(Boolean);

export function dateTime(s?: string | null) {
  if (!s) return "";
  return new Date(s).toLocaleString("en-CA", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}
