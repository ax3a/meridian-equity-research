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
    """Wraps `fastembed`. Construction does no I/O; the model loads lazily on the first `embed` call.

    Inference is serialised. One `TextEmbedding` wraps one ONNX Runtime session, and calling `run()` on
    it from two threads at once deadlocks: a run that indexed two documents concurrently hung forever
    with both threads parked inside `onnxruntime ... run` and the CPU idle. The retriever's lock is per
    *document*, so it does not prevent that -- two agents indexing different filings is exactly the case
    it allows. Nothing above can rescue it either, because the work sits in `asyncio.to_thread`, and a
    thread handed to an executor cannot be cancelled, so even the agent timeout could not fire.

    Serialising costs little: ONNX parallelises internally across its own thread pool, so one call at a
    time already uses the machine.
    """

    name = "fastembed"

    def __init__(self, model_name: str, cache_dir: Path, dim: int = 384, batch_size: int = 64) -> None:
        self.model_name = model_name
        self.cache_dir = Path(cache_dir)
        self.dim = dim
        self.batch_size = max(1, batch_size)
        self._model: object | None = None
        self._fallback: HashingEmbedder | None = None
        self._lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

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
        """Embed in batches, awaiting between them.

        A single call for every chunk of a filing measured ~100ms per chunk, so a large document was
        minutes inside one `asyncio.to_thread` -- and a thread handed to an executor cannot be
        cancelled, so `asyncio.timeout` around the agent could not fire and the run simply hung.
        Batching bounds each uncancellable step to a few seconds and returns control to the event loop
        between batches, which is what makes the agent timeout effective at all. Throughput is
        unaffected: per-chunk cost is flat from about 64 onwards.
        """
        await self._ensure_ready()
        if self._fallback is not None:
            return await self._fallback.embed(texts)
        model = self._model

        def _run(batch: list[str]) -> list[list[float]]:
            return [vec.tolist() for vec in model.embed(batch)]  # type: ignore[union-attr]

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            async with self._inference_lock:
                vectors.extend(await asyncio.to_thread(_run, batch))
        return vectors


def build_embedder(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder(dim=settings.embedding_dim)
    return FastEmbedProvider(
        settings.embedding_model,
        settings.model_cache_dir,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
    )
