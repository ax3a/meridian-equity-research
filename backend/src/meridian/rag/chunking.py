"""Splits a `DocumentSection` into token-bounded chunks.

Chunking never crosses a section boundary (it operates on a single section's text only). Content is
split on paragraph boundaries first; any paragraph that alone exceeds `target_tokens` is further split
on sentence boundaries. Chunks are filled greedily up to `target_tokens`, and the trailing
`overlap_tokens` worth of words from a chunk is carried into the start of the next chunk so retrieval
doesn't lose context at a chunk boundary.

Navigation furniture is removed before any of that. EDGAR HTML repeats a "Table of Contents" link at
every page break, so extracted text collects runs like "7 Table of Contents Note 1. Note 2. 8 Table of
Contents Note 3." Those runs get indexed like any other text and, being dense in filing vocabulary,
score well against topical queries -- a real run reached a report as a cited fact. They are stripped
here rather than at retrieval time so they never become evidence in the first place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from meridian.rag.sections import DocumentSection

# Splitting on every ".!? + space" treats "our U.S. liquidity requirements" as two sentences, and the
# second one then opens a chunk mid-thought. Require the next character to look like a sentence start,
# and refuse to break after a single-letter abbreviation ("U.S.", "No.", "v.").
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<![A-Z]\.)(?<=[.!?])\s+(?=[\"'(A-Z0-9])")
_WORD_RE = re.compile(r"\S+")
_PARAGRAPH_SPLIT_RE = re.compile(r"(\n\s*\n)")

_TOKENS_PER_WORD = 1.3

# The page-break link EDGAR emits, plus any page number sitting immediately either side of it.
_NAVIGATION_RE = re.compile(r"\s*\d{0,4}\s*\btable\s+of\s+contents\b\s*\d{0,4}\s*", re.IGNORECASE)
# A "sentence" shorter than this is a heading, a page number or a cross-reference, not prose.
_MIN_PROSE_WORDS = 8
# Below this many sentences there is too little signal to judge, so the unit is kept.
_MIN_SENTENCES_TO_JUDGE = 3
# Above this share of fragments the unit is navigation furniture rather than a paragraph.
_MAX_FRAGMENT_RATIO = 0.6


@dataclass
class ChunkDraft:
    index: int
    text: str
    token_count: int
    start_offset: int


def estimate_tokens(text: str) -> int:
    """Word-count based token estimate (~1.3 tokens/word), so tests never need a real tokenizer."""
    words = len(_WORD_RE.findall(text))
    if words == 0:
        return 0
    return max(1, round(words * _TOKENS_PER_WORD))


def strip_navigation(text: str) -> str:
    """Remove EDGAR page-break navigation links and the page numbers attached to them."""
    return _NAVIGATION_RE.sub(" ", text).strip()


def is_navigation_noise(text: str) -> bool:
    """True when `text` is a run of headings, page numbers and cross-references rather than prose.

    Judged on the share of sentences too short to be prose: a table-of-contents run is almost entirely
    fragments ("Note 3.", "11", "Item 1A."), while a real paragraph is mostly whole sentences. Short
    inputs are never rejected -- a two-sentence paragraph carries too little signal to judge, and
    discarding real disclosure is a far worse failure than keeping some furniture.
    """
    sentences = [s for s in _SENTENCE_BOUNDARY_RE.split(text) if s.strip()]
    if len(sentences) < _MIN_SENTENCES_TO_JUDGE:
        return False
    fragments = sum(1 for s in sentences if len(_WORD_RE.findall(s)) < _MIN_PROSE_WORDS)
    return fragments / len(sentences) > _MAX_FRAGMENT_RATIO


def _split_paragraphs(text: str) -> list[tuple[str, int]]:
    """Return (paragraph_text, offset_within_text) pairs, skipping blank separators."""
    result: list[tuple[str, int]] = []
    cursor = 0
    for part in _PARAGRAPH_SPLIT_RE.split(text):
        if part == "":
            continue
        if _PARAGRAPH_SPLIT_RE.fullmatch(part):
            cursor += len(part)
            continue
        stripped = part.strip()
        if stripped:
            local_idx = part.find(stripped)
            # A paragraph opening lower-case is the tail of the previous one: HTML extraction inserts
            # breaks mid-sentence at line, cell and page boundaries, and a bullet list has no sentence
            # punctuation to recover from. Rejoining keeps the pieces together as one unit so a chunk
            # cannot begin part-way through a thought. The offset stays that of the opening piece, so
            # cited evidence still points at where the passage starts in the filing.
            if result and stripped[:1].islower():
                previous_text, previous_offset = result[-1]
                result[-1] = (f"{previous_text} {stripped}", previous_offset)
            else:
                result.append((stripped, cursor + local_idx))
        cursor += len(part)
    return result


def _split_sentences(text: str, base_offset: int) -> list[tuple[str, int]]:
    """Return (sentence_text, absolute_offset) pairs for one paragraph's text."""
    result: list[tuple[str, int]] = []
    last = 0
    for m in _SENTENCE_BOUNDARY_RE.finditer(text):
        piece = text[last : m.start()]
        stripped = piece.strip()
        if stripped:
            idx = piece.find(stripped)
            result.append((stripped, base_offset + last + idx))
        last = m.end()
    piece = text[last:]
    stripped = piece.strip()
    if stripped:
        idx = piece.find(stripped)
        result.append((stripped, base_offset + last + idx))
    return result


