"use client";

import { parseCitationMarkers } from "@/lib/citations";

interface CitationTextProps {
  text: string;
  /** Evidence id -> report-wide footnote number, from `buildCitationOrder`. */
  citationIndex: Map<string, number>;
  /** Ids that resolve to a real `Citation` in `report.citations`, so a dangling marker renders disabled. */
  knownEvidenceIds: Set<string>;
  onCite: (evidenceId: string) => void;
}

/**
 * Renders paragraph text with inline `[ev_xxx]` markers replaced by numbered superscript buttons that
 * open the citation drawer. Everything else is rendered as plain text nodes (React escapes it) — the API
 * string is treated as untrusted content throughout, never as HTML.
 */
export function CitationText({ text, citationIndex, knownEvidenceIds, onCite }: CitationTextProps) {
  const segments = parseCitationMarkers(text);
  return (
    <>
      {segments.map((segment, i) => {
        if (segment.type === "text") return <span key={i}>{segment.value}</span>;
        const known = knownEvidenceIds.has(segment.evidenceId);
        const number = citationIndex.get(segment.evidenceId);
        return (
          <button
            key={i}
            type="button"
            onClick={() => known && onCite(segment.evidenceId)}
            disabled={!known}
            aria-label={known ? `View citation ${number ?? ""}` : "Citation not found in this report"}
            title={known ? "View source" : "Citation not found"}
            className={`mx-0.5 inline-flex h-4 min-w-[1rem] -translate-y-1.5 items-center justify-center rounded px-1 align-baseline text-[10px] font-semibold leading-none ${
              known
                ? "bg-accent-600/25 text-accent-400 hover:bg-accent-600/50 cursor-pointer"
                : "cursor-not-allowed bg-ink-700 text-ink-400"
            }`}
          >
            {number ?? "?"}
          </button>
        );
      })}
    </>
  );
}
