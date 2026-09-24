"""Wires the RAG pipeline components (embedder + vector store + retriever) from `Settings`.

This is the single place other packages (agents/tools) should import from to get a working
`Retriever`: it picks `PgVectorStore` when an `AsyncEngine` is supplied and `InMemoryVectorStore`
otherwise, and builds the embedder according to `settings.embedding_provider`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from meridian.rag.embeddings import build_embedder
from meridian.rag.pgvector_store import PgVectorStore
from meridian.rag.retriever import HybridRetriever
from meridian.rag.store import InMemoryVectorStore, VectorStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

    from meridian.core.config import Settings
    from meridian.providers.base import FilingsProvider
    from meridian.rag.types import Retriever


def build_vector_store(settings: Settings, engine: AsyncEngine | None = None) -> VectorStore:
    if engine is not None:
        return PgVectorStore(engine)
    return InMemoryVectorStore()


def build_retriever(
    settings: Settings,
    filings_provider: FilingsProvider,
    *,
    engine: AsyncEngine | None = None,
    rerank: bool = True,
) -> Retriever:
    embedder = build_embedder(settings)
    store = build_vector_store(settings, engine)
    return HybridRetriever(store, embedder, filings_provider, rerank=rerank)
