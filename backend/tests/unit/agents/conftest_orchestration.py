"""Shared test helpers for the orchestration agent suite (supervisor/bull/bear/critic/report_writer/registry).

This is deliberately NOT named `conftest.py`: the parallel Task 9 workstream owns
`tests/unit/agents/conftest.py` for the eight specialist-agent tests, and pytest auto-loads every
`conftest.py` on the path, so a second one here would collide. Import what you need from this module
directly in each test file instead (`from conftest_orchestration import ...`).
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from pydantic import BaseModel, Field

from meridian.agents.base import AgentDeps
from meridian.core.config import Settings
from meridian.core.errors import CompanyNotFoundError
from meridian.observability.events import EventSink, NullEventSink
from meridian.providers.llm.base import LLMProvider
from meridian.providers.llm.offline import OfflineLLMProvider
from meridian.providers.registry import ProviderRegistry
from meridian.schemas.citations import Evidence, EvidenceLocator, Source
from meridian.schemas.enums import (
    AgentName,
    FindingKind,
    FindingStatus,
    ReportSection,
    RunStatus,
    SourceKind,
    TaskStatus,
)
from meridian.schemas.financials import FinancialMetrics, MetricValue
from meridian.schemas.findings import AgentOutput, Finding
from meridian.schemas.research import CompanyIdentity, ResearchPlan, ResearchRequest
from meridian.schemas.state import ResearchState
from meridian.tools.base import Tool, ToolContext, ToolRegistry

# ---- domain builders --------------------------------------------------------------------------------------


def make_company(
    *, ticker: str = "ACME", name: str = "Acme Corp", cik: str = "0000000001", sic: str = "7372"
) -> CompanyIdentity:
    return CompanyIdentity(name=name, ticker=ticker, cik=cik, sic=sic)


def make_source(
    seed: str, *, published_at: date | None = None, kind: SourceKind = SourceKind.SEC_FILING, is_snapshot: bool = False
) -> Source:
    return Source.make(
        kind=kind,
        title=f"Source {seed}",
        provider="test",
        publisher="Test Publisher",
        url=f"https://example.com/{seed}",
        published_at=published_at,
        is_snapshot=is_snapshot,
    )


def make_evidence(source: Source, text: str, *, section: str | None = None) -> Evidence:
    return Evidence.make(source_id=source.id, text=text, locator=EvidenceLocator(section=section))


def make_finding(
    agent: AgentName,
    section: ReportSection,
    claim: str,
    *,
    kind: FindingKind = FindingKind.FACT,
    evidence_ids: list[str] | None = None,
    metric_refs: list[str] | None = None,
    status: FindingStatus = FindingStatus.APPROVED,
    revision: int = 0,
) -> Finding:
    return Finding(
        agent=agent,
        section=section,
        claim=claim,
        kind=kind,
        evidence_ids=evidence_ids or [],
        metric_refs=metric_refs or [],
        status=status,
        revision=revision,
    )


def make_output(
    agent: AgentName,
    findings: list[Finding],
    *,
    status: TaskStatus = TaskStatus.COMPLETED,
    task_id: str | None = None,
    revision: int = 0,
    error: str | None = None,
) -> AgentOutput:
    return AgentOutput(
        agent=agent,
        task_id=task_id or f"task_{agent.value}",
        status=status,
        findings=findings,
        revision=revision,
        error=error,
    )


def make_metrics(ticker: str = "ACME") -> FinancialMetrics:
    """A small, internally-consistent metrics table reused across critic/writer/report_assembly tests."""
    metrics = FinancialMetrics(ticker=ticker)
    metrics.add(
        MetricValue(key="revenue", period="FY2023", value=211_915_000_000.0, unit="USD", formula="reported revenue")
    )
    metrics.add(
        MetricValue(key="revenue", period="FY2024", value=245_122_000_000.0, unit="USD", formula="reported revenue")
    )
    metrics.add(
        MetricValue(
            key="revenue_growth", period="FY2024", value=0.157, unit="ratio", formula="(rev - prior_rev) / prior_rev"
        )
    )
    metrics.add(
        MetricValue(key="gross_margin", period="FY2024", value=0.697, unit="ratio", formula="gross_profit / revenue")
    )
    metrics.add(
        MetricValue(key="net_margin", period="FY2024", value=0.359, unit="ratio", formula="net_income / revenue")
    )
    metrics.add(
        MetricValue(
            key="free_cash_flow",
            period="FY2024",
            value=74_071_000_000.0,
            unit="USD",
            formula="operating_cash_flow - capex",
        )
    )
    metrics.add(MetricValue(key="pe", period="current", value=33.9, unit="x", formula="price / eps_diluted"))
    return metrics


def make_state(
    *,
    query: str = "Research Acme Corp",
    ticker: str | None = "ACME",
    depth: str = "standard",
    focus_areas: list[str] | None = None,
    company: CompanyIdentity | None = None,
    outputs: list[AgentOutput] | None = None,
    sources: list[Source] | None = None,
    evidence: list[Evidence] | None = None,
    metrics: FinancialMetrics | None = None,
    plan: ResearchPlan | None = None,
    revision_round: int = 0,
    supervisor_loops: int = 0,
    peers: object | None = None,
    financials: object | None = None,
) -> ResearchState:
    request = ResearchRequest(query=query, ticker=ticker, depth=depth, focus_areas=focus_areas or [])
    state = ResearchState(
        session_id="sess_test",
        request=request,
        status=RunStatus.RESEARCHING,
        company=company,
        plan=plan,
        revision_round=revision_round,
        supervisor_loops=supervisor_loops,
        metrics=metrics,
        peers=peers,
        financials=financials,
    )
    if sources:
        state.sources.update({s.id: s for s in sources})
    if evidence:
        state.evidence.update({e.id: e for e in evidence})
    if outputs:
        state.outputs.update({o.agent.value: o for o in outputs})
    return state


# ---- tool/provider/deps fakes -----------------------------------------------------------------------------


class _UnusedProvider:
    """Placeholder for a `ProviderRegistry` slot a given test never exercises."""

    name = "unused"


def make_provider_registry(llm: LLMProvider) -> ProviderRegistry:
    unused = _UnusedProvider()
    return ProviderRegistry(
        directory=unused,
        fundamentals=unused,
        filings=unused,
        market=unused,  # type: ignore[arg-type]
        news=unused,
        macro=unused,
        peers=unused,
        llm=llm,
        embeddings=unused,
    )  # type: ignore[arg-type]


def make_deps(
    settings: Settings,
    *,
    llm: LLMProvider | None = None,
    tools: ToolRegistry | None = None,
    events: EventSink | None = None,
) -> AgentDeps:
    return AgentDeps(
        settings=settings,
        providers=make_provider_registry(llm or OfflineLLMProvider()),
        tools=tools or ToolRegistry(),
        retriever=None,
        events=events or NullEventSink(),
    )


class ResolveCompanyInput(BaseModel):
    query: str


class ResolveCompanyOutput(BaseModel):
    company: CompanyIdentity
    evidence_ids: list[str] = Field(default_factory=list)


class FakeResolveCompanyTool(Tool[ResolveCompanyInput, ResolveCompanyOutput]):
    """Test double for the real (Task 8) `resolve_company` tool: same name/shape, no network."""

    name: ClassVar[str] = "resolve_company"
    description: ClassVar[str] = "Resolve a ticker or company name (test double)."
    input_model: ClassVar[type[BaseModel]] = ResolveCompanyInput

    def __init__(
        self,
        company: CompanyIdentity | None = None,
        *,
        source: Source | None = None,
        evidence: Evidence | None = None,
        fail: bool = False,
    ) -> None:
        self._company = company
        self._source = source
        self._evidence = evidence
        self._fail = fail

    async def run(self, args: ResolveCompanyInput, ctx: ToolContext) -> ResolveCompanyOutput:
        if self._fail or self._company is None:
            raise CompanyNotFoundError(f"no company found for {args.query!r}")
        evidence_ids: list[str] = []
        if self._source is not None:
            ctx.ledger.add_source(self._source)
        if self._evidence is not None:
            ctx.ledger.add_evidence(self._evidence)
            evidence_ids.append(self._evidence.id)
        return ResolveCompanyOutput(company=self._company, evidence_ids=evidence_ids)


def make_tool_registry_with_resolve(company: CompanyIdentity | None, **kw: object) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FakeResolveCompanyTool(company, **kw))  # type: ignore[arg-type]
    return registry
