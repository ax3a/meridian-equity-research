import { formatDate } from "@/lib/format";
import type { Confidence, FindingKind } from "@/lib/types";

const KIND_LABEL: Record<FindingKind, string> = {
  fact: "Fact",
  calculated: "Calculated",
  interpretation: "Interpretation",
};

const KIND_CLASSES: Record<FindingKind, string> = {
  fact: "border-fact/50 bg-fact/15 text-fact",
  calculated: "border-calculated/50 bg-calculated/15 text-calculated",
  interpretation: "border-interpretation/50 bg-interpretation/15 text-interpretation",
};

const KIND_DESCRIPTION: Record<FindingKind, string> = {
  fact: "A sourced fact, traceable to at least one piece of evidence.",
  calculated: "A deterministic calculation from the financial engine, traceable to a metric.",
  interpretation: "An agent's interpretation or judgement call — may be wrong, treat as opinion.",
};

/** Distinguishes Fact / Calculated / Interpretation content, per the report's core trust model. */
export function ContentKindBadge({ kind, unverified = false }: { kind: FindingKind; unverified?: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1 align-middle">
      <span
        title={KIND_DESCRIPTION[kind]}
        className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${KIND_CLASSES[kind]}`}
      >
        {KIND_LABEL[kind]}
      </span>
      {unverified && (
        <span
          title="This claim could not be fully verified against evidence and should be treated with caution."
          className="rounded border border-danger/50 bg-danger/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-danger"
        >
          Unverified
        </span>
      )}
    </span>
  );
}

const CONFIDENCE_CLASSES: Record<Confidence, string> = {
  low: "border-ink-500 text-ink-300",
  medium: "border-accent-500/50 text-accent-400",
  high: "border-emerald-500/50 text-emerald-400",
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${CONFIDENCE_CLASSES[confidence]}`}>
      {confidence} confidence
    </span>
  );
}

/** Marks data that came from a recorded snapshot rather than a live provider fetch. Never omit this when true. */
export function SnapshotBadge({ date }: { date?: string | null }) {
  return (
    <span
      title="This data is a recorded snapshot, not a live fetch from the provider."
      className="inline-flex items-center gap-1 rounded-full border border-ink-500 bg-ink-800 px-2 py-0.5 text-xs font-medium text-ink-200"
    >
      <svg viewBox="0 0 16 16" className="h-3 w-3 fill-current" aria-hidden="true">
        <path d="M8 1a1 1 0 0 1 1 1v5.586l3.707 3.707a1 1 0 0 1-1.414 1.414l-4-4A1 1 0 0 1 7 8V2a1 1 0 0 1 1-1Z" />
      </svg>
      Snapshot{date ? ` · ${formatDate(date)}` : ""}
    </span>
  );
}
