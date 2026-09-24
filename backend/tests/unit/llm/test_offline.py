from __future__ import annotations

import pytest

from meridian.core.errors import ProviderUnavailableError
from meridian.providers.llm.base import ChatMessage, LLMProvider, LLMRequest
from meridian.providers.llm.offline import OfflineLLMProvider
from meridian.schemas.enums import AgentName


def test_offline_provider_shape() -> None:
    provider = OfflineLLMProvider()
    assert provider.name == "offline"
    assert provider.generative is False
    assert isinstance(provider, LLMProvider)


async def test_offline_provider_raises_provider_unavailable() -> None:
    provider = OfflineLLMProvider()
    request = LLMRequest(
        agent=AgentName.COMPANY,
        tier="worker",
        system="system prompt",
        messages=[ChatMessage(role="user", content="hello")],
    )
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await provider.complete(request)
    assert exc_info.value.provider == "offline"
