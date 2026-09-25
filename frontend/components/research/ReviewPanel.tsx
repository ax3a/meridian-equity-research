"use client";

import { useState } from "react";
import type { AgentName, FeedbackAction, HumanFeedback, ReviewPackage } from "@/lib/types";
import { SPECIALIST_AGENTS } from "@/lib/types";
import { ApiError, approveResearch, submitFeedback } from "@/lib/api";
import { PlanView } from "./PlanView";
import { CriticPanel } from "./CriticPanel";
import { humanizeEnum } from "@/lib/format";

interface ReviewPanelProps {
  sessionId: string;
  review: ReviewPackage;
  /** Called after any action succeeds, so the parent can refetch status/review and reflect the new state. */
  onSubmitted: () => void;
}

const ACTION_LABEL: Record<FeedbackAction, string> = {
  approve: "Approve & write report",
  deepen_valuation: "Deepen the valuation",
  add_competitor: "Add a competitor",
  add_risk_analysis: "Add risk analysis",
  rerun_agent: "Re-run an agent",
  comment: "Add a comment",
};

const ALL_ACTIONS: FeedbackAction[] = [
  "approve",
  "deepen_valuation",
  "add_competitor",
  "add_risk_analysis",
  "rerun_agent",
  "comment",
];

/**
 * The human approval checkpoint: the plan, retrieved sources and preliminary findings for inspection,
 * plus actions to approve the report or demand more work first. "approve" posts to `POST /approve`;
 * every other action posts a `HumanFeedback` to `POST /feedback`.
 */
