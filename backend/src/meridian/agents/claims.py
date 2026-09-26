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
# A chunk often starts on its own section heading ("Item 1. Business General Target Corporation was
# incorporated..."). The heading is already carried by the citation, so quoting it back adds nothing.
_ITEM_TITLES = (
    "business",
    "risk factors",
    "unresolved staff comments",
    "cybersecurity",
    "properties",
    "legal proceedings",
    "mine safety disclosures",
    "selected financial data",
    # Filings use a curly apostrophe about as often as a straight one.
    r"management[’']s discussion and analysis"  # noqa: RUF001
    r"(?:\s+of\s+financial\s+condition)?(?:\s+and\s+results\s+of\s+operations)?",
    "quantitative and qualitative disclosures about market risk",
    r"financial statements(?:\s+and\s+supplementary\s+data)?",
    "controls and procedures",
    "other information",
)
_LEADING_ITEM_HEADING_RE = re.compile(
    # The en and em dashes are deliberate: filings really do write "Item 1—Business".
    r"^item\s+\d{1,2}[A-C]?\s*[.:|—–-]?\s*(?:" + "|".join(_ITEM_TITLES) + r")?\s*[.:|—–-]?\s*",  # noqa: RUF001
    re.IGNORECASE,
)
# A passage that is nothing but a section title, with or without its item number. These survive the word
# count -- "Management's Discussion and Analysis of Financial Condition and Results of Operations." is
# thirteen words of pure heading -- so they are rejected by shape instead.
_HEADING_ONLY_RE = re.compile(
    r"^(?:item\s+\d{1,2}[A-C]?\s*[.:|—–-]?\s*)?(?:" + "|".join(_ITEM_TITLES) + r")\s*[.:]?$",  # noqa: RUF001
    re.IGNORECASE,
)

DEFAULT_MAX_CHARS = 260
# Below this, what is left after cleaning is a heading or a stub rather than a quotable statement. A
# real run published the claim "Segment disclosure: Item 7." -- true, cited, and entirely uninformative.
MIN_CLAIM_WORDS = 8
# At or above this many cell separators the passage is a flattened table, not a sentence.
MAX_CLAIM_PIPES = 3
# A chunk that starts inside a financial table carries its last cells into the claim ("Segment
# disclosure: 32.0 | % | | 36.4 | % 1Income tax adjustment is defined as..."). The lookahead requires a
# pipe before the first letter, so a passage that simply opens with a figure ("2025 revenue rose") is
# left alone; only a genuine run of table cells is removed.
_LEADING_TABLE_CELLS_RE = re.compile(r"^(?=[^A-Za-z]*\|)[\d\s.,()$%|+\-–—]*")  # noqa: RUF001


def clean_passage(text: str) -> str:
    """Normalise whitespace, drop a leading "[section]" tag and collapse repeated shouty headings."""
    cleaned = _SECTION_PREFIX_RE.sub("", text or "")
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    cleaned = _SHOUTY_RUN_RE.sub(r"\1", cleaned)
    cleaned = _LEADING_ITEM_HEADING_RE.sub("", cleaned)
    cleaned = _LEADING_TABLE_CELLS_RE.sub("", cleaned)
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
    remainder = text[match.end() :].strip()
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


def is_quotable(passage: str) -> bool:
    """False when a passage reduces to a section heading, a table or a stub once cleaned.

    Quoting one produces a finding that is accurate and cited but says nothing, which costs a reader
    attention and makes the evidence chain look padded.
    """
    body = summarize_passage(passage)
    if _HEADING_ONLY_RE.match(body):
        return False
    # A whole chunk of table, flattened into one line ("Debt Ratings | S&P | | Moody's | A-2 | | P-2").
    # Prose does not carry this many cell separators, and the figures are already available as metrics.
    if body.count("|") >= MAX_CLAIM_PIPES:
        return False
    return len(body.split()) >= MIN_CLAIM_WORDS


def describe_claim(label: str, passage: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Compose "<label>: <sentences>", keeping the whole claim within the budget and avoiding a doubled
    label when the passage already starts with it."""
    body = summarize_passage(passage, max_chars=max(60, max_chars - len(label) - 2))
    if not body:
        return label
    if body.lower().startswith(label.lower()):
        return body
    return f"{label}: {body}"
