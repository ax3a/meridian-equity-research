"""Helpers for turning retrieved passages into readable claims.

Retrieved chunks are long, start mid-sentence and end mid-word. Quoting one verbatim as a claim produces
report prose like "[risk factors] RISK RISKS We are exposed to ... diversified among indu." — accurate but
unreadable. These helpers cut a passage down to whole sentences without inventing anything: the full text
stays available as the cited evidence, so nothing is lost.
"""

from __future__ import annotations

import re

_SECTION_PREFIX_RE = re.compile(r"^\s*\[[^\]]{1,60}\]\s*")
_WS_RE = re.compile(r"\s+")
# Sentence end: ., ! or ? followed by whitespace and a capital/quote/digit, not preceded by an abbreviation.
_SENTENCE_END_RE = re.compile(r"(?<![A-Z])[.!?](?=\s+[\"'(A-Z0-9])")
_SHOUTY_RUN_RE = re.compile(r"\b([A-Z]{3,})(\s+\1\b)+")
# Filings stack section headings ("RISK RISKS We are exposed to...") — drop a leading all-caps run when
# ordinary prose follows it, since the heading is noise once the passage is quoted as a claim.
_LEADING_HEADING_RE = re.compile(r"^(?:[A-Z][A-Z&/'\-]{2,}[.,]?\s+){1,6}(?=[A-Z][a-z])")

DEFAULT_MAX_CHARS = 260


def clean_passage(text: str) -> str:
    """Normalise whitespace, drop a leading "[section]" tag and collapse repeated shouty headings."""
    cleaned = _SECTION_PREFIX_RE.sub("", text or "")
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    cleaned = _SHOUTY_RUN_RE.sub(r"\1", cleaned)
    return _LEADING_HEADING_RE.sub("", cleaned).strip()


def _drop_leading_fragment(text: str) -> str:
    """Skip a partial opening sentence.

    Retrieved chunks are cut at a token boundary, so they often begin mid-thought ("successful, and we
    may fail to sell..."). Starting a claim there reads as broken. If the text does not begin like a
    sentence and a later sentence boundary leaves enough material, start from that instead.
    """
    if not text or text[0].isupper() or text[0].isdigit() or text[0] in "\"'(":
        return text
    match = _SENTENCE_END_RE.search(text)
    if match is None:
        return text
    remainder = text[match.end():].strip()
    return remainder if len(remainder) >= 80 else text


def summarize_passage(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Return whole sentences from `text`, never exceeding `max_chars` and never cut mid-word.

    Prefers complete sentences; falls back to a word boundary with an ellipsis when the first sentence is
    itself longer than the budget.
    """
    cleaned = _drop_leading_fragment(clean_passage(text))
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    ends = [m.end() for m in _SENTENCE_END_RE.finditer(cleaned) if m.end() <= max_chars]
    if ends:
        return cleaned[: ends[-1]].strip()

    clipped = cleaned[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:")
    return f"{clipped}..."


def describe_claim(label: str, passage: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Compose "<label>: <sentences>", keeping the whole claim within the budget and avoiding a doubled
    label when the passage already starts with it."""
    body = summarize_passage(passage, max_chars=max(60, max_chars - len(label) - 2))
    if not body:
        return label
    if body.lower().startswith(label.lower()):
        return body
    return f"{label}: {body}"
