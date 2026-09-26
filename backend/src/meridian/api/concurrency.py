"""Bounds how many research runs execute concurrently in this process.

`ResearchRunner` will happily start as many background `asyncio.Task`s as it's asked to; nothing in the
graph layer limits that. `RunAdmission` is a small counting guard the API checks before calling
`runner.start`/`runner.resume`, releasing the slot once the run goes idle (paused for approval or
terminal) via `runner.wait_idle`.
"""

from __future__ import annotations

import asyncio

from meridian.core.config import get_settings
from meridian.core.logging import get_logger

log = get_logger(__name__)


def _configured_limit() -> int:
    """The limit from `Settings`, like every other tunable in the system.

    This used to read `os.environ["MERIDIAN_MAX_CONCURRENT_RUNS"]` directly, which was wrong twice
    over: the name did not match any settings field (`Settings` declares no env prefix, so it binds
    `MAX_CONCURRENT_RUNS`), and pydantic-settings never copies `.env` entries into `os.environ` -- so
    setting it in `.env`, the mechanism the README documents, did nothing at all. It appeared to work
    only under Docker, where compose exports the env file into the real environment.
    """
    return get_settings().max_concurrent_runs


class RunAdmission:
    def __init__(self, limit: int | None = None) -> None:
        self._limit = limit if limit is not None else _configured_limit()
        self._active = 0
        self._lock = asyncio.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def active(self) -> int:
        return self._active

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._active >= self._limit:
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)


async def run_and_release(admission: RunAdmission, wait_idle) -> None:
    """Background task: wait for the run to go idle (paused or terminal), then free its admission slot."""
    try:
        await wait_idle()
    except Exception:  # the run's own error handling already logged; this is just slot bookkeeping
        log.exception("wait_idle_failed")
    finally:
        await admission.release()
