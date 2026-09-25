"""Extracting the company a research request is about.

A request is written the way a person speaks -- "Analyse NVIDIA with particular attention to AI
infrastructure growth, margins and valuation" -- but company lookup needs a name or a ticker. Passing the
whole sentence to the directory finds nothing, so candidates are generated here, most specific first, and
each is tried against the real directory until one resolves. This runs with no LLM, because company
resolution must work in offline mode.
"""

from __future__ import annotations

import re

# Leading phrases people use to ask for research. Ordered longest-first so the longest match wins.
_LEAD_PHRASES = (
    "do a deep dive on",
    "write a report on",
    "put together a report on",
    "give me a report on",
    "tell me about",
    "what do you think about",
    "what about",
    "look into",
    "look at",
    "report on",
    "deep dive on",
    "research into",
    "analyse",
    "analyze",
    "research",
    "review",
    "evaluate",
    "assess",
    "summarise",
    "summarize",
    "cover",
    "study",
    "give me",
)
# Trailing clauses that qualify the request rather than name the company.
_TRAIL_MARKERS = (
    " with particular attention to",
    " with attention to",
    " with a focus on",
    " with focus on",
    " focusing on",
    " focused on",
    " paying attention to",
    " especially",
    " particularly",
    " including",
    " and its",
    " for the",
    " over the",
    " in terms of",
    " regarding",
    " with respect to",
    " with ",
)
_EXPLICIT_TICKER_RE = re.compile(r"(?:\$|\()([A-Za-z]{1,5})(?:\)|\b)")
_BARE_UPPER_RE = re.compile(r"(?<![\w$])([A-Z]{2,5})(?![\w.])")
# Uppercase words that are ordinary vocabulary in a research request, not the company being researched.
# Without this, "Analyse NVIDIA with attention to AI infrastructure" resolves the ticker AI (C3.ai).
_NON_TICKER_UPPERCASE = {
    "AI",
    "ML",
    "IT",
    "US",
    "USA",
    "UK",
    "EU",
    "CEO",
    "CFO",
    "CTO",
    "COO",
    "IPO",
    "ETF",
    "GDP",
    "CPI",
    "FY",
    "TTM",
    "EPS",
    "PE",
    "ROE",
    "ROA",
    "ROI",
    "FCF",
    "EBIT",
    "SEC",
    "GAAP",
    "ESG",
    "API",
    "SAAS",
    "B2B",
    "B2C",
    "R&D",
    "M&A",
    "YOY",
    "QOQ",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "NYSE",
    "DCF",
    "EV",
    "CAGR",
}
_CAPITALISED_RUN_RE = re.compile(r"\b([A-Z][\w&.'-]*(?:\s+(?:of|and|for|the)\s+[A-Z][\w&.'-]*|\s+[A-Z][\w&.'-]*)*)")
_STOPWORDS = {
    "analyse",
    "analyze",
    "research",
    "review",
    "evaluate",
    "assess",
    "report",
    "deep",
    "dive",
    "tell",
    "give",
    "look",
    "what",
    "about",
    "with",
    "and",
    "the",
    "for",
    "into",
    "summarise",
    "summarize",
    "cover",
    "study",
    "please",
    "company",
    "stock",
    "shares",
    # Corporate suffixes and generic entity words. Alone they identify nothing, but they appear in
    # thousands of SEC titles, so offering them as candidates resolves an arbitrary filer.
    "inc",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "plc",
    "holdings",
    "holding",
    "group",
    "partners",
    "capital",
    "trust",
    "industries",
    "technologies",
    "systems",
    "solutions",
    "international",
    "enterprises",
}


def _strip_lead(text: str) -> str:
    lowered = text.lower().lstrip()
    for phrase in sorted(_LEAD_PHRASES, key=len, reverse=True):
        if lowered.startswith(phrase):
            return text.lstrip()[len(phrase) :].lstrip(" ,:-")
    return text.strip()


def _strip_trail(text: str) -> str:
    lowered = text.lower()
    cut = len(text)
    for marker in _TRAIL_MARKERS:
        found = lowered.find(marker)
        if found != -1:
            cut = min(cut, found)
    trimmed = text[:cut]
    for sep in (",", ";", "?", "!", "."):
        trimmed = trimmed.split(sep)[0]
    return trimmed.strip()


def candidate_names(query: str) -> list[str]:
    """Ordered company-name/ticker candidates for `query`, most likely first, deduplicated.

    Callers try each against the company directory; the first that resolves wins. Nothing here decides
    what exists -- that is the directory's job.
    """
    candidates: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        cleaned = value.strip(" ,.:;'\"()").strip()
        if len(cleaned) < 2 or cleaned.lower() in _STOPWORDS:
            return
        if cleaned not in candidates:
            candidates.append(cleaned)

    # 1. An explicitly marked ticker ("$AAPL", "(MSFT)") is unambiguous, so it outranks everything.
    for token in _EXPLICIT_TICKER_RE.findall(query):
        if token and token.lower() not in _STOPWORDS:
            add(token.upper())

    core = _strip_trail(_strip_lead(query))
    add(core)

    # 2. Capitalised runs ("Advanced Micro Devices"), longest first. These rank ABOVE bare uppercase
    #    tokens: in "Analyse NVIDIA ... AI infrastructure", the company is the name, not the acronym.
    runs = sorted((m.group(1) for m in _CAPITALISED_RUN_RE.finditer(core or query)), key=len, reverse=True)
    for run in runs:
        add(run)

    # 3. Bare uppercase tokens that look like tickers, excluding ordinary research vocabulary.
    for token in _BARE_UPPER_RE.findall(query):
        if token.upper() not in _NON_TICKER_UPPERCASE and token.lower() not in _STOPWORDS:
            add(token.upper())

    # 4. Individual meaningful words, as a last resort before the raw query.
    for word in (core or query).split():
        if word.lower() not in _STOPWORDS:
            add(word)

    add(query.strip())
    return candidates
