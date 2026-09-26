"""A whole research run through the generative path, over HTTP.

This is the gap the README called the biggest untested surface. Every run before it took the offline
branch: `OfflineLLMProvider.complete` raises, agents check `self.generative` and synthesise
deterministically instead, so the seven `_run_generative` methods, the supervisor's plan refinement,
the critic's generative review and the writer's drafting had never executed outside unit tests holding
a scripted provider.

A scripted provider cannot close that gap, because it replaces the provider: it proves the callers
behave given a response, not that a request we build is one a server accepts, nor that a response a
server returns is one we read correctly. Pointing the real `OpenAICompatLLMProvider` at a real HTTP
server does close it -- the only thing left untested afterwards is a specific vendor's quirks.
"""

from __future__ import annotations

import pytest

from meridian.api.wiring import build_runtime
from meridian.core.config import Settings
from meridian.schemas.enums import RunStatus
from meridian.schemas.research import ResearchRequest
from tests.integration.llm.fake_openai_server import running_server, schema_aware_responder

pytestmark = pytest.mark.integration


def _settings(base_url: str) -> Settings:
    return Settings(
        sec_user_agent="Meridian Test test@example.com",
        redis_url=None,
        llm_provider="auto",  # the suite pins offline globally; this test is about the generative path
        llm_base_url=base_url,
        model_planner="fake-model",
        model_worker="fake-model",
        model_critic="fake-model",
        model_writer="fake-model",
        require_approval_default=False,
        data_mode="snapshot",  # recorded provider data, so the run needs no network beyond the fake
    )


async def test_a_full_run_completes_through_the_generative_path() -> None:
    async with running_server(schema_aware_responder) as fake:
        settings = _settings(fake.base_url)
        runtime = await build_runtime(settings, use_database=False)
        assert runtime.providers.llm.generative is True, "the run must not quietly fall back to offline"
        assert runtime.providers.llm.name == "openai_compat"

        try:
            session_id = await runtime.runner.start(
                ResearchRequest(query="Analyse Microsoft", ticker="MSFT", depth="quick")
            )
            await runtime.runner.wait_idle(session_id)
            state = await runtime.runner.status(session_id)
        finally:
            await runtime.aclose()

    assert state is not None
    assert state.status is RunStatus.COMPLETED, f"run ended {state.status} with errors={state.errors}"
    assert fake.requests, "the generative path must actually have called the model"

    # Every request the agents built has to be one the endpoint accepted, with the system prompt kept
    # separate from evidence -- the injection defence depends on that separation surviving translation.
    for payload in fake.requests:
        assert payload["messages"][0]["role"] == "system"
        assert isinstance(payload["messages"][0]["content"], str)
        assert payload["model"] == "fake-model"
        assert payload["max_tokens"] > 0


async def test_retrieved_evidence_never_reaches_the_system_prompt() -> None:
    """Untrusted filing text belongs in the user turn, inside a delimited block -- never as instruction.

    Worth asserting on the wire rather than in the prompt builder: this is the first time those prompts
    have been serialised and sent anywhere, and a translation bug that folded evidence into `system`
    would silently undo the defence.
    """
    async with running_server(schema_aware_responder) as fake:
        settings = _settings(fake.base_url)
        runtime = await build_runtime(settings, use_database=False)
        try:
            session_id = await runtime.runner.start(
                ResearchRequest(query="Analyse Microsoft", ticker="MSFT", depth="quick")
            )
            await runtime.runner.wait_idle(session_id)
        finally:
            await runtime.aclose()

    assert fake.requests
    for payload in fake.requests:
        system = payload["messages"][0]["content"]
        # The prompt *names* the delimiter, because it is telling the model what the rule is. What must
        # never appear there is evidence itself, and an evidence id is the marker of that: a rendered
        # block always carries `id="ev_..."`.
        assert 'id="ev_' not in system, "evidence was folded into the system prompt"

        rest = payload["messages"][1:]
        blocks = [m for m in rest if 'id="ev_' in str(m.get("content") or "")]
        for message in blocks:
            assert message["role"] in ("user", "tool"), "evidence must arrive as data, not as instruction"
