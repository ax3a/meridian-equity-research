/**
 * Parsing for inline citation markers of the form `[ev_xxxxxxxxxxxxxxxx]` embedded in
 * `ReportParagraph.text` (see `backend/src/meridian/schemas/report.py`). Evidence ids are produced by
 * `stable_id("ev", ...)` (`backend/src/meridian/core/ids.py`): the literal prefix `ev_` followed by 16
 * lowercase hex characters by default. The matcher accepts a slightly wider length range so it keeps
 * working if that length ever changes, but never matches loose brackets that aren't a well-formed
 * evidence id (e.g. an unclosed `[ev_123`, an empty `[ev_]`, or arbitrary bracketed text).
 */

const CITATION_PATTERN = /\[(ev_[0-9a-f]{6,40})\]/gi;

export interface CitationTextSegment {
  type: "text";
  value: string;
}

export interface CitationMarkerSegment {
  type: "citation";
  /** The referenced evidence id, e.g. "ev_1a2b3c4d5e6f7890". */
  evidenceId: string;
  /** The original matched text, e.g. "[ev_1a2b3c4d5e6f7890]". */
  raw: string;
}

export type CitationSegment = CitationTextSegment | CitationMarkerSegment;

/**
 * Split paragraph text into alternating plain-text and citation-marker segments, in order. Text with no
 * markers returns a single text segment. Empty input returns an empty array. Malformed markers (missing
 * brackets, too-short ids, non-hex characters) are left untouched as ordinary text.
 */
export function parseCitationMarkers(text: string): CitationSegment[] {
  if (!text) return [];
  const segments: CitationSegment[] = [];
  let lastIndex = 0;
  const pattern = new RegExp(CITATION_PATTERN);
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    const raw = match[0];
    const evidenceId = match[1];
    if (!evidenceId) break; // unreachable given the pattern's single capturing group, but keeps TS happy
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: text.slice(lastIndex, match.index) });
    }
    segments.push({ type: "citation", evidenceId: evidenceId.toLowerCase(), raw });
    lastIndex = match.index + raw.length;
    // Guard against zero-width matches looping forever (not reachable with this pattern, but cheap safety).
    if (raw.length === 0) pattern.lastIndex += 1;
  }
  if (lastIndex < text.length) {
    segments.push({ type: "text", value: text.slice(lastIndex) });
  }
  return segments;
}

/** All evidence ids referenced by inline markers in `text`, in order of first appearance, deduplicated. */
export function extractEvidenceIds(text: string): string[] {
  const seen = new Set<string>();
  for (const segment of parseCitationMarkers(text)) {
    if (segment.type === "citation") seen.add(segment.evidenceId);
  }
  return [...seen];
}

/** Remove citation markers entirely, collapsing any resulting double spaces. Useful for plain-text export. */
export function stripCitationMarkers(text: string): string {
  return text.replace(CITATION_PATTERN, "").replace(/[ \t]{2,}/g, " ").trim();
}

/**
 * Assigns a stable 1-based footnote number to each evidence id, in order of first appearance across
 * `texts` (e.g. every paragraph in a report, in document order). Used to render citation markers as
 * numbered superscripts (like a print bibliography) rather than raw ids.
 */
export function buildCitationOrder(texts: string[]): Map<string, number> {
  const order = new Map<string, number>();
  let next = 1;
  for (const text of texts) {
    for (const id of extractEvidenceIds(text)) {
      if (!order.has(id)) {
        order.set(id, next);
        next += 1;
      }
    }
  }
  return order;
}
