"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getResearch, getTrace } from "@/lib/api";
import type { ResearchDetail, TraceView } from "@/lib/types";
import { RunHeader } from "@/components/research/RunHeader";
import { TraceAgentRuns, UsageTable } from "@/components/research/TraceTable";
import { Card, SectionHeading } from "@/components/ui/Layout";
import { EmptyState, ErrorState, SkeletonLines } from "@/components/ui/States";

/** Renders `GET /research/{id}/trace`: task/tool/duration/status summaries only, never model reasoning. */
export function TraceContent({ sessionId }: { sessionId: string }) {
  const [trace, setTrace] = useState<TraceView | null>(null);
  const [detail, setDetail] = useState<ResearchDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTrace(await getTrace(sessionId));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the trace.");
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

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonLines count={6} />
      </div>
    );
  }
  if (error || !trace) return <ErrorState message={error ?? "Trace not available."} onRetry={load} />;

  return (
    <div>
      <RunHeader
        id={sessionId}
        company={detail?.company ?? null}
        status={detail?.status ?? "researching"}
        query={detail?.request.query}
      />

      <div className="space-y-6">
        <Card>
          <SectionHeading>Agent runs</SectionHeading>
          {trace.agent_runs.length === 0 ? (
            <EmptyState title="No agent runs recorded yet" />
          ) : (
            <TraceAgentRuns runs={trace.agent_runs} toolCalls={trace.tool_calls} />
          )}
        </Card>

        <Card>
          <SectionHeading>Usage & cost</SectionHeading>
          {trace.usage.length === 0 ? (
            <EmptyState
              title="No token usage recorded"
              description={
                detail?.llm_mode === "offline"
                  ? "This run used the deterministic offline model, which calls no API and therefore consumes no tokens. Set ANTHROPIC_API_KEY to see per-agent token counts and cost here."
                  : "Usage is recorded as each agent calls the model; nothing has been reported for this run yet."
              }
            />
          ) : (
            <UsageTable usage={trace.usage} totalTokens={trace.total_tokens} totalCostUsd={trace.total_cost_usd} />
          )}
        </Card>

        {trace.errors.length > 0 && (
          <Card>
            <SectionHeading>Errors</SectionHeading>
            <ul className="space-y-1 text-sm text-red-400">
              {trace.errors.map((err, i) => (
                <li key={i}>
                  {err.agent && <span className="font-medium">{err.agent}: </span>}
                  {err.message} <span className="text-ink-500">({err.stage})</span>
                </li>
              ))}
            </ul>
          </Card>
        )}

        {Object.keys(trace.timings_ms).length > 0 && (
          <Card>
            <SectionHeading>Stage timings</SectionHeading>
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              {Object.entries(trace.timings_ms).map(([stage, ms]) => (
                <div key={stage}>
                  <dt className="text-xs text-ink-400">{stage}</dt>
                  <dd className="text-ink-100">{(ms / 1000).toFixed(1)}s</dd>
                </div>
              ))}
            </dl>
          </Card>
        )}
      </div>
    </div>
  );
}
