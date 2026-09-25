"""Assembles the fixed 19-tool registry every agent draws its allowlist from."""

from __future__ import annotations

from meridian.tools.base import ToolRegistry
from meridian.tools.calc import CalculateMetricTool, RunDcfTool
from meridian.tools.company import GetCompanyProfileTool, ResolveCompanyTool, SearchCompaniesTool
from meridian.tools.evidence import LookupEvidenceTool
from meridian.tools.filings import (
    GetFilingSectionTool,
    GetRecent8kEventsTool,
    IndexFilingsTool,
    ListFilingsTool,
    SearchFilingsTool,
)
from meridian.tools.financial import ComputeFinancialMetricsTool, GetFinancialStatementsTool
from meridian.tools.macro import GetMacroIndicatorsTool
from meridian.tools.market import GetMarketQuoteTool
from meridian.tools.memory import RecallResearchMemoryTool
from meridian.tools.news import SearchNewsTool
from meridian.tools.peers import FindPeerCandidatesTool, GetPeerSnapshotTool


def build_tool_registry() -> ToolRegistry:
    """Build the fixed registry of all 19 typed tools available to specialist agents."""
    return ToolRegistry(
        [
            ResolveCompanyTool(),
            SearchCompaniesTool(),
            GetCompanyProfileTool(),
            GetFinancialStatementsTool(),
            ComputeFinancialMetricsTool(),
            CalculateMetricTool(),
            RunDcfTool(),
            ListFilingsTool(),
            IndexFilingsTool(),
            SearchFilingsTool(),
            GetFilingSectionTool(),
            GetRecent8kEventsTool(),
            GetMarketQuoteTool(),
            SearchNewsTool(),
            GetMacroIndicatorsTool(),
            FindPeerCandidatesTool(),
            GetPeerSnapshotTool(),
            LookupEvidenceTool(),
            RecallResearchMemoryTool(),
        ]
    )
