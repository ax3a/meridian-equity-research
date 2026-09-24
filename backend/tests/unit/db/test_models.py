"""Model-metadata assertions that need no live database.

Checks table names against Task 5's table list, composite primary keys where the plan requires
them, the `research_events` unique constraint, and the `document_chunks.embedding` vector column
— everything an integration test would otherwise have to hit Postgres to confirm.
"""

from __future__ import annotations

from pgvector.sqlalchemy import Vector

from meridian.db import models
from meridian.db.base import Base

EXPECTED_TABLES = {
    "users",
    "user_preferences",
    "companies",
    "saved_companies",
    "research_sessions",
    "research_tasks",
    "agent_runs",
    "tool_calls",
    "llm_usage",
    "sources",
    "evidence",
    "findings",
    "critic_reviews",
    "report_versions",
    "feedback",
    "research_events",
    "research_memory",
    "documents",
    "document_chunks",
}

# Expected primary-key column sets. Most are composite (session_id, id) style; user_preferences
# is single-column but included here so its PK is still asserted somewhere.
EXPECTED_PK_COLUMNS = {
    "user_preferences": {"user_id"},
    "saved_companies": {"user_id", "ticker"},
    "research_tasks": {"session_id", "task_id"},
    "agent_runs": {"session_id", "task_id"},
    "tool_calls": {"session_id", "id"},
    "sources": {"session_id", "id"},
    "evidence": {"session_id", "id"},
    "findings": {"session_id", "id"},
    "critic_reviews": {"session_id", "round"},
    "report_versions": {"session_id", "version"},
}


def test_all_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_evidence_sources_and_findings_have_composite_session_id_pk() -> None:
    for name in ("sources", "evidence", "findings"):
        table = Base.metadata.tables[name]
        pk_cols = {c.name for c in table.primary_key.columns}
        assert pk_cols == {"session_id", "id"}, f"{name} PK was {pk_cols}"


def test_composite_primary_keys() -> None:
    for name, expected_pk in EXPECTED_PK_COLUMNS.items():
        table = Base.metadata.tables[name]
        pk_cols = {c.name for c in table.primary_key.columns}
        assert pk_cols == expected_pk, f"{name} PK was {pk_cols}, expected {expected_pk}"


def test_research_events_has_unique_session_id_seq_constraint() -> None:
    table = Base.metadata.tables["research_events"]
    unique_col_sets = {frozenset(c.name for c in constraint.columns) for constraint in table.constraints} | {
        frozenset(c.name for c in index.columns) for index in table.indexes if index.unique
    }
    assert frozenset({"session_id", "seq"}) in unique_col_sets


def test_document_chunks_embedding_is_384_dim_vector() -> None:
    table = Base.metadata.tables["document_chunks"]
    embedding_col = table.c.embedding
    assert isinstance(embedding_col.type, Vector)
    assert embedding_col.type.dim == models.EMBEDDING_DIM == 384


def test_document_chunks_fk_cascades_from_documents() -> None:
    table = Base.metadata.tables["document_chunks"]
    fks = list(table.c.document_id.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "documents"
    assert fks[0].ondelete == "CASCADE"


def test_evidence_has_composite_fk_to_sources() -> None:
    table = Base.metadata.tables["evidence"]
    composite_fks = [fk for fk in table.foreign_key_constraints if len(fk.columns) == 2]
    assert len(composite_fks) == 1
    fk = composite_fks[0]
    assert {c.name for c in fk.columns} == {"session_id", "source_id"}
    assert fk.ondelete == "CASCADE"


def test_documents_and_document_chunks_id_columns_are_text_primary_keys() -> None:
    documents = Base.metadata.tables["documents"]
    chunks = Base.metadata.tables["document_chunks"]
    assert [c.name for c in documents.primary_key.columns] == ["id"]
    assert [c.name for c in chunks.primary_key.columns] == ["id"]
