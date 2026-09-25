"""Assembles the `AgentSet` the graph consumes: supervisor, critic, writer and every specialist agent.

The eight non-bull/bear specialist agents (Task 9) are owned by a parallel workstream. They are imported
lazily and defensively here so this module — and anything that depends on it — keeps working even if that
work is momentarily incomplete or landed under a different class name; a missing specialist is logged and
simply absent from `AgentSet.specialists` rather than crashing `build_agent_set`.
"""

from __future__ import annotations

import importlib

from meridian.agents.base import AgentDeps
from meridian.agents.bear import Bear
from meridian.agents.bull import Bull
from meridian.agents.contracts import AgentSet, Specialist
from meridian.agents.critic import Critic
from meridian.agents.report_writer import ReportWriter
from meridian.agents.supervisor import Supervisor
from meridian.core.logging import get_logger
from meridian.schemas.enums import AgentName

log = get_logger(__name__)

# agent -> (module, candidate class names in preference order).
_SPECIALIST_MODULES: dict[AgentName, tuple[str, tuple[str, ...]]] = {
    AgentName.COMPANY: ("meridian.agents.company", ("CompanyAgent", "Company")),
    AgentName.FINANCIALS: ("meridian.agents.financials", ("FinancialsAgent", "Financials")),
    AgentName.FILINGS: ("meridian.agents.filings", ("FilingsAgent", "Filings")),
    AgentName.NEWS: ("meridian.agents.news", ("NewsAgent", "News")),
    AgentName.MACRO: ("meridian.agents.macro", ("MacroAgent", "Macro")),
    AgentName.COMPETITORS: ("meridian.agents.competitors", ("CompetitorsAgent", "Competitors")),
    AgentName.VALUATION: ("meridian.agents.valuation", ("ValuationAgent", "Valuation")),
    AgentName.RISK: ("meridian.agents.risk", ("RiskAgent", "Risk")),
}


def _load_specialist(
    deps: AgentDeps, agent: AgentName, module_name: str, class_names: tuple[str, ...]
) -> Specialist | None:
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        log.warning("specialist_module_unavailable", agent=agent.value, module=module_name, error=str(exc))
        return None
    for class_name in class_names:
        cls = getattr(module, class_name, None)
        if cls is not None:
            return cls(deps)  # type: ignore[no-any-return]
    log.warning("specialist_class_not_found", agent=agent.value, module=module_name, tried=list(class_names))
    return None


def build_agent_set(deps: AgentDeps) -> AgentSet:
    specialists: dict[AgentName, Specialist] = {}
    for agent, (module_name, class_names) in _SPECIALIST_MODULES.items():
        instance = _load_specialist(deps, agent, module_name, class_names)
        if instance is not None:
            specialists[agent] = instance

    specialists[AgentName.BULL] = Bull(deps)
    specialists[AgentName.BEAR] = Bear(deps)

    return AgentSet(
        supervisor=Supervisor(deps), critic=Critic(deps), writer=ReportWriter(deps), specialists=specialists
    )
