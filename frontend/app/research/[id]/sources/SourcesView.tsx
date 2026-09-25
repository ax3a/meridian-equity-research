"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, getResearch, getSources } from "@/lib/api";
import type { ResearchDetail, SourceView } from "@/lib/types";
import { RunHeader } from "@/components/research/RunHeader";
import { SourceCard } from "@/components/research/SourceCard";
import { EmptyState, ErrorState, SkeletonLines } from "@/components/ui/States";
import { humanizeEnum } from "@/lib/format";

export function SourcesView({ sessionId }: { sessionId: string }) {
  const [sources, setSources] = useState<SourceView[]>([]);
  const [detail, setDetail] = useState<ResearchDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<string>("all");
  const [providerFilter, setProviderFilter] = useState<string>("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSources(await getSources(sessionId));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load sources.");
    } finally {
      setLoading(false);
    }
    try {
      setDetail(await getResearch(sessionId));
    } catch {
      // The run header degrades gracefully without it.
    }
  }, [sessionId]);

  useEffect(() => {
    load();
  }, [load]);

  const kinds = useMemo(() => [...new Set(sources.map((s) => s.source.kind))].sort(), [sources]);
  const providers = useMemo(() => [...new Set(sources.map((s) => s.source.provider))].sort(), [sources]);

  const filtered = sources.filter(
    (s) =>
      (kindFilter === "all" || s.source.kind === kindFilter) &&
      (providerFilter === "all" || s.source.provider === providerFilter),
  );

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonLines count={6} />
      </div>
    );
  }
  if (error) return <ErrorState message={error} onRetry={load} />;

  return (
    <div>
      <RunHeader
        id={sessionId}
        company={detail?.company ?? null}
        status={detail?.status ?? "researching"}
        query={detail?.request.query}
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <div>
          <label htmlFor="kind-filter" className="mb-1 block text-xs text-ink-400">
            Kind
          </label>
          <select
            id="kind-filter"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
            className="rounded-md border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-ink-100"
          >
            <option value="all">All kinds</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {humanizeEnum(k)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="provider-filter" className="mb-1 block text-xs text-ink-400">
            Provider
          </label>
          <select
            id="provider-filter"
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
            className="rounded-md border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-ink-100"
          >
            <option value="all">All providers</option>
            {providers.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          title={sources.length === 0 ? "No sources yet" : "No sources match these filters"}
          description="Sources appear here as agents gather evidence during the run."
        />
      ) : (
        <div className="space-y-2">
          {filtered.map((sv) => (
            <SourceCard key={sv.source.id} sourceView={sv} />
          ))}
        </div>
      )}
    </div>
  );
}
