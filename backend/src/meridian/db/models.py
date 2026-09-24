"""SQLAlchemy 2 declarative ORM models for the Meridian persistence layer.

Column definitions for `documents` / `document_chunks` are copied verbatim from Task 4 of
`docs/superpowers/plans/2026-09-22-meridian-implementation.md` (the RAG pipeline task), since the
pgvector store queries these tables by exact column name.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from meridian.db.base import Base

EMBEDDING_DIM = 384


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserPreferenceModel(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CompanyModel(Base):
    __tablename__ = "companies"

    ticker: Mapped[str] = mapped_column(String(12), primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str | None] = mapped_column(String, nullable=True)
    sic: Mapped[str | None] = mapped_column(String, nullable=True)
    sic_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(4), nullable=True)
    state_of_incorporation: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SavedCompanyModel(Base):
    __tablename__ = "saved_companies"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ticker: Mapped[str] = mapped_column(
        String(12), ForeignKey("companies.ticker", ondelete="CASCADE"), primary_key=True
    )
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_research_id: Mapped[str | None] = mapped_column(String, nullable=True)


class ResearchSessionModel(Base):
    __tablename__ = "research_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    approval: Mapped[str] = mapped_column(String, nullable=False, default="not_required")
    ticker: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    company: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    llm_mode: Mapped[str] = mapped_column(String, nullable=False)
    data_mode: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchTaskModel(Base):
    __tablename__ = "research_tasks"

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent: Mapped[str] = mapped_column(String, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    wave: Mapped[int] = mapped_column(Integer, nullable=False)
    depends_on: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRunModel(Base):
    __tablename__ = "agent_runs"

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    agent: Mapped[str] = mapped_column(String, nullable=False, index=True)
    wave: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    findings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    tools_used: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolCallModel(Base):
    __tablename__ = "tool_calls"

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent: Mapped[str] = mapped_column(String, nullable=False)
    tool: Mapped[str] = mapped_column(String, nullable=False, index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMUsageModel(Base):
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceModel(Base):
    __tablename__ = "sources"

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    snapshot_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class EvidenceModel(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "source_id"],
            ["sources.session_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_evidence_source",
        ),
    )

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    injection_flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)


class FindingModel(Base):
    __tablename__ = "findings"

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section: Mapped[str] = mapped_column(String, nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    evidence_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    metric_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CriticReviewModel(Base):
    __tablename__ = "critic_reviews"

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    round: Mapped[int] = mapped_column(Integer, primary_key=True)
    overall_verdict: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviews: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    checks_run: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReportVersionModel(Base):
    __tablename__ = "report_versions"

    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("research_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackModel(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    agent: Mapped[str | None] = mapped_column(String, nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(12), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchEventModel(Base):
    __tablename__ = "research_events"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_research_events_session_id_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, ForeignKey("research_sessions.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    agent: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchMemoryModel(Base):
    """Append-only history of cached research knowledge per ticker/kind."""

    __tablename__ = "research_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# RAG tables — column definitions copied verbatim from Task 4's PgVectorStore spec.
# ---------------------------------------------------------------------------


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    cik: Mapped[str | None] = mapped_column(Text, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    form: Mapped[str | None] = mapped_column(Text, nullable=True)
    accession_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    snapshot_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list[DocumentChunkModel]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunkModel(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        Text, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    form: Mapped[str | None] = mapped_column(Text, nullable=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    section_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injection_flags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[DocumentModel] = relationship(back_populates="chunks")
