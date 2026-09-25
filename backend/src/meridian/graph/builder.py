"""Assembles the LangGraph `StateGraph` described in the platform design doc, section 5::

    intake -> plan -> dispatch(wave n) -> [specialists in parallel] -> advance_wave
            -> (more waves? dispatch) -> supervisor_review -> (gaps? dispatch) -> critic
            -> (rework & rounds<max? revise -> critic) -> human_review (interrupt if enabled)
            -> (extra work? dispatch) -> write_report -> finalize

Fan-out uses `Send`: `dispatch` marks the next runnable batch RUNNING, then its conditional edge
(`route_dispatch`) builds `Send(agent_name, WorkerInput(task, snapshot))` per task in that batch. Every
worker node has a static edge back to `advance_wave`, which is the single fan-in point whose conditional
edge (`route_after_wave`) decides whether to loop back to `dispatch` (more waves), or move on to critic /
write_report depending on why the batch that just finished was dispatched (see `routing.py`).
"""

from __future__ import annotations

import inspect
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from meridian.agents import contracts as agent_contracts
from meridian.core.config import Settings
from meridian.graph import nodes, routing
from meridian.graph.nodes import WorkerInput
from meridian.memory import types as memory_types
from meridian.observability.events import EventSink
from meridian.schemas import (
    analysis,
    citations,
    enums,
    events,
    financials,
    findings,
    report,
    research,
    state,
    telemetry,
)


def _meridian_msgpack_allowlist() -> set[tuple[str, str]]:
    """Every class defined in the meridian modules the graph state can carry.

    LangGraph 1.2's checkpoint serializer logs "Deserializing unregistered type" for any class it has to
    reconstruct that isn't on this allowlist. Rather than hand-list every schema/enum (and have that list
    silently go stale as other tasks add fields), we walk the modules that make up `ResearchState` and its
    nested schemas plus the graph/agents/memory contracts, and collect every class actually defined there.
    Any new class added to one of these modules is picked up automatically the next time the process starts.
    """
    modules = (
        analysis,
        citations,
        enums,
        events,
        findings,
        financials,
        report,
        research,
        state,
        telemetry,
        agent_contracts,
        memory_types,
        nodes,
    )
    allowed: set[tuple[str, str]] = set()
    for module in modules:
        for obj in vars(module).values():
            if inspect.isclass(obj) and obj.__module__.startswith("meridian"):
                allowed.add((obj.__module__, obj.__name__))
    return allowed


def default_checkpointer() -> InMemorySaver:
    """An `InMemorySaver` whose serializer knows about every meridian type, warning-free."""
    serde = JsonPlusSerializer(allowed_msgpack_modules=_meridian_msgpack_allowlist())
    return InMemorySaver(serde=serde)


def build_graph(
    agents: agent_contracts.AgentSet,
    settings: Settings,
    events_sink: EventSink,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph: StateGraph[state.ResearchState, Any, Any, Any] = StateGraph(state.ResearchState)

    graph.add_node("intake", nodes.make_intake_node(agents, events_sink))
    graph.add_node("plan", nodes.make_plan_node(agents, events_sink))
    graph.add_node("dispatch", nodes.make_dispatch_node(events_sink))
    graph.add_node("advance_wave", nodes.advance_wave)
    graph.add_node("supervisor_review", nodes.make_supervisor_review_node(agents, settings, events_sink))
    graph.add_node("critic", nodes.make_critic_node(agents, settings, events_sink))
    graph.add_node("revise", nodes.make_revise_node(agents, events_sink))
    graph.add_node("human_review", nodes.make_human_review_node(agents, events_sink))
    graph.add_node("write_report", nodes.make_write_report_node(agents, events_sink))
    graph.add_node("finalize", nodes.make_finalize_node(events_sink))

    for agent_name, specialist in agents.specialists.items():
        graph.add_node(
            agent_name.value, nodes.make_worker_node(agent_name, specialist, events_sink), input_schema=WorkerInput
        )
        graph.add_edge(agent_name.value, "advance_wave")

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "plan")
    graph.add_edge("plan", "dispatch")
    graph.add_conditional_edges("dispatch", routing.route_dispatch)
    graph.add_conditional_edges("advance_wave", routing.route_after_wave)
    graph.add_conditional_edges("supervisor_review", routing.route_after_supervisor)
    graph.add_conditional_edges("critic", routing.route_after_critic)
    graph.add_edge("revise", "dispatch")
    graph.add_conditional_edges("human_review", routing.route_after_human)
    graph.add_edge("write_report", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer or default_checkpointer())
