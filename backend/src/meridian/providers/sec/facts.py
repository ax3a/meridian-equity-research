"""SEC EDGAR fundamentals provider: XBRL company facts -> FinancialStatements with full provenance.

Every populated line item carries a Source (one per accession, kind XBRL_FACTS) and an Evidence
whose text names the exact us-gaap/dei concept, value, unit and period used -- or, for a value we
had to derive ourselves (e.g. gross profit = revenue - cost of revenue) or a restated value, says so
explicitly.

Fiscal-year assignment is the one subtle part of this module: SEC's XBRL `fy`/`fp` tags describe the
*report* a fact was disclosed in, not the period it covers. A company's Nth 10-K shows several years
of comparatives, and -- confirmed against real MSFT and NVIDIA data -- ALL of them get stamped with
that 10-K's own `fy`. Naively grouping facts by their own `fy` tag therefore mislabels every period
except the very latest one. We instead identify a period purely by its (start, end) boundaries, pool
every line item's candidate facts together, and derive the fiscal year from whichever disclosure of
that exact period was filed *earliest* (the period's own original filing) -- see
`meridian.providers.sec.concepts` for the full algorithm.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from meridian.cache.base import Policies
from meridian.core.http import HttpClient
from meridian.providers.base import ProviderResult
from meridian.providers.sec.concepts import (
    CONCEPT_CHAINS,
    CONCEPT_KEY,
    INSTANT_ITEMS,
    PER_SHARE_ITEMS,
    SHARE_COUNT_ITEMS,
    SHARES_OUTSTANDING_CONCEPT,
    SHARES_OUTSTANDING_ITEM,
    SHARES_OUTSTANDING_TAXONOMY,
    FiscalLabel,
    PeriodKey,
    ResolvedFact,
    candidate_entries,
    label_periods,
    period_key,
    pool_period_entries,
    reconcile_fiscal_years,
    select_by_period,
)
from meridian.providers.sec.endpoints import accession_nodashes, company_facts_url, filing_index_url
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import SourceKind
from meridian.schemas.financials import FinancialPeriod, FinancialStatements, PeriodFinancials
from meridian.schemas.research import CompanyIdentity

PUBLISHER = "U.S. SEC EDGAR"
_Q_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
_FISCAL_PERIODS = ("FY", "Q1", "Q2", "Q3")


class SecFundamentalsProvider:
    """FundamentalsProvider backed by SEC EDGAR's XBRL company facts API."""

    name = "sec_edgar"

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    async def get_statements(self, company: CompanyIdentity, years: int = 5) -> ProviderResult[FinancialStatements]:
        result = await self._http.get_json(
            company_facts_url(company.cik), provider=self.name, policy=Policies.COMPANY_FACTS
        )
        body: dict[str, Any] = result.body
        entity_name = body.get("entityName", company.name)
        builder = _SourceEvidenceBuilder(company=company, entity_name=entity_name)

        by_fiscal_label = _resolve_all_periods(body)
        _add_q4_periods(by_fiscal_label)

        fy_keys = sorted({fy for fy, fp in by_fiscal_label if fp == "FY"})
        if years > 0:
            fy_keys = fy_keys[-years:]
        annual_periods = [builder.assemble_period(fy, "FY", by_fiscal_label[(fy, "FY")]) for fy in fy_keys]

        quarterly_keys = sorted(
            (k for k in by_fiscal_label if k[1] in ("Q1", "Q2", "Q3", "Q4")),
            key=lambda k: (k[0], _Q_ORDER[k[1]]),
        )
        quarterly_periods = []
        for fy, fp in quarterly_keys:
            items = by_fiscal_label[(fy, fp)]
            force_derived = fp == "Q4" and any(rf.derived for rf in items.values())
            quarterly_periods.append(builder.assemble_period(fy, fp, items, force_derived=force_derived))

        statements = FinancialStatements(
            ticker=company.ticker,
            annual=annual_periods,
            quarterly=quarterly_periods,
            source_ids=[s.id for s in builder.sources.values()],
        )

        is_snapshot = result.from_snapshot
        if is_snapshot:
            for src in builder.sources.values():
                src.is_snapshot = True
                src.snapshot_date = result.snapshot_date

        return ProviderResult(
            data=statements,
            provider=self.name,
            sources=list(builder.sources.values()),
            evidence=builder.evidence,
            is_snapshot=is_snapshot,
            cached=result.from_cache,
        )


