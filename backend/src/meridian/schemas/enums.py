from __future__ import annotations

from enum import StrEnum
from typing import Literal


class AgentName(StrEnum):
    SUPERVISOR = "supervisor"
    COMPANY = "company"
    FINANCIALS = "financials"
    FILINGS = "filings"
    NEWS = "news"
    MACRO = "macro"
    COMPETITORS = "competitors"
    VALUATION = "valuation"
    RISK = "risk"
    BULL = "bull"
    BEAR = "bear"
    CRITIC = "critic"
    REPORT_WRITER = "report_writer"


SPECIALIST_AGENTS: tuple[AgentName, ...] = (
    AgentName.COMPANY,
    AgentName.FINANCIALS,
    AgentName.FILINGS,
    AgentName.NEWS,
    AgentName.MACRO,
    AgentName.COMPETITORS,
    AgentName.VALUATION,
    AgentName.RISK,
    AgentName.BULL,
    AgentName.BEAR,
)


class ReportSection(StrEnum):
    EXECUTIVE_SUMMARY = "executive_summary"
    COMPANY_OVERVIEW = "company_overview"
    BUSINESS_MODEL = "business_model"
    FINANCIAL_PERFORMANCE = "financial_performance"
    FINANCIAL_TRENDS = "financial_trends"
    KEY_RATIOS = "key_ratios"
    RECENT_DEVELOPMENTS = "recent_developments"
    INDUSTRY_COMPETITION = "industry_competition"
    MACRO = "macro"
    VALUATION = "valuation"
    BULL_CASE = "bull_case"
    BEAR_CASE = "bear_case"
    KEY_RISKS = "key_risks"
    CATALYSTS = "catalysts"
    OPEN_QUESTIONS = "open_questions"
    SOURCES = "sources"


class FindingKind(StrEnum):
    FACT = "fact"
    CALCULATED = "calculated"
    INTERPRETATION = "interpretation"


class FindingStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    RESEARCHING = "researching"
    REVIEWING = "reviewing"
    REVISING = "revising"
    AWAITING_APPROVAL = "awaiting_approval"
    WRITING = "writing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Declared once and imported everywhere. It was spelled out separately in the settings, the API
# schema and the report schema, so adding a third backend broke a run at the point the report was
# built -- after every agent had already done its work.
LlmMode = Literal["anthropic", "openai_compat", "offline"]

TERMINAL_RUN_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})
# States a worker can pick a run back up from. AWAITING_APPROVAL is deliberately absent: that run
# is waiting for a person, and resuming it automatically would skip the approval gate.
RECOVERABLE_RUN_STATUSES = frozenset({RunStatus.QUEUED, RunStatus.RESEARCHING})


class SourceKind(StrEnum):
    SEC_FILING = "sec_filing"
    XBRL_FACTS = "xbrl_facts"
    MARKET_DATA = "market_data"
    NEWS = "news"
    MACRO = "macro"
    COMPANY_PROFILE = "company_profile"
    PEER_DATA = "peer_data"
    DOCUMENT = "document"
    CALCULATION = "calculation"


class RiskCategory(StrEnum):
    FINANCIAL = "financial"
    LIQUIDITY = "liquidity"
    DEBT = "debt"
    COMPETITIVE = "competitive"
    REGULATORY = "regulatory"
    OPERATIONAL = "operational"
    CONCENTRATION = "concentration"
    GEOPOLITICAL = "geopolitical"
    TECHNOLOGY = "technology"
    VALUATION = "valuation"


class Verdict(StrEnum):
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"


class CriticIssueType(StrEnum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    INCONSISTENT_FIGURE = "inconsistent_figure"
    STALE_INFORMATION = "stale_information"
    CONTRADICTION = "contradiction"
    CALCULATION_ERROR = "calculation_error"
    MISSING_CITATION = "missing_citation"
    HALLUCINATION = "hallucination"
    WEAK_ASSUMPTION = "weak_assumption"
    DUPLICATION = "duplication"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FeedbackAction(StrEnum):
    APPROVE = "approve"
    DEEPEN_VALUATION = "deepen_valuation"
    ADD_COMPETITOR = "add_competitor"
    ADD_RISK_ANALYSIS = "add_risk_analysis"
    RERUN_AGENT = "rerun_agent"
    COMMENT = "comment"
