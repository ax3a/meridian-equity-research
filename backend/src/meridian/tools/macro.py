"""Macro indicators tool: get_macro_indicators."""

from __future__ import annotations

from pydantic import BaseModel

from meridian.providers.base import MacroIndicator
from meridian.tools.base import Tool, ToolContext


class GetMacroIndicatorsInput(BaseModel):
    keys: list[str] | None = None


class GetMacroIndicatorsOutput(BaseModel):
    indicators: list[MacroIndicator]
    evidence_ids: list[str]


class GetMacroIndicatorsTool(Tool[GetMacroIndicatorsInput, GetMacroIndicatorsOutput]):
    """Macro indicators (Treasury yields, and CPI/Fed funds/unemployment/GDP when a FRED key is set)."""

    name = "get_macro_indicators"
    description = (
        "Fetch macroeconomic indicators (e.g. 'ust_10y', 'ust_2y', 'ust_3m', and if configured "
        "'cpi_yoy', 'fed_funds', 'unemployment', 'real_gdp_growth'). Pass `keys` to filter."
    )
    input_model = GetMacroIndicatorsInput

    async def run(self, args: GetMacroIndicatorsInput, ctx: ToolContext) -> GetMacroIndicatorsOutput:
        result = await ctx.providers.macro.get_indicators()
        ctx.ledger.absorb(result)
        # Evidence is produced in the same order as indicators by every macro provider; filter both
        # lists together so an indicator never ends up paired with another indicator's evidence id.
        pairs = list(zip(result.data, result.evidence, strict=False))
        if args.keys:
            wanted = set(args.keys)
            pairs = [(i, e) for i, e in pairs if i.key in wanted]
        indicators = [i for i, _ in pairs]
        evidence_ids = [e.id for _, e in pairs]
        return GetMacroIndicatorsOutput(indicators=indicators, evidence_ids=evidence_ids)

    def summarize(self, output: GetMacroIndicatorsOutput) -> str:
        lines = []
        for indicator, eid in zip(output.indicators, output.evidence_ids, strict=False):
            lines.append(f"{indicator.key} = {indicator.latest} {indicator.unit} as of {indicator.as_of} [{eid}]")
        return "\n".join(lines)[:6000]
