"use client";

import type { Citation } from "@/lib/types";
import { SnapshotBadge } from "@/components/ui/Badges";

interface CitationDrawerProps {
  citation: Citation | null;
  index?: number;
  onClose: () => void;
}

/** Slide-over panel showing a citation's title, publisher, location, quote, link and snapshot badge. */
export function CitationDrawer({ citation, index, onClose }: CitationDrawerProps) {
  if (!citation) return null;

  return (
    <div className="no-print fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label="Citation detail">
      <button type="button" aria-label="Close citation panel" className="flex-1 bg-black/60" onClick={onClose} />
      <div className="flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-ink-700 bg-ink-900 p-5 shadow-2xl">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <p className="text-xs uppercase tracking-wide text-ink-400">Citation{index ? ` #${index}` : ""}</p>
            <h3 className="mt-0.5 text-lg font-semibold leading-snug text-ink-50">{citation.source_title}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1.5 text-ink-400 transition hover:bg-ink-800 hover:text-ink-100"
          >
            <svg viewBox="0 0 20 20" className="h-5 w-5 fill-current" aria-hidden="true">
              <path d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L8.94 10l-4.72 4.72a.75.75 0 1 0 1.06 1.06L10 11.06l4.72 4.72a.75.75 0 1 0 1.06-1.06L11.06 10l4.72-4.72a.75.75 0 0 0-1.06-1.06L10 8.94 5.28 4.22Z" />
            </svg>
          </button>
        </div>

        <dl className="mb-4 space-y-2 text-sm">
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-ink-400">Publisher</dt>
            <dd className="text-right text-ink-100">{citation.publisher}</dd>
          </div>
          <div className="flex items-baseline justify-between gap-4">
            <dt className="text-ink-400">Location</dt>
            <dd className="text-right text-ink-100">{citation.location}</dd>
          </div>
          {citation.is_snapshot && (
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-400">Data</dt>
              <dd>
                <SnapshotBadge />
              </dd>
            </div>
          )}
        </dl>

        <blockquote className="mb-4 rounded-md border border-ink-700 bg-ink-950 p-3 text-sm italic leading-relaxed text-ink-200">
          &ldquo;{citation.quote}&rdquo;
        </blockquote>

        {citation.source_url && (
          <a
            href={citation.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-fit items-center gap-1 text-sm font-medium text-accent-400 hover:underline"
          >
            Open original source
            <span aria-hidden="true">&#8599;</span>
          </a>
        )}
      </div>
    </div>
  );
}
