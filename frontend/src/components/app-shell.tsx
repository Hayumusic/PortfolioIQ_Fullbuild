"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { JobControl } from "@/context/job-context";

const navigation = [
  { href: "/uploads", label: "Uploads", icon: "UP" },
  { href: "/validation", label: "CMDB Validation", icon: "VA" },
  { href: "/similarity", label: "Similarity and Redundancy", icon: "SI" },
  { href: "/technology", label: "Technology and Integration", icon: "TE" },
  { href: "/output-families", label: "Application Outputs", icon: "AO" },
  { href: "/portfolio-insights", label: "Portfolio Insights", icon: "PI" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">AA</div>
          <div>
            <div className="brand-name">App Analyser MVP</div>
            <div className="brand-caption">Local CMDB analysis</div>
          </div>
        </div>
        <nav className="navigation" aria-label="Primary navigation">
          <div className="nav-label">Analysis modules</div>
          {navigation.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                className={`nav-link ${active ? "active" : ""}`}
                href={item.href}
                key={item.href}
                aria-current={active ? "page" : undefined}
              >
                <span className="nav-icon" aria-hidden="true">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        {!(["/similarity", "/technology", "/output-families"].includes(pathname)) && <JobControl />}
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <h1>App Analyser MVP</h1>
            <p>Local, CMDB-first enterprise application analysis. No dummy data is generated; analysis uses only uploaded inputs and configured rules.</p>
          </div>
        </header>
        <main className="main-content">{children}</main>
      </div>
    </div>
  );
}
