from __future__ import annotations

from meridian.rag.chunking import chunk_section, estimate_tokens, is_navigation_noise, strip_navigation
from meridian.rag.sections import DocumentSection


def test_estimate_tokens_word_based() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("one two three four") == round(4 * 1.3)


def test_short_section_yields_single_chunk() -> None:
    section = DocumentSection(
        key="1", title="Item 1. Business", text="A short paragraph of business text.", start_offset=100
    )
    drafts = chunk_section(section, target_tokens=350, overlap_tokens=50)
    assert len(drafts) == 1
    assert drafts[0].index == 0
    assert drafts[0].text.strip() == section.text.strip()
    assert drafts[0].start_offset == 100


def test_long_section_splits_into_multiple_chunks_with_overlap() -> None:
    paragraphs = [f"Sentence number {i} discusses risk factor {i} in some detail. " * 3 for i in range(30)]
    text = "\n\n".join(paragraphs)
    section = DocumentSection(key="1A", title="Item 1A. Risk Factors", text=text, start_offset=0)

    drafts = chunk_section(section, target_tokens=40, overlap_tokens=10)

    assert len(drafts) > 1
    for i, draft in enumerate(drafts):
        assert draft.index == i
        # allow slack since we don't split mid-sentence
        assert draft.token_count <= 40 * 2

    # consecutive chunks should share some overlapping trailing/leading words
    first_words = drafts[0].text.split()[-5:]
    second_words = drafts[1].text.split()
    assert any(w in second_words for w in first_words)

    # offsets are monotonically non-decreasing and stay within the section
    offsets = [d.start_offset for d in drafts]
    assert offsets == sorted(offsets)
    assert all(0 <= o <= section.start_offset + len(section.text) for o in offsets)


def test_chunk_never_crosses_section_boundary() -> None:
    section_a = DocumentSection(
        key="1", title="Item 1. Business", text="Business content only, nothing about risks here.", start_offset=0
    )
    section_b = DocumentSection(
        key="1A",
        title="Item 1A. Risk Factors",
        text="Risk factor content only, nothing about business here.",
        start_offset=1000,
    )

    drafts_a = chunk_section(section_a)
    drafts_b = chunk_section(section_b)

    for d in drafts_a:
        assert "risk factor" not in d.text.lower()
    for d in drafts_b:
        assert "business content" not in d.text.lower()


# The page-break furniture below is copied from a real Walmart 10-Q, where it was retrieved as a
# top-scoring passage and quoted in a report as a cited fact.
_REAL_TOC_RUN = (
    "7 Table of Contents Walmart Inc. Notes to Condensed Consolidated Financial Statements Note 1. "
    "Note 2. 8 Table of Contents Note 3. 9 Table of Contents Note 4. 10 Table of Contents Note 5. "
    "11 Table of Contents 12 Table of Contents Note 6."
)

_REAL_PARAGRAPH = (
    "We must continue to preserve our reputation, which is impacted by public perceptions and customer "
    "experiences. It may be difficult to address negative publicity across media channels, regardless of "
    "whether it is accurate. Our reputation affects our ability to attract and retain associates."
)


def test_strip_navigation_removes_page_break_links_and_their_page_numbers() -> None:
    text = "Table of Contents Our operations are subject to numerous state laws. 14 Table of Contents"
    assert strip_navigation(text) == "Our operations are subject to numerous state laws."


def test_strip_navigation_leaves_ordinary_prose_untouched() -> None:
    assert strip_navigation(_REAL_PARAGRAPH) == _REAL_PARAGRAPH


def test_table_of_contents_run_is_navigation_noise() -> None:
    assert is_navigation_noise(strip_navigation(_REAL_TOC_RUN)) is True


def test_real_paragraph_is_not_navigation_noise() -> None:
    assert is_navigation_noise(_REAL_PARAGRAPH) is False


def test_short_text_is_never_rejected_as_noise() -> None:
    # Two fragments carry too little signal; dropping real disclosure is worse than keeping furniture.
    assert is_navigation_noise("Item 1A. Risk Factors.") is False


def test_chunking_drops_navigation_and_keeps_surrounding_disclosure() -> None:
    section = DocumentSection(
        key="7",
        title="Item 7. Management's Discussion and Analysis",
        text=f"{_REAL_TOC_RUN}\n\n{_REAL_PARAGRAPH}",
        start_offset=0,
    )

    drafts = chunk_section(section)
    body = " ".join(d.text for d in drafts)

    assert "Table of Contents" not in body
    assert "preserve our reputation" in body
