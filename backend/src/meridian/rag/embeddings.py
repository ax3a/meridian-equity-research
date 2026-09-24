"""Embedding providers for the RAG pipeline.

`HashingEmbedder` is fully deterministic and offline (token -> signed hash bucket, L2-normalised), so
unit tests never need to download a model. `FastEmbedProvider` lazily loads a local fastembed model on
first use (off the event loop, via `asyncio.to_thread`) and transparently falls back to
`HashingEmbedder` if the model can't be imported or loaded (no network, no cached weights, etc).
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING

from meridian.core.logging import get_logger

if TYPE_CHECKING:
    from meridian.core.config import Settings
    from meridian.providers.base import EmbeddingProvider

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"\w+")


class HashingEmbedder:
    """Deterministic, offline embedder: hashes each token into a signed bucket, then L2-normalises."""

    name = "hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class FastEmbedProvider:
    """Wraps `fastembed`. Construction does no I/O; the model loads lazily on the first `embed` call."""

    name = "fastembed"

    def __init__(self, model_name: str, cache_dir: Path, dim: int = 384) -> None:
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.dim = dim
        self._model: object | None = None
        self._fallback: HashingEmbedder | None = None
        self._lock = asyncio.Lock()

    def _load_model(self) -> object:
        from fastembed import TextEmbedding

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return TextEmbedding(model_name=self.model_name, cache_dir=str(self.cache_dir))

    async def _ensure_ready(self) -> None:
        if self._model is not None or self._fallback is not None:
            return
        async with self._lock:
            if self._model is not None or self._fallback is not None:
                return
            try:
                self._model = await asyncio.to_thread(self._load_model)
            except Exception as exc:
                logger.warning("fastembed_load_failed", model=self.model_name, error=str(exc))
                self._fallback = HashingEmbedder(dim=self.dim)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        await self._ensure_ready()
        if self._fallback is not None:
            return await self._fallback.embed(texts)
        model = self._model

        def _run() -> list[list[float]]:
            return [vec.tolist() for vec in model.embed(texts)]  # type: ignore[union-attr]

        return await asyncio.to_thread(_run)


def build_embedder(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder(dim=settings.embedding_dim)
    return FastEmbedProvider(settings.embedding_model, settings.model_cache_dir, dim=settings.embedding_dim)
