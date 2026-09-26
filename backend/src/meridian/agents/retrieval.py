"""Section-scoped filing retrieval shared by the specialist agents.

Agents quote a retrieved passage under a topical label ("Products and services: ...", "Segment
disclosure: ..."). That label is the *search query's* topic, not a property of the passage, so an
unscoped search makes it a claim the evidence may not support: a run labelled Walmart's litigation
matters "Products and services" and its reputation risk factor a "Segment disclosure", purely because
those passages were the best hits for those queries across the whole filing.

`search_filings` accepts a `section_keys` filter, which makes the label defensible -- text from Item 1A
really is a risk factor. Scoping can also return nothing (section detection fails on some filings, and
a company may have no 10-K indexed), so this falls back to an unscoped search and reports that it did.
Callers use a neutral label for unscoped results rather than asserting a topic they cannot stand behind.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from meridian.tools.base import ToolContext


def unscoped_label(topic: str) -> str:
    """Label for a passage retrieved without a section filter.

    Says only what is known -- that the passage matched a search for `topic` -- instead of asserting it
    *is* that topic. It stays distinct per topic on purpose: citation validation deduplicates findings on
    claim text alone, so a single shared label would silently drop every unscoped claim but the first.
    """
    return f'Filing excerpt matching "{topic}"'


async def search_sections(
    agent: Any,
    ctx: ToolContext,
    *,
    ticker: str,
    query: str,
    k: int,
    section_keys: Sequence[str],
) -> tuple[list[Any], bool]:
    """Search `section_keys` first, falling back to an unscoped search over all indexed filings.

    Returns `(passages, scoped)`. `scoped` is False when the fallback ran, meaning the caller must not
    claim the passage came from the section its query was aimed at.
    """
    if section_keys:
        inv = await agent.tool(ctx, "search_filings", ticker=ticker, query=query, k=k, section_keys=list(section_keys))
        if inv.ok and inv.output is not None and inv.output.passages:
            return list(inv.output.passages), True

    inv = await agent.tool(ctx, "search_filings", ticker=ticker, query=query, k=k)
    passages = list(inv.output.passages) if inv.ok and inv.output is not None else []
    return passages, False
