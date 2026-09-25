from __future__ import annotations

from meridian.providers.sec.concepts import (
    annual_entries,
    candidate_entries,
    dedupe_by_period,
    label_periods,
    pool_period_entries,
    quarterly_entries,
    reconcile_fiscal_years,
    resolve_concept,
    resolve_shares_outstanding,
    select_by_period,
)


def _duration(start, end, val, accn="A", fy=2024, fp="FY", form="10-K", filed="2024-07-30"):
    return {"start": start, "end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}


def _instant(end, val, accn="A", fy=2024, fp="FY", form="10-K", filed="2024-07-30"):
    return {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}


def test_resolve_concept_falls_back_through_the_chain():
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [_duration("2023-01-01", "2023-12-31", 100)]}}}}}

    resolved = resolve_concept(facts, "revenue")

    assert resolved is not None
    concept, entries = resolved
    assert concept == "Revenues"
    assert len(entries) == 1


def test_resolve_concept_returns_none_when_no_concept_present():
    assert resolve_concept({"facts": {"us-gaap": {}}}, "revenue") is None


def test_resolve_concept_ignores_wrong_unit():
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"shares": [_duration("2023-01-01", "2023-12-31", 100)]}}}}}

    assert resolve_concept(facts, "revenue") is None


def test_resolve_shares_outstanding_reads_dei_taxonomy():
    concept = {"units": {"shares": [_instant("2024-07-25", 7000)]}}
    facts = {"facts": {"dei": {"EntityCommonStockSharesOutstanding": concept}}}

    resolved = resolve_shares_outstanding(facts)

    assert resolved is not None
    concept, entries = resolved
    assert concept == "EntityCommonStockSharesOutstanding"
    assert entries[0]["val"] == 7000


def test_annual_entries_filters_form_and_fp_and_duration_window():
    entries = [
        _duration("2023-07-01", "2024-06-30", 1, form="10-K", fp="FY"),  # keep: 366 days
        _duration("2024-01-01", "2024-03-31", 2, form="10-Q", fp="Q3"),  # drop: wrong form
        _duration("2023-07-01", "2024-06-30", 3, form="10-K", fp="Q4"),  # drop: wrong fp
        _duration("2024-05-01", "2024-06-30", 4, form="10-K", fp="FY"),  # drop: too short a duration
    ]

    kept = annual_entries(entries, "revenue")

    assert kept == [entries[0]]


def test_annual_entries_keeps_both_balances_of_an_accession_for_period_labelling():
    # A 10-K tags the current FYE balance AND the prior year-end comparative with the same fy/fp.
    # Both are kept here: the period pipeline (not this filter) decides which fiscal year each is.
    entries = [
        _instant("2023-06-30", 100, accn="X", fy=2024),  # prior-year comparative
        _instant("2024-06-30", 200, accn="X", fy=2024),  # true FY2024 balance
    ]

    assert annual_entries(entries, "total_assets") == entries


def test_dedupe_by_period_prefers_latest_filed_so_restatements_win():
    older = _duration("2021-07-01", "2022-06-30", 100, accn="A", fy=2022, filed="2022-07-28")
    restated = _duration("2021-07-01", "2022-06-30", 111, accn="B", fy=2024, filed="2024-07-30")

    best = dedupe_by_period([older, restated])

    assert best[("2021-07-01", "2022-06-30")] == restated


def test_comparative_rows_do_not_steal_the_filing_fiscal_year():
    """The FY2022 period appears in three successive 10-Ks, tagged fy=2022, 2023 then 2024.

    Labelling must follow the period, not the filing: taking the latest-filed entry's own `fy`
    (the old behaviour) labelled Microsoft's FY2022 revenue as FY2024.
    """
    period = ("2021-07-01", "2022-06-30")
    entries_by_item = {
        "revenue": [
            _duration(*period, 198270, accn="A", fy=2022, filed="2022-07-28"),  # original
            _duration(*period, 198270, accn="B", fy=2023, filed="2023-07-27"),  # comparative
            _duration(*period, 198270, accn="C", fy=2024, filed="2024-07-30"),  # comparative
        ]
    }

    labels = label_periods(pool_period_entries(entries_by_item))

    assert labels[period] == (2022, "FY")


