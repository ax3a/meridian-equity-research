from __future__ import annotations

from meridian.rag.parsing import parse_filing_html

from .conftest import read_fixture


def test_strips_script_style_and_title_extracted() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    assert "trackingPixel" not in parsed.text
    assert "should not appear in parsed text" not in parsed.text
    assert "font-family" not in parsed.text
    assert parsed.title == "Acme Corp 10-K"


def test_strips_inline_xbrl_hidden_block() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    assert "SECRET INLINE XBRL METADATA" not in parsed.text
    assert "EntityRegistrantName" not in parsed.text


def test_strips_display_none_elements() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    assert "HIDDEN RISK NOTE" not in parsed.text


def test_table_numbers_survive_as_pipe_rows() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    assert "482.6" in parsed.text
    assert "210.4" in parsed.text
    # header + data cells pipe-delimited on one line
    assert "Net Sales | Gross Profit | Net Income" in parsed.text
    assert "2025 | 482.6 | 210.4 | 58.9" in parsed.text


def test_real_content_present() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    assert "Item 1A. Risk Factors" in parsed.text
    assert "industrial automation market" in parsed.text


def test_page_breaks_recorded_and_ordered() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    assert len(parsed.page_breaks) >= 1
    assert parsed.page_breaks == sorted(parsed.page_breaks)
    # the *real* Risk Factors heading (not the earlier table-of-contents mention) sits right after the
    # page break marker in the fixture.
    real_risk_offset = parsed.text.index("Item 1A. Risk Factors", parsed.text.index("over the next several years"))
    assert any(b <= real_risk_offset for b in parsed.page_breaks)


def test_whitespace_collapsed_but_paragraphs_kept() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    for line in parsed.text.split("\n"):
        assert "  " not in line, f"double space survived in line: {line!r}"
    assert "\n" in parsed.text
