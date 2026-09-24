"""Initial schema: research sessions, evidence, reports, telemetry, memory, RAG tables.

The `documents` / `document_chunks` column definitions (including `embedding vector(384)`, the HNSW
cosine index and the GIN full-text index) are copied verbatim from Task 4 of
`docs/superpowers/plans/2026-09-22-meridian-implementation.md`.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-24

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "companies",
        sa.Column("ticker", sa.String(12), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("sic", sa.String(), nullable=True),
        sa.Column("sic_description", sa.Text(), nullable=True),
        sa.Column("fiscal_year_end", sa.String(4), nullable=True),
        sa.Column("state_of_incorporation", sa.String(), nullable=True),
        sa.Column("website", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "saved_companies",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "ticker",
            sa.String(12),
            sa.ForeignKey("companies.ticker", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("saved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_research_id", sa.String(), nullable=True),
    )

    op.create_table(
        "research_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("approval", sa.String(), nullable=False, server_default="not_required"),
        sa.Column("ticker", sa.String(12), nullable=True),
        sa.Column("company", JSONB(), nullable=True),
        sa.Column("llm_mode", sa.String(), nullable=False),
        sa.Column("data_mode", sa.String(), nullable=False),
        sa.Column("state", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_research_sessions_user_id", "research_sessions", ["user_id"])
    op.create_index("ix_research_sessions_ticker", "research_sessions", ["ticker"])
    op.create_index("ix_research_sessions_status", "research_sessions", ["status"])
    op.create_index("ix_research_sessions_created_at", "research_sessions", ["created_at"])

    op.create_table(
        "research_tasks",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("task_id", sa.String(), primary_key=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("wave", sa.Integer(), nullable=False),
        sa.Column("depends_on", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fingerprint", sa.String(), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )

    op.create_table(
        "agent_runs",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("task_id", sa.String(), primary_key=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("wave", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("findings", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("evidence_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tools_used", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_agent", "agent_runs", ["agent"])

    op.create_table(
        "tool_calls",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=False),
        sa.Column("arguments", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tool_calls_tool", "tool_calls", ["tool"])

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("research_sessions.id", ondelete="CASCADE")),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_usage_session_id", "llm_usage", ["session_id"])
    op.create_index("ix_llm_usage_agent", "llm_usage", ["agent"])
    op.create_index("ix_llm_usage_model", "llm_usage", ["model"])

    op.create_table(
        "sources",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("publisher", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_snapshot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("snapshot_date", sa.Date(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_table(
        "evidence",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("locator", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("injection_flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.ForeignKeyConstraint(
            ["session_id", "source_id"],
            ["sources.session_id", "sources.id"],
            ondelete="CASCADE",
            name="fk_evidence_source",
        ),
    )
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"])

    op.create_table(
        "findings",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("section", sa.String(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("evidence_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metric_refs", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.String(), nullable=False, server_default="medium"),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_findings_agent", "findings", ["agent"])

    op.create_table(
        "critic_reviews",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("round", sa.Integer(), primary_key=True),
        sa.Column("overall_verdict", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("reviews", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("checks_run", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "report_versions",
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("research_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("report", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("research_sessions.id", ondelete="CASCADE")),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=True),
        sa.Column("ticker", sa.String(12), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feedback_session_id", "feedback", ["session_id"])

    op.create_table(
        "research_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("research_sessions.id", ondelete="CASCADE")),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "seq", name="uq_research_events_session_id_seq"),
    )
    op.create_index("ix_research_events_session_id", "research_events", ["session_id"])

    op.create_table(
        "research_memory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(12), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_memory_ticker", "research_memory", ["ticker"])
    op.create_index("ix_research_memory_kind", "research_memory", ["kind"])
    op.create_index(
        "ix_research_memory_ticker_kind_created",
        "research_memory",
        ["ticker", "kind", "created_at"],
    )
    op.create_index("ix_research_memory_ticker_created", "research_memory", ["ticker", "created_at"])

    # --- RAG tables (column defs verbatim from Task 4) --------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("cik", sa.Text(), nullable=True),
        sa.Column("company", sa.Text(), nullable=True),
        sa.Column("form", sa.Text(), nullable=True),
        sa.Column("accession_number", sa.Text(), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("is_snapshot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("snapshot_date", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_ticker", "documents", ["ticker"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("document_id", sa.Text(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("form", sa.Text(), nullable=True),
        sa.Column("filing_date", sa.Date(), nullable=True),
        sa.Column("section_key", sa.Text(), nullable=True),
        sa.Column("section_title", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("injection_flags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_ticker_form", "document_chunks", ["ticker", "form"])
    op.execute(
        "CREATE INDEX ix_document_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX ix_document_chunks_text_fts ON document_chunks USING gin (to_tsvector('english', text))")


def downgrade() -> None:
    op.drop_index("ix_document_chunks_text_fts", table_name="document_chunks")
    op.drop_index("ix_document_chunks_embedding_hnsw", table_name="document_chunks")
    op.drop_index("ix_document_chunks_ticker_form", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("ix_documents_ticker", table_name="documents")
    op.drop_table("documents")

    op.drop_index("ix_research_memory_ticker_created", table_name="research_memory")
    op.drop_index("ix_research_memory_ticker_kind_created", table_name="research_memory")
    op.drop_index("ix_research_memory_kind", table_name="research_memory")
    op.drop_index("ix_research_memory_ticker", table_name="research_memory")
    op.drop_table("research_memory")

    op.drop_index("ix_research_events_session_id", table_name="research_events")
    op.drop_table("research_events")

    op.drop_index("ix_feedback_session_id", table_name="feedback")
    op.drop_table("feedback")

    op.drop_table("report_versions")
    op.drop_table("critic_reviews")

    op.drop_index("ix_findings_agent", table_name="findings")
    op.drop_table("findings")

    op.drop_index("ix_evidence_source_id", table_name="evidence")
    op.drop_table("evidence")

    op.drop_table("sources")

    op.drop_index("ix_llm_usage_model", table_name="llm_usage")
    op.drop_index("ix_llm_usage_agent", table_name="llm_usage")
    op.drop_index("ix_llm_usage_session_id", table_name="llm_usage")
    op.drop_table("llm_usage")

    op.drop_index("ix_tool_calls_tool", table_name="tool_calls")
    op.drop_table("tool_calls")

    op.drop_index("ix_agent_runs_agent", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_table("research_tasks")

    op.drop_index("ix_research_sessions_created_at", table_name="research_sessions")
    op.drop_index("ix_research_sessions_status", table_name="research_sessions")
    op.drop_index("ix_research_sessions_ticker", table_name="research_sessions")
    op.drop_index("ix_research_sessions_user_id", table_name="research_sessions")
    op.drop_table("research_sessions")

    op.drop_table("saved_companies")
    op.drop_table("user_preferences")
    op.drop_table("companies")
    op.drop_table("users")

    op.execute("DROP EXTENSION IF EXISTS vector")
