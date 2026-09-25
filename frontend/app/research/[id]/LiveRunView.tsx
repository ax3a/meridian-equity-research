"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, cancelResearch, getAgentRuns, getResearch, getResearchStatus, getReview } from "@/lib/api";
import type { AgentRunView, ResearchDetail, ReviewPackage, StatusView } from "@/lib/types";
import { TERMINAL_RUN_STATUSES } from "@/lib/types";
import { useResearchEvents } from "@/components/hooks/useResearchEvents";
import { RunHeader } from "@/components/research/RunHeader";
import { PlanView } from "@/components/research/PlanView";
import { AgentWaveGraph } from "@/components/research/AgentWaveGraph";
import { EventFeed } from "@/components/research/EventFeed";
import { CriticPanel } from "@/components/research/CriticPanel";
import { ReviewPanel } from "@/components/research/ReviewPanel";
import { ModeBanners } from "@/components/ui/Banners";
import { Card, SectionHeading } from "@/components/ui/Layout";
import { ErrorState, SkeletonCard } from "@/components/ui/States";

function describeError(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function LiveRunView({ sessionId }: { sessionId: string }) {
  const [detail, setDetail] = useState<ResearchDetail | null>(null);
  const [status, setStatus] = useState<StatusView | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRunView[]>([]);
  const [review, setReview] = useState<ReviewPackage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const { events, streamStatus } = useResearchEvents(sessionId);

  const refresh = useCallback(async () => {
    try {
      const [detailRes, statusRes, agentsRes] = await Promise.all([
        getResearch(sessionId),
        getResearchStatus(sessionId),
        getAgentRuns(sessionId).catch(() => [] as AgentRunView[]),
      ]);
      setDetail(detailRes);
      setStatus(statusRes);
      setAgentRuns(agentsRes);
      setError(null);
      if (statusRes.approval === "pending" || detailRes.status === "awaiting_approval") {
        try {
          setReview(await getReview(sessionId));
        } catch {
          // The review package may not be assembled yet; keep whatever we had (or null).
        }
      } else {
        setReview(null);
      }
    } catch (err) {
      setError(describeError(err, "Could not load this research run."));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // ProgressEvent.data is intentionally untyped by the API contract (it's not part of the frozen schema
  // beyond `dict[str, Any]`), so rather than parse nested event payloads we treat every SSE message as a
  // signal to refresh the typed status/detail/review endpoints. This also naturally covers the SSE
  // reconnect case, since EventSource keeps delivering messages transparently after it resumes.
  useEffect(() => {
    if (events.length === 0) return;
    refresh();
  }, [events.length, refresh]);

  // Fallback poll, used ONLY while the live stream is not connected. The stream is an optimisation, not
  // the source of truth: when it is unavailable (a proxy that buffers, a network that blocks
  // text/event-stream) this view would otherwise sit on whatever it fetched at mount and show "Queued"
  // for a run that has already finished. Polling while the stream is healthy would duplicate the
  // event-driven refresh above and burn through the API rate limit for no benefit.
  useEffect(() => {
    const status = detail?.status;
    if (!status || TERMINAL_RUN_STATUSES.includes(status)) return;
    if (streamStatus === "open") return;
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [detail?.status, streamStatus, refresh]);

  if (loading) {
    return (
      <div className="space-y-4">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (error || !detail || !status) {
    return <ErrorState message={error ?? "This research run could not be found."} onRetry={refresh} />;
  }

  const runsByAgent = new Map(agentRuns.map((r) => [r.agent, r]));
  const latestCritic = detail.critic_reviews.length > 0 ? detail.critic_reviews[detail.critic_reviews.length - 1]! : null;
  const isTerminal = TERMINAL_RUN_STATUSES.includes(detail.status);

  async function handleCancel() {
    if (typeof window !== "undefined" && !window.confirm("Cancel this research run?")) return;
    try {
      await cancelResearch(sessionId);
      refresh();
    } catch (err) {
      setError(describeError(err, "Could not cancel this run."));
    }
  }

  return (
    <div>
      <RunHeader id={sessionId} company={detail.company} status={detail.status} query={detail.request.query} />
      <ModeBanners llmMode={detail.llm_mode} usesSnapshotData={detail.uses_snapshot_data} />

      {streamStatus === "reconnecting" && (
        <p className="mb-4 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          Live updates disconnected — reconnecting…
        </p>
      )}
      {streamStatus === "closed" && !isTerminal && (
        <p className="mb-4 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          Live stream closed. Status shown below may be stale — reload to reconnect.
        </p>
      )}

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-300">
          Wave {detail.current_wave} · Revision round {detail.revision_round} ·{" "}
          {Math.round(status.progress * 100)}% complete
        </p>
        {!isTerminal && (
          <button
            type="button"
            onClick={handleCancel}
            className="rounded-md border border-red-500/40 px-3 py-1.5 text-xs font-medium text-red-300 transition hover:bg-red-500/10"
          >
            Cancel run
          </button>
        )}
      </div>

      {status.approval === "pending" && review && (
        <div className="mb-6">
          <ReviewPanel sessionId={sessionId} review={review} onSubmitted={refresh} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {detail.plan && (
            <Card>
              <SectionHeading>Plan</SectionHeading>
              <PlanView plan={detail.plan} live={status.agents} />
            </Card>
          )}
          <Card>
            <SectionHeading>Agents</SectionHeading>
            <AgentWaveGraph agents={status.agents} runsByAgent={runsByAgent} />
          </Card>
          {latestCritic && (
            <Card>
              <SectionHeading>Critic</SectionHeading>
              <CriticPanel review={latestCritic} />
            </Card>
          )}
          {detail.errors.length > 0 && (
            <Card>
              <SectionHeading>Errors</SectionHeading>
              <ul className="space-y-1 text-sm text-red-400">
                {detail.errors.map((err, i) => (
                  <li key={i}>
                    {err.agent && <span className="font-medium">{err.agent}: </span>}
                    {err.message}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <div>
          <Card>
            <SectionHeading>Activity</SectionHeading>
            <EventFeed events={events} />
          </Card>
          {detail.has_report && (
            <Link
              href={`/research/${sessionId}/report`}
              className="mt-4 block rounded-md bg-accent-600 px-4 py-2 text-center text-sm font-medium text-white transition hover:bg-accent-500"
            >
              View report
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