def test_oldest_period_seen_only_as_a_comparative_is_repaired():
    """FY2020 never appears as a current period here, so its earliest entry mislabels it FY2022.

    Reconciliation anchors on the most recent period and walks back whole fiscal years.
    """
    fy2020 = ("2019-07-01", "2020-06-30")
    fy2022 = ("2021-07-01", "2022-06-30")
    labels = {fy2020: (2022, "FY"), fy2022: (2022, "FY")}

    reconciled = reconcile_fiscal_years(labels)

    assert reconciled[fy2022] == (2022, "FY")
    assert reconciled[fy2020] == (2020, "FY")


def test_reconciliation_handles_a_late_january_fiscal_year_end():
    """NVIDIA's year ending late January 2025 is FY2025; no calendar month may be hardcoded."""
    fy2024 = ("2023-01-30", "2024-01-28")
    fy2025 = ("2024-01-29", "2025-01-26")
    labels = {fy2024: (2025, "FY"), fy2025: (2025, "FY")}

    reconciled = reconcile_fiscal_years(labels)

    assert reconciled[fy2025] == (2025, "FY")
    assert reconciled[fy2024] == (2024, "FY")


def test_concept_is_chosen_per_period_when_a_filer_changes_tagging():
    """NVIDIA tags older years under one revenue concept and recent years under another.

    Picking a single concept per company (the first in the chain with any facts) left recent
    periods empty, so revenue came back as None for every year the analyst actually cares about.
    """
    old_period, new_period = ("2016-02-01", "2017-01-29"), ("2024-01-29", "2025-01-26")
    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [_duration(*old_period, 6910, fy=2019, filed="2019-02-21")]}
                },
                "Revenues": {"units": {"USD": [_duration(*new_period, 130497, fy=2025, filed="2025-02-26")]}},
            }
        }
    }

    selected = select_by_period(candidate_entries(facts, "revenue"))

    assert selected[old_period]["val"] == 6910
    assert selected[new_period]["val"] == 130497


def test_select_by_period_prefers_chain_order_over_recency():
    period = ("2024-01-29", "2025-01-26")
    facts = {
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {"USD": [_duration(*period, 111, fy=2025, filed="2025-02-26")]}
                },
                # Filed later, but a lower-priority concept must not displace the preferred one.
                "Revenues": {"units": {"USD": [_duration(*period, 222, fy=2025, filed="2026-02-26")]}},
            }
        }
    }

    assert select_by_period(candidate_entries(facts, "revenue"))[period]["val"] == 111


def test_quarterly_entries_requires_10q_and_q1_q2_q3_and_80_100_days():
    entries = [
        _duration("2023-07-01", "2023-09-30", 1, form="10-Q", fp="Q1"),  # keep: 91 days
        _duration("2023-07-01", "2024-06-30", 2, form="10-Q", fp="Q1"),  # drop: too long
        _duration("2023-07-01", "2023-09-30", 3, form="10-K", fp="Q1"),  # drop: wrong form
        _duration("2023-07-01", "2023-09-30", 4, form="10-Q", fp="Q4"),  # drop: Q4 is never a standalone fact
    ]

    kept = quarterly_entries(entries, "revenue")

    assert kept == [entries[0]]


def test_quarterly_periods_are_labelled_from_the_filing_that_first_reported_them():
    period = ("2023-07-01", "2023-09-30")
    entries_by_item = {
        "revenue": [
            _duration(*period, 1, accn="A", fy=2024, fp="Q1", form="10-Q", filed="2023-10-24"),
            _duration(*period, 1, accn="B", fy=2025, fp="Q1", form="10-Q", filed="2024-10-24"),
        ]
    }

    labels = label_periods(pool_period_entries(entries_by_item))

    assert labels[period] == (2024, "Q1")
