from __future__ import annotations

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
