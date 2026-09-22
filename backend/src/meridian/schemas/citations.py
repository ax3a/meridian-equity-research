from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from meridian.core.ids import stable_id, utcnow
from meridian.schemas.enums import SourceKind

MAX_EVIDENCE_CHARS = 4000


class Source(BaseModel):
    """A retrievable origin of evidence (filing, XBRL dataset, article, price series...)."""

    id: str
    kind: SourceKind
    title: str
    url: str | None = None
    publisher: str
    provider: str
    published_at: date | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    is_snapshot: bool = False
    snapshot_date: date | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def make(cls, *, kind: SourceKind, title: str, provider: str, publisher: str,
             url: str | None = None, **kw: Any) -> Source:
        return cls(id=stable_id("src", provider, kind, url or title), kind=kind, title=title,
                   provider=provider, publisher=publisher, url=url, **kw)


class EvidenceLocator(BaseModel):
    """Where inside the source the evidence lives."""

    section: str | None = None
    page: int | None = None
    xbrl_concept: str | None = None
    period: str | None = None
    accession_number: str | None = None
    chunk_id: str | None = None

    def describe(self) -> str:
        parts = [
            f"section {self.section}" if self.section else None,
            f"p.{self.page}" if self.page else None,
            f"XBRL {self.xbrl_concept}" if self.xbrl_concept else None,
            f"period {self.period}" if self.period else None,
            f"accession {self.accession_number}" if self.accession_number else None,
        ]
        return ", ".join(p for p in parts if p) or "document"


class Evidence(BaseModel):
    """An exact excerpt or datum from a Source. `text` is untrusted content."""

    id: str
    source_id: str
    locator: EvidenceLocator = Field(default_factory=EvidenceLocator)
    text: str = Field(max_length=MAX_EVIDENCE_CHARS)
    injection_flags: list[str] = Field(default_factory=list)

    @classmethod
    def make(cls, *, source_id: str, text: str, locator: EvidenceLocator | None = None,
             injection_flags: list[str] | None = None) -> Evidence:
        loc = locator or EvidenceLocator()
        clipped = text[:MAX_EVIDENCE_CHARS]
        return cls(id=stable_id("ev", source_id, loc.model_dump_json(), clipped), source_id=source_id,
                   locator=loc, text=clipped, injection_flags=injection_flags or [])


class Citation(BaseModel):
    """Resolved claim→evidence→source chain, as rendered in reports."""

    evidence_id: str
    source_id: str
    source_title: str
    source_url: str | None
    publisher: str
    location: str
    quote: str
    is_snapshot: bool = False


def resolve_citation(evidence: Evidence, source: Source) -> Citation:
    return Citation(
        evidence_id=evidence.id,
        source_id=source.id,
        source_title=source.title,
        source_url=source.url,
        publisher=source.publisher,
        location=evidence.locator.describe(),
        quote=evidence.text[:600],
        is_snapshot=source.is_snapshot,
    )
