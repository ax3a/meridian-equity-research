"""HTML parsing for SEC filings.

Strips script/style/noscript tags and inline-XBRL hidden blocks, converts tables to pipe-delimited
rows so numeric data survives, and collapses incidental whitespace while preserving paragraph breaks.
Also tracks page-break offsets (from `page-break-before|after` styles and `<hr>` markers) so downstream
chunking can derive a page number for citations.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

_STRIP_TAGS = {"script", "style", "noscript"}
_PARAGRAPH_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote"}
_DISPLAY_NONE_RE = re.compile(r"display\s*:\s*none", re.I)
_PAGE_BREAK_RE = re.compile(r"page-break-(before|after)\s*:\s*(always|left|right)", re.I)
_INLINE_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")


@dataclass
class ParsedDocument:
    text: str
    page_breaks: list[int] = field(default_factory=list)
    title: str | None = None


def page_for_offset(page_breaks: list[int], offset: int) -> int:
    """1-based page number for a character offset, given the recorded page-break offsets."""
    page = 1
    for brk in page_breaks:
        if offset >= brk:
            page += 1
        else:
            break
    return page


def _style_of(tag: Tag) -> str:
    style = tag.get("style")
    return style if isinstance(style, str) else ""


def _is_hidden(tag: Tag) -> bool:
    name = (tag.name or "").lower()
    if name.startswith("ix:"):
        return True
    return bool(_DISPLAY_NONE_RE.search(_style_of(tag)))


def _has_page_break(tag: Tag) -> bool:
    if (tag.name or "").lower() == "hr":
        return True
    return bool(_PAGE_BREAK_RE.search(_style_of(tag)))


class _Builder:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.length = 0
        self.page_breaks: list[int] = []

    def _append(self, text: str) -> None:
        if not text:
            return
        self.parts.append(text)
        self.length += len(text)

    def emit_text(self, raw: str) -> None:
        text = _INLINE_WHITESPACE_RE.sub(" ", raw)
        if not text or text.isspace():
            return
        if self.parts and self.parts[-1].endswith((" ", "\n")) and text.startswith(" "):
            text = text[1:]
        self._append(text)

    def paragraph_break(self) -> None:
        if not self.parts:
            return
        if self.parts[-1].endswith("\n\n"):
            return
        if self.parts[-1].endswith("\n"):
            self._append("\n")
        else:
            self._append("\n\n")

    def line_break(self) -> None:
        if not self.parts or self.parts[-1].endswith("\n"):
            return
        self._append("\n")

    def mark_page_break(self) -> None:
        if self.length > 0 and (not self.page_breaks or self.page_breaks[-1] != self.length):
            self.page_breaks.append(self.length)


def _cell_text(cell: Tag) -> str:
    text = cell.get_text(" ", strip=True)
    return _INLINE_WHITESPACE_RE.sub(" ", text).strip()


def _walk_table(table: Tag, builder: _Builder) -> None:
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        line = " | ".join(_cell_text(c) for c in cells)
        if line.strip(" |"):
            builder.line_break()
            builder.emit_text(line)


def _walk(node: Tag, builder: _Builder) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            builder.emit_text(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = (child.name or "").lower()
        if name in _STRIP_TAGS:
            continue
        if _is_hidden(child):
            continue
        if _has_page_break(child):
            builder.mark_page_break()
        if name == "table":
            builder.paragraph_break()
            _walk_table(child, builder)
            builder.paragraph_break()
            continue
        if name == "br":
            builder.line_break()
            continue
        if name in _PARAGRAPH_TAGS:
            builder.paragraph_break()
            _walk(child, builder)
            builder.paragraph_break()
        else:
            _walk(child, builder)


def parse_filing_html(html: str) -> ParsedDocument:
    # EDGAR serves a mix of HTML and XML-declared XHTML; the HTML parser handles both, and warning
    # about it on every filing would drown out real log output.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(list(_STRIP_TAGS)):
        tag.decompose()

    title: str | None = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip() or None

    root = soup.body or soup
    builder = _Builder()
    _walk(root, builder)

    text = "".join(builder.parts).rstrip()
    return ParsedDocument(text=text, page_breaks=builder.page_breaks, title=title)
