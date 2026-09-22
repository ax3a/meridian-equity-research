"""Agent base class.

Each agent is an independent component with its own tool allowlist, output schema and two synthesis paths:
- generative: a bounded LLM tool-use loop (Anthropic) whose final answer is schema-validated;
- offline: deterministic, evidence-driven synthesis (no LLM), used when no API key is configured.
Both paths gather evidence through the same recorded tools, and all findings pass citation validation.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, Field, ValidationError

from meridian.agents.validation import ValidationReport, validate_findings
from meridian.core.config import LLMTier, Settings
from meridian.core.errors import AgentTimeoutError, LLMOutputError, MeridianError
from meridian.core.ids import utcnow
from meridian.core.logging import get_logger
from meridian.observability.events import EventSink
from meridian.providers.llm.base import ChatMessage, LLMRequest
from meridian.providers.registry import ProviderRegistry
from meridian.rag.types import Retriever
from meridian.schemas.citations import Evidence, Source
from meridian.schemas.enums import AgentName, Confidence, FindingKind, ReportSection, TaskStatus
from meridian.schemas.findings import AgentOutput, Finding
from meridian.schemas.research import ResearchTask
from meridian.schemas.state import ResearchState
from meridian.schemas.telemetry import LLMUsage, ToolCallRecord
from meridian.security.prompting import build_user_message, render_evidence, system_prompt, wrap_tool_result
from meridian.tools.base import ToolContext, ToolInvocation, ToolRegistry

log = get_logger(__name__)
M = TypeVar("M", bound=BaseModel)


@dataclass
class AgentDeps:
    settings: Settings
    providers: ProviderRegistry
    tools: ToolRegistry
    retriever: Retriever | None
    events: EventSink


class DraftFinding(BaseModel):
    """LLM-facing finding schema (ids are assigned by the platform)."""

    claim: str = Field(min_length=3, max_length=1500)
    kind: FindingKind
    section: ReportSection
    evidence_ids: list[str] = Field(default_factory=list)
    metric_refs: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM
    category: str | None = None


class AgentAnswer(BaseModel):
    """Default structured LLM answer for specialist agents."""

    summary: str = Field(max_length=2000)
    findings: list[DraftFinding] = Field(default_factory=list, max_length=40)


@dataclass
class AgentDraft:
    """What an agent's `run` returns before platform validation."""

    summary: str
    findings: list[Finding] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    state_updates: dict[str, Any] = field(default_factory=dict)  # e.g. {"metrics": FinancialMetrics}


@dataclass
class AgentResult:
    output: AgentOutput
    sources: dict[str, Source]
    evidence: dict[str, Evidence]
    tool_calls: list[ToolCallRecord]
    usage: list[LLMUsage]
    state_updates: dict[str, Any]
    validation: ValidationReport