export function ReviewPanel({ sessionId, review, onSubmitted }: ReviewPanelProps) {
  const [pending, setPending] = useState<FeedbackAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ticker, setTicker] = useState("");
  const [rerunAgent, setRerunAgent] = useState<AgentName | "">("");
  const [comment, setComment] = useState("");

  const availableSet = new Set<string>(review.available_actions.length > 0 ? review.available_actions : ALL_ACTIONS);
  const available = ALL_ACTIONS.filter((a) => availableSet.has(a));

  function describeError(err: unknown, fallback: string): string {
    return err instanceof ApiError ? err.message : err instanceof Error ? err.message : fallback;
  }

  async function handleApprove() {
    setPending("approve");
    setError(null);
    try {
      await approveResearch(sessionId);
      onSubmitted();
    } catch (err) {
      setError(describeError(err, "Failed to approve this run."));
    } finally {
      setPending(null);
    }
  }

  async function handleFeedback(action: Exclude<FeedbackAction, "approve">, overrides: Partial<HumanFeedback> = {}) {
    setPending(action);
    setError(null);
    const feedback: HumanFeedback = {
      action,
      agent: overrides.agent ?? null,
      ticker: overrides.ticker ?? null,
      comment: overrides.comment ?? null,
      submitted_at: null,
    };
    try {
      await submitFeedback(sessionId, { actions: [feedback] });
      onSubmitted();
    } catch (err) {
      setError(describeError(err, "Failed to submit that feedback."));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-200">
        <p className="font-semibold">Awaiting your approval</p>
        <p className="mt-1 text-amber-200/80">
          Review the plan, retrieved sources and preliminary findings below, then approve to have the report
          written — or ask for more work first.
        </p>
      </div>

      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">Plan</h3>
        <PlanView plan={review.plan} />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">
          Retrieved sources ({review.sources.length})
        </h3>
        {review.sources.length === 0 ? (
          <p className="text-sm text-ink-400">No sources retrieved yet.</p>
        ) : (
          <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {review.sources.map((s) => (
              <li key={s.id} className="rounded-md border border-ink-700 bg-ink-900/40 p-2 text-xs text-ink-300">
                <p className="font-medium text-ink-100">{s.title}</p>
                <p>{s.publisher}</p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">Preliminary findings</h3>
        {review.preliminary.length === 0 ? (
          <p className="text-sm text-ink-400">No preliminary findings yet.</p>
        ) : (
          <div className="space-y-3">
            {review.preliminary.map((section) => (
              <div key={section.agent} className="rounded-md border border-ink-700 p-3">
                <p className="mb-1 font-medium text-ink-100">{humanizeEnum(section.agent)}</p>
                <p className="mb-2 text-sm text-ink-300">{section.summary}</p>
                <ul className="list-disc space-y-1 pl-5 text-sm text-ink-300">
                  {section.findings.map((f) => (
                    <li key={f.id}>{f.claim}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      {review.critic && (
        <section>
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-ink-400">Critic review</h3>
          <CriticPanel review={review.critic} />
        </section>
      )}

      <section className="space-y-4 rounded-lg border border-ink-700 p-4">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-400">Actions</h3>
        {error && (
          <p role="alert" className="text-sm text-red-400">
            {error}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          {available.includes("approve") && (
            <button
              type="button"
              onClick={handleApprove}
              disabled={pending !== null}
              className="rounded-md bg-accent-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-500 disabled:opacity-50"
            >
              {pending === "approve" ? "Approving…" : ACTION_LABEL.approve}
            </button>
          )}
          {available.includes("add_risk_analysis") && (
            <button
              type="button"
              onClick={() => handleFeedback("add_risk_analysis")}
              disabled={pending !== null}
              className="rounded-md border border-ink-600 px-4 py-2 text-sm font-medium text-ink-100 transition hover:bg-ink-800 disabled:opacity-50"
            >
              {pending === "add_risk_analysis" ? "Requesting…" : ACTION_LABEL.add_risk_analysis}
            </button>
          )}
          {available.includes("deepen_valuation") && (
            <button
              type="button"
              onClick={() => handleFeedback("deepen_valuation")}
              disabled={pending !== null}
              className="rounded-md border border-ink-600 px-4 py-2 text-sm font-medium text-ink-100 transition hover:bg-ink-800 disabled:opacity-50"
            >
              {pending === "deepen_valuation" ? "Requesting…" : ACTION_LABEL.deepen_valuation}
            </button>
          )}
        </div>

        {available.includes("add_competitor") && (
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label htmlFor="add-competitor-ticker" className="mb-1 block text-xs text-ink-400">
                Competitor ticker
              </label>
              <input
                id="add-competitor-ticker"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
                placeholder="e.g. AMD"
                className="rounded-md border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-ink-100 focus:border-accent-500 focus:outline-none"
              />
            </div>
            <button
              type="button"
              disabled={pending !== null || !ticker.trim()}
              onClick={() => handleFeedback("add_competitor", { ticker: ticker.trim().toUpperCase() })}
              className="rounded-md border border-ink-600 px-4 py-2 text-sm font-medium text-ink-100 transition hover:bg-ink-800 disabled:opacity-50"
            >
              {pending === "add_competitor" ? "Requesting…" : ACTION_LABEL.add_competitor}
            </button>
          </div>
        )}

        {available.includes("rerun_agent") && (
          <div className="flex flex-wrap items-end gap-2">
            <div>
              <label htmlFor="rerun-agent-select" className="mb-1 block text-xs text-ink-400">
                Agent to re-run
              </label>
              <select
                id="rerun-agent-select"
                value={rerunAgent}
                onChange={(e) => setRerunAgent(e.target.value as AgentName | "")}
                className="rounded-md border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-ink-100 focus:border-accent-500 focus:outline-none"
              >
                <option value="">Select an agent</option>
                {SPECIALIST_AGENTS.map((a) => (
                  <option key={a} value={a}>
                    {humanizeEnum(a)}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              disabled={pending !== null || !rerunAgent}
              onClick={() => rerunAgent && handleFeedback("rerun_agent", { agent: rerunAgent })}
              className="rounded-md border border-ink-600 px-4 py-2 text-sm font-medium text-ink-100 transition hover:bg-ink-800 disabled:opacity-50"
            >
              {pending === "rerun_agent" ? "Requesting…" : ACTION_LABEL.rerun_agent}
            </button>
          </div>
        )}

        {available.includes("comment") && (
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[240px] flex-1">
              <label htmlFor="review-comment" className="mb-1 block text-xs text-ink-400">
                Comment
              </label>
              <input
                id="review-comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Anything else the supervisor should know"
                className="w-full rounded-md border border-ink-600 bg-ink-900 px-2 py-1.5 text-sm text-ink-100 focus:border-accent-500 focus:outline-none"
              />
            </div>
            <button
              type="button"
              disabled={pending !== null || !comment.trim()}
              onClick={() => handleFeedback("comment", { comment: comment.trim() })}
              className="rounded-md border border-ink-600 px-4 py-2 text-sm font-medium text-ink-100 transition hover:bg-ink-800 disabled:opacity-50"
            >
              {pending === "comment" ? "Submitting…" : ACTION_LABEL.comment}
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
