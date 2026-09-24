"""Repositories: each takes an `AsyncSession` owned by the caller and never commits its own txn."""

from __future__ import annotations

from meridian.db.repositories.companies import CompanyRepository
from meridian.db.repositories.events import EventRepository
from meridian.db.repositories.evidence import EvidenceRepository
from meridian.db.repositories.memory import MemoryRepository, PreferenceRepository
from meridian.db.repositories.reports import ReportRepository
from meridian.db.repositories.research import AgentRunRecord, ResearchRecord, ResearchRepository
from meridian.db.repositories.telemetry import TelemetryRepository

__all__ = [
    "AgentRunRecord",
    "CompanyRepository",
    "EventRepository",
    "EvidenceRepository",
    "MemoryRepository",
    "PreferenceRepository",
    "ReportRepository",
    "ResearchRecord",
    "ResearchRepository",
    "TelemetryRepository",
]
