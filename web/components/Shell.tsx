"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useNewApplicantCount } from "@/lib/applicants";
import { useSession } from "@/lib/session";

const NAV = [
  { href: "/jobs", label: "Jobs" },
  { href: "/applicants", label: "New applicants" },
  { href: "/candidates", label: "Candidates" },
  { href: "/clients", label: "Clients" },
  { href: "/inbox", label: "Email inbox" },
  { href: "/settings", label: "Settings" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { me, tenant, setTenant, signOut } = useSession();
  const path = usePathname();
  const newApplicants = useNewApplicantCount(tenant.id);
  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><span /></span>
          <span className="brand-name">{tenant.name}</span>
        </div>
        {me.tenants.length > 1 && (
          <select className="tenant-switch" value={tenant.id} onChange={(e) => setTenant(e.target.value)}
                  aria-label="Workspace">
            {me.tenants.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        )}
        <ul>
          {NAV.filter((n) => n.href !== "/inbox" || tenant.inbox_access).map((n) => (
            <li key={n.href}>
              <Link href={n.href} className={path.startsWith(n.href) ? "active" : ""}
                    aria-current={path.startsWith(n.href) ? "page" : undefined}>
                {n.label}
                {n.href === "/applicants" && newApplicants > 0 && (
                  <span className="nav-badge" aria-label={`${newApplicants} new`}>{newApplicants > 99 ? "99+" : newApplicants}</span>
                )}
              </Link>
            </li>
          ))}
        </ul>
        <div className="side-foot">
          <span className="who">{me.profile.email}</span>
          <button className="link-btn" onClick={signOut}>Sign out</button>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
