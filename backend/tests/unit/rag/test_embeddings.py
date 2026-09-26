from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

from meridian.core.config import Settings
from meridian.rag.embeddings import FastEmbedProvider, HashingEmbedder, build_embedder


async def test_hashing_embedder_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder(dim=384)
    [v1] = await embedder.embed(["Risk factors include competition and supply chain disruption."])
    [v2] = await embedder.embed(["Risk factors include competition and supply chain disruption."])
    assert v1 == v2
    assert len(v1) == 384
    norm = math.sqrt(sum(x * x for x in v1))
    assert norm == pytest.approx(1.0, abs=1e-6)


async def test_hashing_embedder_differs_for_different_text() -> None:
    embedder = HashingEmbedder(dim=384)
    [v1] = await embedder.embed(["risk factors and competition"])
    [v2] = await embedder.embed(["completely unrelated valuation multiples discussion"])
    assert v1 != v2


async def test_hashing_embedder_custom_dim() -> None:
    embedder = HashingEmbedder(dim=32)
    [v] = await embedder.embed(["hello world"])
    assert len(v) == 32


def test_build_embedder_defaults_to_hashing(tmp_path: Path) -> None:
    settings = Settings(embedding_provider="hashing", embedding_dim=384, model_cache_dir=tmp_path)
    embedder = build_embedder(settings)
    assert isinstance(embedder, HashingEmbedder)
    assert embedder.dim == 384


async def test_fastembed_provider_falls_back_to_hashing_on_load_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(self: FastEmbedProvider):
        raise RuntimeError("no network / model not cached")

    monkeypatch.setattr(FastEmbedProvider, "_load_model", _boom)

    provider = FastEmbedProvider("BAAI/bge-small-en-v1.5", tmp_path, dim=384)
    text = "management discussion and analysis of results of operations"
    result = await provider.embed([text])

    expected = await HashingEmbedder(dim=384).embed([text])
    assert result == expected


def test_fastembed_provider_construction_does_not_touch_network(tmp_path: Path) -> None:
    # Constructing must not import/load the model eagerly.
    provider = FastEmbedProvider("BAAI/bge-small-en-v1.5", tmp_path, dim=384)
    assert provider.dim == 384
    assert provider.name == "fastembed"


class _CountingModel:
    """Stands in for fastembed's TextEmbedding, recording batch sizes and concurrent entries."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self.batches: list[int] = []
        self.concurrent = 0
        self.max_concurrent = 0

    def embed(self, texts):
        import numpy as np

        self.batches.append(len(texts))
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            return [np.zeros(self.dim) for _ in texts]
        finally:
            self.concurrent -= 1


def _provider(model: _CountingModel, batch_size: int = 64) -> FastEmbedProvider:
    provider = FastEmbedProvider("test-model", Path("."), dim=model.dim, batch_size=batch_size)
    provider._model = model  # skip the real load
    return provider


async def test_embedding_is_split_into_bounded_batches() -> None:
    """One call for every chunk of a filing measured minutes inside a single uncancellable thread."""
    model = _CountingModel()
    provider = _provider(model, batch_size=64)

    vectors = await provider.embed([f"chunk {i}" for i in range(150)])

    assert len(vectors) == 150, "every input must still get a vector, in order"
    assert model.batches == [64, 64, 22]


async def test_concurrent_callers_never_enter_the_model_together() -> None:
    """One `TextEmbedding` wraps one ONNX session; concurrent `run()` on it deadlocked a real run.

    Two agents indexing *different* documents hit exactly this: the retriever's lock is per document,
    so it does not serialise them, and both threads parked inside onnxruntime with the CPU idle.
    """
    model = _CountingModel()
    provider = _provider(model, batch_size=8)

    await asyncio.gather(*(provider.embed([f"doc{d} chunk {i}" for i in range(40)]) for d in range(4)))

    assert model.max_concurrent == 1, f"{model.max_concurrent} concurrent entries into the ONNX session"


async def test_a_batch_size_below_one_is_not_allowed_to_stall_the_loop() -> None:
    model = _CountingModel()
    provider = _provider(model, batch_size=0)

    await provider.embed(["a", "b", "c"])

    assert provider.batch_size == 1
    assert model.batches == [1, 1, 1]
