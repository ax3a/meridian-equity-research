"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, getDashboard } from "@/lib/api";
import type { DashboardView } from "@/lib/types";
import { PageHeader, Card, SectionHeading } from "@/components/ui/Layout";
import { EmptyState, ErrorState, SkeletonCard } from "@/components/ui/States";
import { StatusChip } from "@/components/ui/StatusChip";
import { ModeBanners } from "@/components/ui/Banners";
import { formatDateTime, humanizeEnum } from "@/lib/format";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getDashboard()
      .then(setData)
      .catch((err: unknown) => setError(err instanceof ApiError ? err.message : "Could not load the dashboard."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Recent research runs, saved companies and system status."
        actions={
          <Link
            href="/research/new"
            className="rounded-md bg-accent-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-500"
          >
            New research
          </Link>
        }
      />

      {loading && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <SkeletonCard className="lg:col-span-2" />
          <SkeletonCard />
        </div>
      )}

      {!loading && error && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && data && (
        <div className="space-y-6">
          <ModeBanners llmMode={data.system.llm_mode} usesSnapshotData={data.system.data_mode === "snapshot"} />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="space-y-4 lg:col-span-2">
              <Card>
                <SectionHeading>Recent runs</SectionHeading>
                {data.recent_runs.length === 0 ? (
                  <EmptyState
                    title="No research runs yet"
                    description="Start your first research run to see it here."
                    action={
                      <Link href="/research/new" className="text-sm font-medium text-accent-400 hover:underline">
                        Start a run
                      </Link>
                    }
                  />
                ) : (
                  <ul className="divide-y divide-ink-800">
                    {data.recent_runs.map((run) => (
                      <li key={run.id} className="py-3">
                        <Link
                          href={run.has_report ? `/research/${run.id}/report` : `/research/${run.id}`}
                          className="flex items-center justify-between gap-3 transition hover:opacity-80"
                        >
                          <div className="min-w-0">
                            <p className="truncate font-medium text-ink-100">
                              {run.company ? `${run.company.name} (${run.company.ticker})` : run.query}
                            </p>
                            <p className="truncate text-xs text-ink-400">{run.query}</p>
                          </div>
                          <div className="flex flex-shrink-0 items-center gap-2">
                            <StatusChip status={run.status} kind="run" />
                            <span className="text-xs text-ink-500">{formatDateTime(run.updated_at)}</span>
                          </div>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>

            <div className="space-y-4">
              <Card>
                <SectionHeading>System status</SectionHeading>
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-ink-400">LLM mode</dt>
                    <dd className="text-ink-100">{humanizeEnum(data.system.llm_mode)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-400">Data mode</dt>
                    <dd className="text-ink-100">{humanizeEnum(data.system.data_mode)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-400">Database</dt>
                    <dd className={data.system.database ? "text-emerald-400" : "text-red-400"}>
                      {data.system.database ? "Connected" : "Unavailable"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-400">Redis</dt>
                    <dd className={data.system.redis ? "text-emerald-400" : "text-red-400"}>
                      {data.system.redis ? "Connected" : "Unavailable"}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-ink-400">Active runs</dt>
                    <dd className="text-ink-100">{data.system.active_runs}</dd>
                  </div>
                </dl>
                {data.system.providers.length > 0 && (
                  <div className="mt-3 border-t border-ink-800 pt-3">
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-400">Providers</p>
                    <ul className="space-y-1 text-xs">
                      {data.system.providers.map((p) => (
                        <li key={p.name} className="flex items-center justify-between gap-2">
                          <span className="text-ink-300">
                            {p.name} <span className="text-ink-500">({p.role})</span>
                          </span>
                          <span className={p.configured ? "text-emerald-400" : "text-ink-500"}>
                            {p.configured ? "Ready" : "Not configured"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>

              <Card>
                <SectionHeading>Saved companies</SectionHeading>
                {data.saved_companies.length === 0 ? (
                  <p className="text-sm text-ink-400">No saved companies yet.</p>
                ) : (
                  <ul className="space-y-2 text-sm">
                    {data.saved_companies.map((sc) => (
                      <li key={sc.company.cik} className="flex items-center justify-between gap-2">
                        <span className="text-ink-100">
                          {sc.company.name} <span className="text-ink-500">({sc.company.ticker})</span>
                        </span>
                        {sc.last_research_id && (
                          <Link
                            href={`/research/${sc.last_research_id}`}
                            className="text-xs font-medium text-accent-400 hover:underline"
                          >
                            Latest run
                          </Link>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              {Object.keys(data.stats).length > 0 && (
                <Card>
                  <SectionHeading>Stats</SectionHeading>
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    {Object.entries(data.stats).map(([key, value]) => (
                      <div key={key}>
                        <dt className="text-xs text-ink-400">{humanizeEnum(key)}</dt>
                        <dd className="text-lg font-semibold text-ink-50">{value}</dd>
                      </div>
                    ))}
                  </dl>
                </Card>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
