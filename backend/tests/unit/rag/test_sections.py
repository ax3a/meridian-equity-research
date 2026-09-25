from __future__ import annotations

from meridian.rag.parsing import parse_filing_html
from meridian.rag.sections import split_sections

from .conftest import read_fixture


def test_10k_section_keys_present() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    sections = split_sections(parsed.text, "10-K")
    keys = [s.key for s in sections]
    assert "1" in keys
    assert "1A" in keys
    assert "7" in keys
    assert "8" in keys


def test_toc_is_not_mistaken_for_a_section() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    sections = split_sections(parsed.text, "10-K")
    by_key = {s.key: s for s in sections}
    # the chosen "1A" section must be the real, long risk-factors body, not the one-line TOC entry
    risk = by_key["1A"]
    assert "high degree of risk" in risk.text
    assert "Risk Factors .......... 5" not in risk.text
    assert len(risk.text) > 200


def test_section_text_does_not_bleed_into_next_section() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    sections = split_sections(parsed.text, "10-K")
    by_key = {s.key: s for s in sections}
    assert "Management's Discussion and Analysis" not in by_key["1A"].text
    assert "high degree of risk" not in by_key["7"].text


def test_section_title_and_offsets() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    sections = split_sections(parsed.text, "10-K")
    by_key = {s.key: s for s in sections}
    assert by_key["1A"].title == "Item 1A. Risk Factors"
    assert by_key["1A"].start_offset == parsed.text.index("Item 1A. Risk Factors", by_key["1"].start_offset + 1)


def test_front_matter_captured() -> None:
    parsed = parse_filing_html(read_fixture("sample_10k.html"))
    sections = split_sections(parsed.text, "10-K")
    front = next(s for s in sections if s.key == "front")
    assert "ANNUAL REPORT ON FORM 10-K" in front.text


def test_10q_part_item_keys() -> None:
    parsed = parse_filing_html(read_fixture("sample_10q.html"))
    sections = split_sections(parsed.text, "10-Q")
    keys = {s.key for s in sections}
    assert "partI_item1" in keys
    assert "partI_item2" in keys
    assert "partII_item1" in keys


def test_8k_item_code_keys() -> None:
    parsed = parse_filing_html(read_fixture("sample_8k.html"))
    sections = split_sections(parsed.text, "8-K")
    keys = {s.key for s in sections}
    assert "2.02" in keys
    assert "9.01" in keys
    by_key = {s.key: s for s in sections}
    assert "Net sales for the quarter" in by_key["2.02"].text
