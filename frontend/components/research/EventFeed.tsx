"use client";

import type { EventType, ProgressEvent } from "@/lib/types";
import { formatRelativeTime, humanizeEnum } from "@/lib/format";

const TYPE_COLOR: Record<EventType, string> = {
  run_started: "bg-accent-400",
  company_resolved: "bg-accent-400",
  plan_created: "bg-accent-400",
  wave_started: "bg-ink-400",
  agent_started: "bg-amber-400",
  agent_completed: "bg-emerald-400",
  agent_failed: "bg-red-400",
  tool_called: "bg-ink-400",
  supervisor_review: "bg-accent-400",
  critic_started: "bg-calculated",
  critic_verdict: "bg-calculated",
  revision_started: "bg-amber-400",
  awaiting_approval: "bg-amber-400",
  feedback_received: "bg-accent-400",
  report_started: "bg-accent-400",
  report_completed: "bg-emerald-400",
  run_completed: "bg-emerald-400",
  run_failed: "bg-red-400",
};

/** A scrolling feed of `ProgressEvent`s. `message` is server-composed, human-facing text (never CoT). */
export function EventFeed({ events }: { events: ProgressEvent[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-ink-400">Waiting for the run to start…</p>;
  }

  return (
    <ol className="max-h-96 space-y-2 overflow-y-auto pr-1">
      {[...events].reverse().map((event, i) => (
        <li key={`${event.session_id}-${event.seq}-${i}`} className="flex items-start gap-2 text-sm">
          <span
            className={`mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full ${TYPE_COLOR[event.type] ?? "bg-ink-400"}`}
            aria-hidden="true"
          />
          <div className="min-w-0 flex-1">
            <p className="text-ink-100">{event.message}</p>
            <p className="text-xs text-ink-500">
              {event.agent && <span className="mr-1 font-medium text-ink-400">{humanizeEnum(event.agent)}</span>}
              {formatRelativeTime(event.at)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}
