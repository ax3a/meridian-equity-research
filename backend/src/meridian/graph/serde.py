"""The msgpack allowlist LangGraph's checkpoint serializer needs.

Lives apart from `builder` so the checkpointer can share it without importing the graph: every saver
must use the same serializer, or a checkpoint written by one process fails to deserialize in another.
"""

from __future__ import annotations

import inspect

from meridian.agents import contracts as agent_contracts
from meridian.graph import nodes
from meridian.memory import types as memory_types
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


def meridian_msgpack_allowlist() -> set[tuple[str, str]]:
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
