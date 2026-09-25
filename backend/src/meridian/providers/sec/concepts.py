"""XBRL us-gaap/dei concept fallback chains and period-selection rules for SEC company facts.

Pure functions only: no I/O. ``facts.py`` orchestrates fetching and evidence construction on top
of these.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

# A period is identified purely by its own boundaries: (start, end) for a duration fact, or
# (None, end) for an instant fact. This is the only thing SEC's XBRL data ever gets right, no
# matter how many later filings re-disclose the period as a comparative -- see PeriodKey below.
PeriodKey = tuple[str | None, str]
FiscalLabel = tuple[int, str]  # (fiscal_year, fiscal_period), e.g. (2024, "FY") or (2024, "Q1")

# Canonical line item -> ordered us-gaap concept fallback chain. The first concept with any
# accepted-unit facts wins.
CONCEPT_CHAINS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"),
    "gross_profit": ("GrossProfit",),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "eps_basic": ("EarningsPerShareBasic",),
    "shares_diluted": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "depreciation_amortization": ("DepreciationDepletionAndAmortization", "DepreciationAndAmortization"),
    "cash_and_equivalents": ("CashAndCashEquivalentsAtCarryingValue",),
    "short_term_investments": ("ShortTermInvestments", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "current_debt": ("LongTermDebtCurrent", "DebtCurrent"),
    "current_assets": ("AssetsCurrent",),
    "total_assets": ("Assets",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "total_liabilities": ("Liabilities",),
    "shareholders_equity": ("StockholdersEquity",),
    "research_and_development": ("ResearchAndDevelopmentExpense",),
    "income_tax_expense": ("IncomeTaxExpenseBenefit",),
    "interest_expense": ("InterestExpense", "InterestExpenseDebt"),
}

# dei (Document and Entity Information) taxonomy: shares outstanding as of the cover-page date.
SHARES_OUTSTANDING_ITEM = "shares_outstanding"
SHARES_OUTSTANDING_TAXONOMY = "dei"
SHARES_OUTSTANDING_CONCEPT = "EntityCommonStockSharesOutstanding"

# Line items backed by XBRL "duration" (start/end) facts.
DURATION_ITEMS: frozenset[str] = frozenset(
    {
        "revenue",
        "cost_of_revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "operating_cash_flow",
        "capex",
        "depreciation_amortization",
        "research_and_development",
        "income_tax_expense",
        "interest_expense",
        "eps_basic",
        "eps_diluted",
        "shares_diluted",
    }
)

# Line items backed by XBRL "instant" (point-in-time) facts.
INSTANT_ITEMS: frozenset[str] = frozenset(
    {
        "cash_and_equivalents",
        "short_term_investments",
        "long_term_debt",
        "current_debt",
        "current_assets",
        "total_assets",
        "current_liabilities",
        "total_liabilities",
        "shareholders_equity",
        SHARES_OUTSTANDING_ITEM,
    }
)

PER_SHARE_ITEMS: frozenset[str] = frozenset({"eps_basic", "eps_diluted"})
SHARE_COUNT_ITEMS: frozenset[str] = frozenset({"shares_diluted", SHARES_OUTSTANDING_ITEM})

ACCEPTED_UNITS: dict[str, frozenset[str]] = {
    "eps_basic": frozenset({"USD/shares"}),
    "eps_diluted": frozenset({"USD/shares"}),
    "shares_diluted": frozenset({"shares"}),
    SHARES_OUTSTANDING_ITEM: frozenset({"shares"}),
}
_DEFAULT_UNIT: frozenset[str] = frozenset({"USD"})


def accepted_units(item: str) -> frozenset[str]:
    return ACCEPTED_UNITS.get(item, _DEFAULT_UNIT)


@dataclass(frozen=True)
class ResolvedFact:
    """A single line-item value resolved from a company facts payload."""

    item: str
    concept: str
    taxonomy: str
    entry: dict[str, Any]
    derived: bool = False
    # Free-text annotation surfaced in the evidence text: either how a derived value was computed,
    # or that the chosen (latest-filed) value differs from what was originally reported.
    note: str | None = None

    @property
    def value(self) -> float:
        return float(self.entry["val"])


def _entries_for_concept(company_facts: dict[str, Any], taxonomy: str, concept: str, item: str) -> list[dict[str, Any]]:
    units: dict[str, list[dict[str, Any]]] = (
        company_facts.get("facts", {}).get(taxonomy, {}).get(concept, {}).get("units", {})
    )
    allowed = accepted_units(item)
    out: list[dict[str, Any]] = []
    for unit_name, entries in units.items():
        if unit_name in allowed:
            out.extend(entries)
    return out


def resolve_concept(company_facts: dict[str, Any], item: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Try each us-gaap concept in ``item``'s fallback chain; return the first with any facts.

    Prefer :func:`candidate_entries` for statement building: picking a single concept per company
    silently loses periods when a filer changes tagging mid-history.
    """
    for concept in CONCEPT_CHAINS.get(item, ()):
        entries = _entries_for_concept(company_facts, "us-gaap", concept, item)
        if entries:
            return concept, entries
    return None


