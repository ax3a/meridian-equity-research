"use client";

import { useState } from "react";
import type { SourceView } from "@/lib/types";
import { formatDate, humanizeEnum } from "@/lib/format";
import { SnapshotBadge } from "@/components/ui/Badges";

function describeLocator(evidence: SourceView["evidence"][number]): string {
  const loc = evidence.locator;
  const parts = [
    loc.section ? `section ${loc.section}` : null,
    loc.page ? `p.${loc.page}` : null,
    loc.xbrl_concept ? `XBRL ${loc.xbrl_concept}` : null,
    loc.period ? `period ${loc.period}` : null,
    loc.accession_number ? `accession ${loc.accession_number}` : null,
  ].filter((p): p is string => Boolean(p));
  return parts.length > 0 ? parts.join(", ") : "document";
}

/** One expandable source: its evidence excerpts and the findings that cite it. */
export function SourceCard({ sourceView }: { sourceView: SourceView }) {
  const [open, setOpen] = useState(false);
  const { source, evidence, cited_by_findings } = sourceView;

  return (
    <div className="rounded-lg border border-ink-700">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-3 p-3 text-left"
      >
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-ink-100">{source.title}</span>
            <span className="rounded border border-ink-600 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-400">
              {humanizeEnum(source.kind)}
            </span>
            {source.is_snapshot && <SnapshotBadge date={source.snapshot_date} />}
          </div>
          <p className="mt-1 text-xs text-ink-400">
            {source.publisher} · {source.provider}
            {source.published_at && ` · ${formatDate(source.published_at)}`}
          </p>
        </div>
        <span className="text-ink-400" aria-hidden="true">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && (
        <div className="border-t border-ink-800 p-3">
          {source.url && (
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mb-3 inline-flex text-sm font-medium text-accent-400 hover:underline"
            >
              Open source <span aria-hidden="true">&#8599;</span>
            </a>
          )}
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">
            Evidence ({evidence.length})
          </p>
          {evidence.length === 0 ? (
            <p className="mb-3 text-sm text-ink-500">No evidence excerpts recorded for this source.</p>
          ) : (
            <ul className="mb-3 space-y-2">
              {evidence.map((e) => (
                <li key={e.id} className="rounded-md border border-ink-800 bg-ink-950 p-2 text-sm text-ink-200">
                  <p className="italic">&ldquo;{e.text}&rdquo;</p>
                  <p className="mt-1 text-xs text-ink-500">{describeLocator(e)}</p>
                  {e.injection_flags.length > 0 && (
                    <p className="mt-1 text-xs text-amber-400">Flagged: {e.injection_flags.join(", ")}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-400">
            Cited by findings ({cited_by_findings.length})
          </p>
          {cited_by_findings.length === 0 ? (
            <p className="text-sm text-ink-500">Not cited by any finding yet.</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {cited_by_findings.map((id) => (
                <span key={id} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[10px] text-ink-300">
                  {id}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