def _take_overlap(text: str, overlap_tokens: int) -> str:
    """The trailing whole sentences of `text`, within the overlap budget.

    Carrying the last N *words* instead made every chunk after the first in a section begin
    mid-sentence by construction -- 62% of a real index did. That is not only unreadable when the
    passage is quoted as a claim: the chunk is embedded as it stands, so a fragment that opens
    mid-thought is also a worse vector for retrieval.

    Whole sentences serve the carry's actual purpose -- keeping a fact that straddles a boundary
    findable from either side -- just as well. When even one trailing sentence will not fit the budget
    the carry is dropped, because the next chunk then starts on a fresh unit, which is already a clean
    boundary.
    """
    if overlap_tokens <= 0 or not text.strip():
        return ""
    sentences = [s for s in _SENTENCE_BOUNDARY_RE.split(text) if s.strip()]
    taken: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        tokens = estimate_tokens(sentence)
        if total + tokens > overlap_tokens:
            break
        taken.append(sentence)
        total += tokens
    return " ".join(reversed(taken)).strip()


def chunk_section(section: DocumentSection, *, target_tokens: int = 350, overlap_tokens: int = 50) -> list[ChunkDraft]:
    units: list[tuple[str, int]] = []
    for para_text, para_offset in _split_paragraphs(section.text):
        if estimate_tokens(para_text) > target_tokens:
            units.extend(_split_sentences(para_text, para_offset))
        else:
            units.append((para_text, para_offset))

    # Offsets still point into the original section text, so cited evidence stays locatable in the filing.
    units = [
        (stripped, offset)
        for stripped, offset in ((strip_navigation(text), offset) for text, offset in units)
        if stripped and not is_navigation_noise(stripped)
    ]

    if not units:
        return []

    drafts: list[ChunkDraft] = []
    current: list[str] = []
    current_tokens = 0
    current_start: int | None = None
    carry = ""

    def flush() -> None:
        nonlocal current, current_tokens, current_start, carry
        if not current:
            return
        pieces = ([carry] if carry else []) + current
        text = " ".join(pieces).strip()
        start = section.start_offset + (current_start if current_start is not None else 0)
        drafts.append(ChunkDraft(index=len(drafts), text=text, token_count=estimate_tokens(text), start_offset=start))
        carry = _take_overlap(text, overlap_tokens)
        current = []
        current_tokens = 0
        current_start = None

    for unit_text, unit_offset in units:
        unit_tokens = estimate_tokens(unit_text)
        if current and current_tokens + unit_tokens > target_tokens:
            flush()
        if current_start is None:
            current_start = unit_offset
        current.append(unit_text)
        current_tokens += unit_tokens

    flush()
    return drafts