CONCEPT_KEY = "__concept"
PRIORITY_KEY = "__priority"


def candidate_entries(
    company_facts: dict[str, Any], item: str, *, taxonomy: str = "us-gaap", concepts: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Every annual+quarterly candidate for ``item``, from *all* concepts in its chain.

    Filers change tagging over time: NVIDIA reports recent years under ``Revenues`` but its older
    years under ``RevenueFromContractWithCustomerExcludingAssessedTax``. Choosing one concept per
    company therefore leaves whole periods empty, so each entry is tagged with the concept it came
    from and its position in the chain, and the choice is made per period by :func:`select_by_period`.
    """
    out: list[dict[str, Any]] = []
    for priority, concept in enumerate(concepts if concepts is not None else CONCEPT_CHAINS.get(item, ())):
        entries = _entries_for_concept(company_facts, taxonomy, concept, item)
        kept = annual_entries(entries, item) + quarterly_entries(entries, item)
        out.extend({**e, CONCEPT_KEY: concept, PRIORITY_KEY: priority} for e in kept)
    return out


def select_by_period(entries: list[dict[str, Any]]) -> dict[PeriodKey, dict[str, Any]]:
    """One entry per period: the earliest concept in the chain wins, then the latest filing wins.

    Chain order encodes preference (a specific revenue concept over a generic one), so it outranks
    recency; within one concept, a later filing means a restatement and should win.
    """
    best: dict[PeriodKey, dict[str, Any]] = {}
    for e in entries:
        key = period_key(e)
        current = best.get(key)
        if current is None:
            best[key] = e
            continue
        rank = (-e.get(PRIORITY_KEY, 0), str(e.get("filed", "")))
        current_rank = (-current.get(PRIORITY_KEY, 0), str(current.get("filed", "")))
        if rank > current_rank:
            best[key] = e
    return best


def resolve_shares_outstanding(company_facts: dict[str, Any]) -> tuple[str, list[dict[str, Any]]] | None:
    entries = _entries_for_concept(
        company_facts, SHARES_OUTSTANDING_TAXONOMY, SHARES_OUTSTANDING_CONCEPT, SHARES_OUTSTANDING_ITEM
    )
    return (SHARES_OUTSTANDING_CONCEPT, entries) if entries else None


def _is_duration_entry(entry: dict[str, Any]) -> bool:
    return bool(entry.get("start")) and bool(entry.get("end"))


def _duration_days(entry: dict[str, Any]) -> int:
    return (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days


def annual_entries(entries: list[dict[str, Any]], item: str) -> list[dict[str, Any]]:
    """Filter to 10-K, ``fp == "FY"`` facts, applying the duration/instant window rule.

    ``fp`` reliably marks "this is an annual fact" even on a comparative row (a 10-K's prior-year
    comparatives are still tagged ``fp == "FY"``) -- only the ``fy`` *number* is untrustworthy on a
    comparative row (see the module docstring / ``label_periods``), so it is deliberately not
    filtered on here. Callers must resolve the true fiscal year via ``pool_period_entries`` +
    ``label_periods`` + ``reconcile_fiscal_years``, never from an individual entry's own ``fy``.
    """
    is_duration = item in DURATION_ITEMS
    candidates = []
    for e in entries:
        if not str(e.get("form", "")).startswith("10-K"):
            continue
        if e.get("fp") != "FY":
            continue
        if is_duration:
            if not _is_duration_entry(e):
                continue
            if not (300 <= _duration_days(e) <= 400):
                continue
        elif _is_duration_entry(e):
            continue
        candidates.append(e)
    return candidates


def quarterly_entries(entries: list[dict[str, Any]], item: str) -> list[dict[str, Any]]:
    """Filter to 10-Q, ``fp`` in (Q1, Q2, Q3) facts, 80-100 day durations for duration items.

    ``fp`` reflects a quarter's calendar position (which quarter of the fiscal year it is), which
    stays correct even on a comparative row; as with ``annual_entries``, only ``fy`` is untrustworthy
    on a comparative row.
    """
    is_duration = item in DURATION_ITEMS
    out = []
    for e in entries:
        if not str(e.get("form", "")).startswith("10-Q"):
            continue
        if e.get("fp") not in ("Q1", "Q2", "Q3"):
            continue
        if is_duration:
            if not _is_duration_entry(e):
                continue
            if not (80 <= _duration_days(e) <= 100):
                continue
        elif _is_duration_entry(e):
            continue
        out.append(e)
    return out


def period_key(entry: dict[str, Any]) -> PeriodKey:
    return (entry.get("start"), entry["end"])


def dedupe_by_period(entries: list[dict[str, Any]]) -> dict[PeriodKey, dict[str, Any]]:
    """Keep one entry per *actual* (start, end) period, preferring the one filed most recently
    (so a later restatement wins). Grouping by the real period boundaries -- rather than by an
    entry's own ``fy`` tag -- is immune to the "comparative rows inherit the filing's own fy" quirk:
    the period boundaries themselves never lie about which period a fact covers.
    """
    best: dict[PeriodKey, dict[str, Any]] = {}
    for e in entries:
        key = period_key(e)
        current = best.get(key)
        if current is None or str(e.get("filed", "")) > str(current.get("filed", "")):
            best[key] = e
    return best


def pool_period_entries(entries_by_item: dict[str, list[dict[str, Any]]]) -> dict[PeriodKey, list[dict[str, Any]]]:
    """Pool every candidate entry, across every line item, bucketed by its exact period.

    The same period is reported under many different ``fy`` tags across successive filings (the tag
    describes the *report* the fact was disclosed in, not the period itself). Pooling across every
    line item maximises the chance of finding, for a given period, the filing where it was first
    disclosed as the *current* period -- the one filing whose ``fy``/``fp`` tags for that period can
    be trusted.
    """
    buckets: dict[PeriodKey, list[dict[str, Any]]] = defaultdict(list)
    for entries in entries_by_item.values():
        for e in entries:
            buckets[period_key(e)].append(e)
    return buckets


def label_periods(buckets: dict[PeriodKey, list[dict[str, Any]]]) -> dict[PeriodKey, FiscalLabel]:
    """One (fiscal_year, fiscal_period) label per period, taken from whichever entry was filed
    *earliest*: that is the filing where the period was the current period, so its own ``fy``/``fp``
    tags are trustworthy. A later filing re-discloses the same period only as a comparative and
    mistags its ``fy`` with the later filing's own fiscal year (``fp`` stays correct either way: it
    reflects the period's calendar position, not its vintage).

    This alone still mislabels a period that is *never* captured as a "current" period anywhere in
    the fetched history (e.g. the oldest comparative year in a company facts payload) -- that case is
    repaired by ``reconcile_fiscal_years``.
    """
    labels: dict[PeriodKey, FiscalLabel] = {}
    for key, entries in buckets.items():
        earliest = min(entries, key=lambda e: (str(e.get("filed") or ""), e.get("fy") or 0))
        fy, fp = earliest.get("fy"), earliest.get("fp")
        if fy is not None and fp is not None:
            labels[key] = (fy, fp)
    return labels


def reconcile_fiscal_years(labels: dict[PeriodKey, FiscalLabel]) -> dict[PeriodKey, FiscalLabel]:
    """Anchor each fiscal-period cycle (FY, or each of Q1/Q2/Q3 independently) on its *most recent*
    occurrence -- which, by construction, can only ever have been disclosed as a current period so
    far, so ``label_periods`` always gets it right -- then walk backwards in whole fiscal years from
    there. This repairs the "oldest period only ever seen as a comparative" edge case, and any other
    period whose ``label_periods`` result disagrees with the periodic calendar established by the
    company's own most recent filings.

    Fiscal year length is derived from the *actual* gap between period end dates (rounded to the
    nearest whole year), so this works for any fiscal-year-end month/day (June for Microsoft,
    September for Apple, late January for NVIDIA) without hardcoding a calendar.
    """
    by_fiscal_period: dict[str, list[tuple[PeriodKey, int]]] = defaultdict(list)
    for key, (fy, fp) in labels.items():
        by_fiscal_period[fp].append((key, fy))

    reconciled: dict[PeriodKey, FiscalLabel] = {}
    for fp, items in by_fiscal_period.items():
        ordered = sorted(items, key=lambda pair: pair[0][1])  # ascending by end date
        anchor_key, anchor_fy = ordered[-1]
        anchor_end = date.fromisoformat(anchor_key[1])
        for key, _fy in ordered:
            end = date.fromisoformat(key[1])
            year_gap = round((anchor_end - end).days / 365.25)
            reconciled[key] = (anchor_fy - year_gap, fp)
    return reconciled
