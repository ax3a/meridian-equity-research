"""`RunAdmission` bounds how many runs execute at once, and takes its limit from `Settings`.

It used to read `os.environ["MERIDIAN_MAX_CONCURRENT_RUNS"]` itself. That name matched no settings
field -- `Settings` declares no env prefix, so it binds `MAX_CONCURRENT_RUNS` -- and pydantic-settings
never copies `.env` entries into `os.environ`, so configuring it the way the README documents had no
effect outside Docker, where compose exports the env file into the real environment.
"""

from __future__ import annotations

import asyncio

import pytest

from meridian.api.concurrency import RunAdmission, run_and_release
from meridian.core.config import Settings, get_settings


def test_limit_comes_from_settings(monkeypatch) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "7")
    get_settings.cache_clear()
    try:
        assert Settings().max_concurrent_runs == 7
        assert RunAdmission().limit == 7
    finally:
        get_settings.cache_clear()


def test_an_env_file_value_reaches_the_limit(monkeypatch, tmp_path) -> None:
    """The documented mechanism: `.env`, read by pydantic-settings, not by `os.environ`."""
    env_file = tmp_path / ".env"
    env_file.write_text("MAX_CONCURRENT_RUNS=9\n", encoding="utf-8")

    settings = Settings(_env_file=str(env_file))  # type: ignore[call-arg]

    assert settings.max_concurrent_runs == 9
    assert "MAX_CONCURRENT_RUNS" not in __import__("os").environ, (
        "pydantic-settings does not export .env into os.environ -- which is why reading os.environ "
        "directly silently ignored the file"
    )


async def test_admits_up_to_the_limit_then_refuses() -> None:
    admission = RunAdmission(limit=2)

    assert await admission.try_acquire() is True
    assert await admission.try_acquire() is True
    assert await admission.try_acquire() is False, "the third run must be refused, not queued"
    assert admission.active == 2


async def test_a_released_slot_is_reusable() -> None:
    admission = RunAdmission(limit=1)

    assert await admission.try_acquire() is True
    assert await admission.try_acquire() is False
    await admission.release()
    assert admission.active == 0
    assert await admission.try_acquire() is True


async def test_release_never_goes_negative() -> None:
    """A double release would otherwise inflate capacity permanently."""
    admission = RunAdmission(limit=1)

    await admission.release()
    await admission.release()

    assert admission.active == 0
    assert await admission.try_acquire() is True
    assert await admission.try_acquire() is False


async def test_the_slot_is_freed_even_when_the_run_raises() -> None:
    """A run that blows up must not leak its slot; four such runs would wedge the API at 429 forever."""
    admission = RunAdmission(limit=1)
    assert await admission.try_acquire() is True

    async def boom() -> None:
        raise RuntimeError("run exploded")

    await run_and_release(admission, boom)

    assert admission.active == 0
    assert await admission.try_acquire() is True


@pytest.mark.parametrize("limit", [1, 4])
async def test_concurrent_acquires_never_exceed_the_limit(limit: int) -> None:
    admission = RunAdmission(limit=limit)

    granted = await asyncio.gather(*(admission.try_acquire() for _ in range(20)))

    assert sum(granted) == limit
    assert admission.active == limit