def _resolve_all_periods(body: dict[str, Any]) -> dict[FiscalLabel, dict[str, ResolvedFact]]:
    """Resolve every line item's value for every period, with the fiscal year taken from a single
    authoritative period_end -> (fiscal_year, fiscal_period) map built across ALL items at once, so
    no two line items can ever disagree about which fiscal year a period belongs to.
    """
    candidate_entries_by_item: dict[str, list[dict[str, Any]]] = {}
    concept_by_item: dict[str, str] = {}
    taxonomy_by_item: dict[str, str] = {}

    for item in CONCEPT_CHAINS:
        candidates = candidate_entries(body, item)
        if candidates:
            candidate_entries_by_item[item] = candidates
            taxonomy_by_item[item] = "us-gaap"

    shares = candidate_entries(
        body,
        SHARES_OUTSTANDING_ITEM,
        taxonomy=SHARES_OUTSTANDING_TAXONOMY,
        concepts=(SHARES_OUTSTANDING_CONCEPT,),
    )
    if shares:
        candidate_entries_by_item[SHARES_OUTSTANDING_ITEM] = shares
        taxonomy_by_item[SHARES_OUTSTANDING_ITEM] = SHARES_OUTSTANDING_TAXONOMY

    period_labels = reconcile_fiscal_years(label_periods(pool_period_entries(candidate_entries_by_item)))

    by_fiscal_label: dict[FiscalLabel, dict[str, ResolvedFact]] = defaultdict(dict)
    for item, entries in candidate_entries_by_item.items():
        # Per period: best concept in the chain wins, then latest filing (restatements).
        chosen_by_period = select_by_period(entries)
        earliest_by_period = _earliest_filed_by_period(entries)  # what was *originally* reported

        for pkey, chosen_entry in chosen_by_period.items():
            label = period_labels.get(pkey)
            if label is None or label[1] not in _FISCAL_PERIODS:
                continue
            note = None
            earliest_entry = earliest_by_period[pkey]
            if earliest_entry is not chosen_entry and earliest_entry.get("val") != chosen_entry.get("val"):
                note = (
                    f"restated; originally reported as {float(earliest_entry['val']):,.0f} in accession "
                    f"{earliest_entry.get('accn')}, filed {earliest_entry.get('filed')}"
                )
            by_fiscal_label[label][item] = ResolvedFact(
                item=item,
                concept=chosen_entry.get(CONCEPT_KEY, concept_by_item.get(item, "unknown")),
                taxonomy=taxonomy_by_item[item],
                entry=chosen_entry,
                note=note,
            )

    # Gross-profit derivation applies to annual periods only (matching prior behaviour: quarterly
    # gross profit is left absent unless a company reports GrossProfit quarterly itself).
    for label, items in by_fiscal_label.items():
        if label[1] != "FY":
            continue
        if "gross_profit" not in items and "revenue" in items and "cost_of_revenue" in items:
            rev, cost = items["revenue"], items["cost_of_revenue"]
            derived_entry = {**rev.entry, "val": rev.value - cost.value}
            items["gross_profit"] = ResolvedFact(
                item="gross_profit",
                concept="derived",
                taxonomy="us-gaap",
                entry=derived_entry,
                derived=True,
                note="derived as revenue - cost_of_revenue (GrossProfit not reported)",
            )

    return dict(by_fiscal_label)


def _earliest_filed_by_period(entries: list[dict[str, Any]]) -> dict[PeriodKey, dict[str, Any]]:
    earliest: dict[PeriodKey, dict[str, Any]] = {}
    for e in entries:
        key = period_key(e)
        current = earliest.get(key)
        if current is None or str(e.get("filed") or "") < str(current.get("filed") or ""):
            earliest[key] = e
    return earliest


def _add_q4_periods(by_fiscal_label: dict[FiscalLabel, dict[str, ResolvedFact]]) -> None:
    """Q4 is never filed as a standalone XBRL fact. Balance-sheet Q4 figures are simply the
    fiscal-year-end instant balances from the 10-K (no derivation needed); flow Q4 figures are
    derived as FY total minus Q1+Q2+Q3, only when all four are on hand.
    """
    fiscal_years = {fy for fy, fp in by_fiscal_label if fp == "FY"}
    for fy in fiscal_years:
        fy_items = by_fiscal_label.get((fy, "FY"), {})
        q1 = by_fiscal_label.get((fy, "Q1"), {})
        q2 = by_fiscal_label.get((fy, "Q2"), {})
        q3 = by_fiscal_label.get((fy, "Q3"), {})

        q4: dict[str, ResolvedFact] = {}
        for item, rf in fy_items.items():
            if item in INSTANT_ITEMS:
                q4[item] = rf

        if q1 and q2 and q3 and fy_items:
            for item in set(q1) & set(q2) & set(q3) & set(fy_items):
                fy_rf = fy_items[item]
                derived_val = fy_rf.value - (q1[item].value + q2[item].value + q3[item].value)
                derived_entry = {
                    "val": derived_val,
                    "end": fy_rf.entry.get("end"),
                    "start": q3[item].entry.get("end"),
                    "accn": fy_rf.entry.get("accn"),
                    "fy": fy,
                    "fp": "Q4",
                    "form": "derived",
                    "filed": fy_rf.entry.get("filed"),
                }
                q4[item] = ResolvedFact(
                    item=item,
                    concept=fy_rf.concept,
                    taxonomy=fy_rf.taxonomy,
                    entry=derived_entry,
                    derived=True,
                    note=f"derived as FY{fy} total minus Q1+Q2+Q3 (no standalone Q4 fact is filed)",
                )

        if q4:
            by_fiscal_label[(fy, "Q4")] = q4


