"""Splits parsed filing text into named sections (10-K items, 10-Q part/item, 8-K item codes).

Sections are found with line-start regexes, which means a table of contents (which lists every item
heading, each followed by only a page number before the next heading) produces the same regex hits as
the real body headings. To avoid mistaking the TOC for the real section, when a key is matched more than
once we keep only the occurrence with the most following text before the *next* heading of any kind --
the TOC entries lose that contest to the real, much longer sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ITEM_10K_RE = re.compile(r"^\s*item\s+(1a|1b|1c|1|2|3|4|5|6|7a|7|8|9a|9b|9)\.?\s*[-:]?\s*(.*)$", re.I)
_PART_ITEM_10Q_RE = re.compile(r"^\s*part\s+(i{1,3}|iv)\.?\s*[,.]?\s+item\s+(1a|1|2|3|4|5|6)\.?\s*[-:]?\s*(.*)$", re.I)
_ITEM_8K_RE = re.compile(r"^\s*item\s+(\d\.\d{2})\.?\s*[-:]?\s*(.*)$", re.I)

FRONT_KEY = "front"
FRONT_TITLE = "Front matter"


@dataclass
class DocumentSection:
    key: str
    title: str
    text: str
    start_offset: int


@dataclass
class _Candidate:
    key: str
    title: str
    offset: int


def _line_starts(text: str) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = []
    cursor = 0
    for line in text.split("\n"):
        starts.append((cursor, line))
        cursor += len(line) + 1  # account for the "\n" split removed
    return starts


def _match_line(line: str, form: str) -> tuple[str, str] | None:
    form_u = (form or "").upper()

    if form_u.startswith("10-Q"):
        m = _PART_ITEM_10Q_RE.match(line)
        if m:
            key = f"part{m.group(1).upper()}_item{m.group(2).upper()}"
            return key, line.strip()
        return None

    if form_u.startswith("8-K"):
        m = _ITEM_8K_RE.match(line)
        if m:
            return m.group(1), line.strip()
        return None

    # 10-K / 10-K/A and anything else falls back to the standard item pattern.
    m = _ITEM_10K_RE.match(line)
    if m:
        return m.group(1).upper(), line.strip()
    return None


def split_sections(text: str, form: str) -> list[DocumentSection]:
    candidates: list[_Candidate] = []
    for offset, line in _line_starts(text):
        if not line.strip():
            continue
        matched = _match_line(line, form)
        if matched:
            key, title = matched
            candidates.append(_Candidate(key=key, title=title, offset=offset))

    if not candidates:
        if text.strip():
            return [DocumentSection(key=FRONT_KEY, title=FRONT_TITLE, text=text, start_offset=0)]
        return []

    # Defeat table-of-contents hits: keep, per key, the occurrence with the most text before the next
    # heading of ANY key -- a TOC entry is immediately followed by another TOC entry, while a real
    # section is followed by paragraphs of body text (or the next real section, much further away).
    best: dict[str, _Candidate] = {}
    best_span: dict[str, int] = {}
    for i, cand in enumerate(candidates):
        next_offset = candidates[i + 1].offset if i + 1 < len(candidates) else len(text)
        span = next_offset - cand.offset
        if cand.key not in best_span or span > best_span[cand.key]:
            best_span[cand.key] = span
            best[cand.key] = cand

    chosen = sorted(best.values(), key=lambda c: c.offset)

    sections: list[DocumentSection] = []
    if chosen[0].offset > 0:
        front_text = text[: chosen[0].offset]
        if front_text.strip():
            sections.append(DocumentSection(key=FRONT_KEY, title=FRONT_TITLE, text=front_text, start_offset=0))

    for i, cand in enumerate(chosen):
        end = chosen[i + 1].offset if i + 1 < len(chosen) else len(text)
        section_text = text[cand.offset : end]
        sections.append(DocumentSection(key=cand.key, title=cand.title, text=section_text, start_offset=cand.offset))

    return sections
