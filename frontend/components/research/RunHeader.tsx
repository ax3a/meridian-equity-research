"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { CompanyIdentity, RunStatus } from "@/lib/types";
import { StatusChip } from "@/components/ui/StatusChip";

interface RunHeaderProps {
  id: string;
  company: CompanyIdentity | null;
  status: RunStatus;
  query?: string;
}

const TABS = [
  { suffix: "", label: "Live Run" },
  { suffix: "/report", label: "Report" },
  { suffix: "/sources", label: "Sources" },
  { suffix: "/trace", label: "Trace" },
];

/** Shared header + tab navigation for all four `/research/[id]/*` pages. */
export function RunHeader({ id, company, status, query }: RunHeaderProps) {
  const pathname = usePathname();
  const base = `/research/${id}`;

  return (
    <div className="mb-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink-50">
            {company ? `${company.name} (${company.ticker})` : "Research Run"}
          </h1>
          {query && <p className="mt-0.5 max-w-2xl text-sm text-ink-400">{query}</p>}
        </div>
        <StatusChip status={status} kind="run" />
      </div>
      <nav className="no-print flex gap-1 border-b border-ink-800" aria-label="Run sections">
        {TABS.map((tab) => {
          const href = `${base}${tab.suffix}`;
          const active = pathname === href;
          return (
            <Link
              key={tab.suffix}
              href={href}
              aria-current={active ? "page" : undefined}
              className={`border-b-2 px-3 py-2 text-sm font-medium transition ${
                active ? "border-accent-500 text-ink-50" : "border-transparent text-ink-400 hover:text-ink-200"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
