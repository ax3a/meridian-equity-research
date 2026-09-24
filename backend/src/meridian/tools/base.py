"""Typed tool framework: validated inputs/outputs, per-agent allowlists, and call recording."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from meridian.core.config import Settings
from meridian.core.errors import MeridianError
from meridian.core.ids import new_id
from meridian.memory.types import ResearchMemoryStore
from meridian.observability.events import EventSink
from meridian.providers.base import ProviderResult
from meridian.providers.llm.base import ToolSpec
from meridian.providers.registry import ProviderRegistry
from meridian.rag.types import Retriever
from meridian.schemas.citations import Evidence, Source
from meridian.schemas.enums import AgentName
from meridian.schemas.events import EventType, ProgressEvent
from meridian.schemas.telemetry import ToolCallRecord

InT = TypeVar("InT", bound=BaseModel)
OutT = TypeVar("OutT")


class EvidenceLedger:
    """Collects sources and evidence produced during one agent execution (deduplicated by id)."""

    def __init__(self) -> None:
        self.sources: dict[str, Source] = {}
        self.evidence: dict[str, Evidence] = {}

    def add_source(self, source: Source) -> Source:
        self.sources.setdefault(source.id, source)
        return self.sources[source.id]

    def add_evidence(self, evidence: Evidence) -> Evidence:
        self.evidence.setdefault(evidence.id, evidence)
        return self.evidence[evidence.id]

    def absorb(self, result: ProviderResult[Any]) -> None:
        for s in result.sources:
            self.add_source(s)
        for e in result.evidence:
            self.add_evidence(e)


@dataclass
class ToolContext:
    session_id: str
    agent: AgentName
    settings: Settings
    providers: ProviderRegistry
    retriever: Retriever | None
    events: EventSink
    ledger: EvidenceLedger = field(default_factory=EvidenceLedger)
    calls: list[ToolCallRecord] = field(default_factory=list)
    # Read-only view of evidence/sources already in the research state (for citation lookup tools).
    known_evidence: dict[str, Evidence] = field(default_factory=dict)
    known_sources: dict[str, Source] = field(default_factory=dict)
    memory: ResearchMemoryStore | None = None

    def evidence(self, evidence_id: str) -> Evidence | None:
        return self.ledger.evidence.get(evidence_id) or self.known_evidence.get(evidence_id)

    def source(self, source_id: str) -> Source | None:
        return self.ledger.sources.get(source_id) or self.known_sources.get(source_id)


class Tool(ABC, Generic[InT, OutT]):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def run(self, args: InT, ctx: ToolContext) -> OutT: ...

    def summarize(self, output: OutT) -> str:
        """Compact, LLM-readable rendering of the output (also used in traces)."""
        if isinstance(output, BaseModel):
            return output.model_dump_json(exclude_none=True)[:6000]
        return str(output)[:6000]

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description,
                        input_schema=self.input_model.model_json_schema())


class ToolInvocation(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    ok: bool
    output: Any = None
    summary: str = ""
    error: str | None = None
    record: ToolCallRecord


class ToolNotAllowedError(MeridianError):
    code = "tool_not_allowed"
    status_code = 403


class ToolRegistry:
    def __init__(self, tools: list[Tool[Any, Any]] | None = None) -> None:
        self._tools: dict[str, Tool[Any, Any]] = {}
        for t in tools or []:
            self.register(t)

    def register(self, tool: Tool[Any, Any]) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any, Any]:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, allowlist: frozenset[str]) -> list[ToolSpec]:
        return [self._tools[n].spec() for n in sorted(allowlist) if n in self._tools]

    async def invoke(
        self, name: str, raw_args: dict[str, Any], ctx: ToolContext, *, allowlist: frozenset[str]
    ) -> ToolInvocation:
        """Validate, execute and record a tool call. Never raises for tool/provider failures."""
        started = time.perf_counter()
        status, output, summary, error = "error", None, "", None
        try:
            if name not in allowlist or name not in self._tools:
                raise ToolNotAllowedError(f"tool '{name}' is not available to agent '{ctx.agent}'")
            tool = self._tools[name]
            args = tool.input_model.model_validate(raw_args)
            output = await tool.run(args, ctx)
            summary = tool.summarize(output)
            status = "ok"
        except ValidationError as exc:
            error = f"invalid arguments: {exc.errors(include_url=False)[:3]}"
        except MeridianError as exc:
            error = exc.message
        except Exception as exc:  # tool boundary: record and continue, never crash the agent
            error = f"{type(exc).__name__}: {exc}"
        record = ToolCallRecord(
            id=new_id("tc"), agent=ctx.agent, tool=name, arguments=_safe_args(raw_args), status=status,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            result_summary=summary[:300], error=error,
        )
        ctx.calls.append(record)
        await ctx.events.emit(ProgressEvent(
            session_id=ctx.session_id, type=EventType.TOOL_CALLED, agent=ctx.agent,
            message=f"{ctx.agent.value} called {name} ({status})",
            data={"tool": name, "status": status, "duration_ms": record.duration_ms, "error": error},
        ))
        return ToolInvocation(ok=status == "ok", output=output, summary=summary, error=error, record=record)


def _safe_args(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in list(raw.items())[:12]:
        if any(s in k.lower() for s in ("key", "token", "secret", "password")):
            out[k] = "***"
        elif isinstance(v, str):
            out[k] = v[:200]
        elif isinstance(v, int | float | bool) or v is None:
            out[k] = v
        else:
            out[k] = str(v)[:200]
    return out