class BaseAgent(ABC):
    name: ClassVar[AgentName]
    role: ClassVar[str]
    mission: ClassVar[str]
    tier: ClassVar[LLMTier] = "worker"
    allowed_tools: ClassVar[frozenset[str]] = frozenset()
    max_tool_steps: ClassVar[int] = 6

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps
        self._usage: list[LLMUsage] = []

    # ---- template method ------------------------------------------------
    async def execute(self, task: ResearchTask, state: ResearchState) -> AgentResult:
        ctx = ToolContext(session_id=state.session_id, agent=self.name, settings=self.deps.settings,
                          providers=self.deps.providers, retriever=self.deps.retriever, events=self.deps.events)
        self._usage = []
        started = utcnow()
        t0 = time.perf_counter()
        status, error = TaskStatus.COMPLETED, None
        draft = AgentDraft(summary="")
        try:
            async with asyncio.timeout(self.deps.settings.agent_timeout_seconds):
                draft = await self.run(task, state, ctx)
        except TimeoutError:
            status, error = TaskStatus.FAILED, AgentTimeoutError(f"{self.name} timed out").message
        except MeridianError as exc:
            status, error = TaskStatus.FAILED, exc.message
        except Exception as exc:  # agent boundary: a failed agent must not crash the run
            log.exception("agent_crashed", agent=self.name)
            status, error = TaskStatus.FAILED, f"{type(exc).__name__}: {exc}"

        known_evidence = set(state.evidence) | set(ctx.ledger.evidence)
        metrics = draft.state_updates.get("metrics") or state.metrics
        known_metrics = set(metrics.values) if metrics else set()
        findings, report = validate_findings(draft.findings, evidence_ids=known_evidence, metric_refs=known_metrics)
        if report.problems:
            log.info("findings_validated", agent=self.name, stripped=len(report.stripped_evidence_ids),
                     unverified=len(report.unverified_finding_ids))

        output = AgentOutput(
            agent=self.name, task_id=task.id, status=status, summary=draft.summary or (error or ""),
            findings=[f.model_copy(update={"revision": task.revision}) for f in findings],
            data=draft.data, source_ids=list(ctx.ledger.sources), evidence_ids=list(ctx.ledger.evidence),
            tools_used=sorted({c.tool for c in ctx.calls}), error=error, revision=task.revision,
            started_at=started, finished_at=utcnow(),
        )
        log.info("agent_finished", agent=self.name, status=status, findings=len(findings),
                 ms=round((time.perf_counter() - t0) * 1000))
        return AgentResult(output=output, sources=ctx.ledger.sources, evidence=ctx.ledger.evidence,
                           tool_calls=ctx.calls, usage=self._usage, state_updates=draft.state_updates,
                           validation=report)

    @abstractmethod
    async def run(self, task: ResearchTask, state: ResearchState, ctx: ToolContext) -> AgentDraft: ...

    # ---- helpers for subclasses ----------------------------------------
    @property
    def generative(self) -> bool:
        return self.deps.providers.llm.generative

    async def tool(self, ctx: ToolContext, name: str, **args: Any) -> ToolInvocation:
        return await self.deps.tools.invoke(name, args, ctx, allowlist=self.allowed_tools)

    def finding(self, claim: str, kind: FindingKind, section: ReportSection, *, evidence_ids: list[str] | None = None,
                metric_refs: list[str] | None = None, confidence: Confidence = Confidence.MEDIUM,
                category: str | None = None) -> Finding:
        return Finding(agent=self.name, section=section, claim=claim, kind=kind, evidence_ids=evidence_ids or [],
                       metric_refs=metric_refs or [], confidence=confidence, category=category)

    def to_findings(self, answer: AgentAnswer) -> list[Finding]:
        return [self.finding(d.claim, d.kind, d.section, evidence_ids=d.evidence_ids, metric_refs=d.metric_refs,
                             confidence=d.confidence, category=d.category) for d in answer.findings]

    async def llm_structured(self, ctx: ToolContext, *, task: str, schema: type[M], evidence: list[Evidence],
                             sources: dict[str, Source], context: dict[str, Any] | None = None,
                             max_tokens: int = 4096) -> M:
        """Single-shot structured generation over provided evidence (no tools)."""
        message = build_user_message(task, context=context, evidence_block=render_evidence(evidence, sources))
        return await self._structured_loop(ctx, [message], schema, tools=False, max_tokens=max_tokens)

    async def llm_research(self, ctx: ToolContext, *, task: str, schema: type[M],
                           context: dict[str, Any] | None = None, max_tokens: int = 4096) -> M:
        """Bounded tool-use loop: the model chooses allowlisted tools, then submits a structured answer."""
        message = build_user_message(task, context=context)
        return await self._structured_loop(ctx, [message], schema, tools=True, max_tokens=max_tokens)

    async def _structured_loop(self, ctx: ToolContext, messages: list[ChatMessage], schema: type[M], *,
                               tools: bool, max_tokens: int) -> M:
        llm = self.deps.providers.llm
        specs = self.deps.tools.specs(self.allowed_tools) if tools else []
        validation_retries = 0
        steps = self.max_tool_steps if tools else 1
        for step in range(steps + 2):
            force = not specs or step >= steps
            req = LLMRequest(agent=self.name, tier=self.tier, system=system_prompt(self.role, self.mission),
                             messages=messages, tools=[] if force else specs, output_schema=schema,
                             force_output=force, max_tokens=max_tokens)
            resp = await llm.complete(req)
            self._usage.append(resp.usage)
            if resp.structured is not None:
                try:
                    return schema.model_validate(resp.structured)
                except ValidationError as exc:
                    validation_retries += 1
                    if validation_retries > 2:
                        raise LLMOutputError(f"{self.name}: output failed schema validation") from exc
                    messages = [*messages, ChatMessage(role="assistant", content=resp.raw_content or
                                                       [{"type": "text", "text": "(invalid output)"}]),
                                ChatMessage(role="user", content=_tool_results_for_invalid(resp, exc))]
                    continue
            if not resp.tool_calls:
                messages = [*messages, ChatMessage(role="assistant", content=resp.text or "(no answer)"),
                            ChatMessage(role="user", content="Submit your answer using the submit_answer tool.")]
                continue
            results: list[dict[str, Any]] = []
            for call in resp.tool_calls[:4]:
                inv = await self.tool(ctx, call.name, **call.arguments)
                content = wrap_tool_result(call.name, inv.summary if inv.ok else f"ERROR: {inv.error}")
                results.append({"type": "tool_result", "tool_use_id": call.id, "content": content,
                                "is_error": not inv.ok})
            messages = [*messages, ChatMessage(role="assistant", content=resp.raw_content),
                        ChatMessage(role="user", content=results)]
        raise LLMOutputError(f"{self.name}: no valid structured answer within step budget")


def _tool_results_for_invalid(resp: Any, exc: ValidationError) -> list[dict[str, Any]] | str:
    problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])
    submit = [c for c in resp.tool_calls if c.name == "submit_answer"]
    if submit:
        return [{"type": "tool_result", "tool_use_id": submit[0].id, "is_error": True,
                 "content": f"Schema validation failed: {problems}. Call submit_answer again with corrected output."}]
    return f"Your answer failed schema validation: {problems}. Submit a corrected answer."
