"""Splits a `DocumentSection` into token-bounded chunks.

Chunking never crosses a section boundary (it operates on a single section's text only). Content is
split on paragraph boundaries first; any paragraph that alone exceeds `target_tokens` is further split
on sentence boundaries. Chunks are filled greedily up to `target_tokens`, and the trailing
`overlap_tokens` worth of words from a chunk is carried into the start of the next chunk so retrieval
doesn't lose context at a chunk boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from meridian.rag.sections import DocumentSection

_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"\S+")
_PARAGRAPH_SPLIT_RE = re.compile(r"(\n\s*\n)")

_TOKENS_PER_WORD = 1.3


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


def _take_overlap_words(text: str, overlap_tokens: int) -> str:
    if overlap_tokens <= 0:
        return ""
    words = text.split()
    n = max(0, round(overlap_tokens / _TOKENS_PER_WORD))
    if n == 0 or not words:
        return ""
    return " ".join(words[-n:])


def chunk_section(section: DocumentSection, *, target_tokens: int = 350, overlap_tokens: int = 50) -> list[ChunkDraft]:
    units: list[tuple[str, int]] = []
    for para_text, para_offset in _split_paragraphs(section.text):
        if estimate_tokens(para_text) > target_tokens:
            units.extend(_split_sentences(para_text, para_offset))
        else:
            units.append((para_text, para_offset))

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
        carry = _take_overlap_words(text, overlap_tokens)
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
