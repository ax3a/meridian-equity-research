import type { LlmMode } from "@/lib/types";

/** Shown whenever a run/report was produced by the deterministic offline model, never a live LLM. */
export function OfflineLlmBanner() {
  return (
    <div
      role="status"
      className="border-b border-amber-500/40 bg-amber-500/10 px-4 py-2 text-center text-sm text-amber-300"
    >
      <strong className="font-semibold">Offline LLM mode.</strong> This content was produced by Meridian&rsquo;s
      deterministic offline model, not a live Anthropic model. Narrative sections are template-based.
    </div>
  );
}

/** Shown whenever a run/report used recorded snapshot data instead of a live provider fetch. */
export function SnapshotDataBanner() {
  return (
    <div role="status" className="border-b border-ink-500/40 bg-ink-800 px-4 py-2 text-center text-sm text-ink-200">
      <strong className="font-semibold">Snapshot data.</strong> This run used recorded snapshot fixtures instead of
      live provider fetches. Figures may not reflect current reality.
    </div>
  );
}

interface ModeBannersProps {
  llmMode?: LlmMode | string | null;
  usesSnapshotData?: boolean;
}

/** Convenience wrapper: renders whichever mode banners apply, or nothing. Never claim snapshot data is live. */
export function ModeBanners({ llmMode, usesSnapshotData }: ModeBannersProps) {
  return (
    <>
      {llmMode === "offline" && <OfflineLlmBanner />}
      {usesSnapshotData && <SnapshotDataBanner />}
    </>
  );
}

export function Disclaimer({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-900 p-4 text-sm leading-relaxed text-ink-300">
      <p className="mb-1 font-semibold text-ink-100">Not investment advice</p>
      <p>{text}</p>
    </div>
  );
}