class _SourceEvidenceBuilder:
    """Accumulates one Source per accession and one Evidence per populated line item."""

    def __init__(self, *, company: CompanyIdentity, entity_name: str) -> None:
        self.company = company
        self.entity_name = entity_name
        self.sources: dict[str, Source] = {}
        self.evidence: list[Evidence] = []

    def _source_for(self, entry: dict[str, Any]) -> Source:
        accession = entry.get("accn") or "unknown"
        if accession in self.sources:
            return self.sources[accession]
        form = entry.get("form") or "10-K"
        filed_raw = entry.get("filed")
        filed = date.fromisoformat(filed_raw) if filed_raw else None
        url = None
        if accession != "unknown":
            url = filing_index_url(int(self.company.cik), accession_nodashes(accession), accession)
        src = Source.make(
            kind=SourceKind.XBRL_FACTS,
            title=f"{self.entity_name} {form} (accession {accession})",
            provider="sec_edgar",
            publisher=PUBLISHER,
            url=url,
            published_at=filed,
            metadata={"accession": accession, "form": form, "fiscal_year": entry.get("fy")},
        )
        self.sources[accession] = src
        return src

    def assemble_period(
        self,
        fiscal_year: int,
        fiscal_period: str,
        items: dict[str, ResolvedFact],
        *,
        force_derived: bool = False,
    ) -> PeriodFinancials:
        anchor = (
            items.get("revenue") or items.get("net_income") or items.get("total_assets") or next(iter(items.values()))
        )
        label = f"FY{fiscal_year}" if fiscal_period == "FY" else f"FY{fiscal_year}{fiscal_period}"
        period_end = date.fromisoformat(anchor.entry["end"])

        if force_derived:
            period = FinancialPeriod(
                label=label,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                period_end=period_end,
                form="derived",
                accession_number=None,
                filed=None,
            )
        else:
            filed_raw = anchor.entry.get("filed")
            period = FinancialPeriod(
                label=label,
                fiscal_year=fiscal_year,
                fiscal_period=fiscal_period,
                period_end=period_end,
                form=anchor.entry.get("form"),
                accession_number=anchor.entry.get("accn"),
                filed=date.fromisoformat(filed_raw) if filed_raw else None,
            )

        pf = PeriodFinancials(period=period)
        for item, rf in items.items():
            setattr(pf, item, rf.value)
            source = self._source_for(rf.entry)
            text = _evidence_text(self.entity_name, rf, label)
            evidence = Evidence.make(
                source_id=source.id,
                text=text,
                locator=EvidenceLocator(xbrl_concept=rf.concept, period=label, accession_number=rf.entry.get("accn")),
            )
            pf.evidence_ids[item] = evidence.id
            self.evidence.append(evidence)
        return pf


def _unit_for(item: str) -> str:
    if item in PER_SHARE_ITEMS:
        return "USD/shares"
    if item in SHARE_COUNT_ITEMS:
        return "shares"
    return "USD"


def _evidence_text(entity_name: str, rf: ResolvedFact, period_label: str) -> str:
    form = rf.entry.get("form") or "10-K"
    accession = rf.entry.get("accn") or "unknown"
    filed = rf.entry.get("filed") or "unknown"
    unit = _unit_for(rf.item)
    start, end = rf.entry.get("start"), rf.entry.get("end")
    period_desc = f"{start}..{end}" if start else str(end)
    value_str = f"{rf.value:,.2f}" if unit == "USD/shares" else f"{rf.value:,.0f}"
    prefix = f"{entity_name} {form} (accession {accession}, filed {filed})"

    if rf.derived:
        return f"{prefix}: {rf.item} = {value_str} {unit} for period {period_desc} ({rf.note})"

    qualified_concept = f"{rf.taxonomy}:{rf.concept}"
    base = f"{prefix}: {qualified_concept} = {value_str} {unit} for period {period_desc}"
    return f"{base} ({rf.note})" if rf.note else base
