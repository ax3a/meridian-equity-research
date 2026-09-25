"""Small helpers shared across tool modules. Not a tool itself -- no `Tool` subclass here.

Kept private (leading underscore module name) because it is an implementation detail of this
package, not part of the 19-tool contract in the implementation plan.
"""

from __future__ import annotations

import re

from meridian.core.errors import MeridianError
from meridian.schemas.financials import FinancialStatements, MetricValue
from meridian.schemas.research import CompanyIdentity
from meridian.tools.base import ToolContext


async def resolve_identity(ctx: ToolContext, ticker: str) -> CompanyIdentity:
    """Resolve a ticker/name to a `CompanyIdentity` via the directory provider. No SIC lookup."""
    return await ctx.providers.directory.resolve(ticker)


async def resolve_identity_with_profile(ctx: ToolContext, ticker: str) -> CompanyIdentity:
    """Resolve, then enrich with SIC/profile data (needed for `is_financial_institution` and peer
    discovery). Profile evidence is absorbed into the ledger as a side effect (harmless, deduplicated);
    if the profile lookup itself fails, the plain resolved identity is returned rather than failing
    the whole tool call.
    """
    identity = await ctx.providers.directory.resolve(ticker)
    try:
        result = await ctx.providers.directory.profile(identity)
    except MeridianError:
        return identity
    ctx.ledger.absorb(result)
    return result.data.identity


def fmt_num(value: float | None, *, decimals: int = 0) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.{decimals}f}"


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.2f}%"


def render_metric_value(mv: MetricValue) -> str:
    if mv.unit == "ratio":
        return fmt_pct(mv.value)
    if mv.unit == "x":
        return f"{fmt_num(mv.value, decimals=2)}x"
    if mv.unit == "USD/share":
        return f"{fmt_num(mv.value, decimals=2)} USD/share"
    if mv.unit == "shares":
        return f"{fmt_num(mv.value)} shares"
    return f"{fmt_num(mv.value)} {mv.unit}"


_BASIS_RE = re.compile(r"\[basis: (.+?)\]")


def line_item_evidence_map(statements: FinancialStatements) -> dict[tuple[str, str], str]:
    """(period_label, field_name) -> evidence_id, across every annual and quarterly period."""
    mapping: dict[tuple[str, str], str] = {}
    for pf in (*statements.annual, *statements.quarterly):
        for field, eid in pf.evidence_ids.items():
            mapping[(pf.period.label, field)] = eid
    return mapping


def ttm_evidence_ids(statements: FinancialStatements, field: str) -> list[str]:
    quarters = statements.quarterly[-4:]
    return [pf.evidence_ids[field] for pf in quarters if field in pf.evidence_ids]


def metric_evidence_ids(mv: MetricValue, statements: FinancialStatements) -> list[str]:
    """Best-effort trace from a computed `MetricValue` back to the raw-line-item evidence ids that
    fed it, using the fact that `financial_engine`'s `Calc.inputs` keys are named identically to
    `PeriodFinancials` field names. Market-basis inputs (e.g. ``price``) have no line-item evidence
    of their own -- callers should also include the quote's evidence id separately when relevant.
    """
    ids: set[str] = set()
    basis_match = _BASIS_RE.search(mv.formula)
    basis = basis_match.group(1) if basis_match else mv.period
    line_map = line_item_evidence_map(statements)
    latest_label = statements.annual[-1].period.label if statements.annual else None

    for field, value in mv.inputs.items():
        if value is None or field == "price":
            continue
        if mv.period == "TTM" or basis == "TTM":
            ids.update(ttm_evidence_ids(statements, field))
            continue
        candidate_labels = [basis if mv.period == "current" else mv.period]
        if latest_label and latest_label not in candidate_labels:
            candidate_labels.append(latest_label)
        for label in candidate_labels:
            eid = line_map.get((label, field))
            if eid:
                ids.add(eid)
                break
    return sorted(ids)
