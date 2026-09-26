"""Assembles one running instance of the platform: providers, tools, agents, the `ResearchRunner` and
whichever persistence backend is actually reachable.

Shared by `api/app.py` (the HTTP server's lifespan) and `cli.py` (`meridian research`), so both start
from the exact same wiring logic and behave identically with or without Postgres.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from meridian.agents.base import AgentDeps
from meridian.agents.registry import build_agent_set
from meridian.api.concurrency import RunAdmission
from meridian.api.dispatch import InProcessDispatcher, RunDispatcher, WorkerDispatcher
from meridian.api.memory_store import LocalRunStore
from meridian.api.persistence import DbPreferenceStore, DbResearchMemoryStore
from meridian.api.security import RateLimiter
from meridian.core.config import Settings
from meridian.core.logging import get_logger
from meridian.db.run_store import DbRunStore
from meridian.db.session import check_database, create_db_engine, session_factory
from meridian.graph.checkpointing import CheckpointerHandle, build_checkpointer
from meridian.graph.jobs import RunQueue
from meridian.graph.runner import ResearchRunner, RunStore
from meridian.memory.inmemory import InMemoryPreferenceStore, InMemoryResearchMemoryStore
from meridian.observability.bus import EventBus, NullEventBus, RedisEventBus
from meridian.providers.factory import build_providers, build_retriever
from meridian.schemas.events import ProgressEvent
from meridian.tools.factory import build_tool_registry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from meridian.memory.types import PreferenceStore, ResearchMemoryStore
    from meridian.providers.registry import ProviderRegistry

log = get_logger(__name__)


class _ForwardingEventSink:
    """`AgentDeps.events` proxy, bound to the runner's own event router once it exists.

    Agents are built (with their `events` dependency already set) *before* `ResearchRunner` exists, but
    `ResearchRunner` owns the only sink that actually reaches live SSE subscribers and assigns `seq`
    (`graph.runner._RouterEventSink`, private to that instance -- `graph/runner.py` is frozen so we
    cannot have it accept an external sink). This proxy lets agent/tool-level events (e.g. `tool_called`)
    reach that same router once `bind()` is called, instead of going nowhere.
    """

    def __init__(self) -> None:
        self._target: object | None = None

    def bind(self, target: object) -> None:
        self._target = target

    async def emit(self, event: ProgressEvent) -> None:
        if self._target is not None:
            await self._target.emit(event)  # type: ignore[attr-defined]


async def probe_database(settings: Settings) -> bool:
    """Live reachability check, independent of which store backend the process picked at startup.

    Used by `/health` and `/system/status` so they reflect the database coming back (or going away)
    without requiring a restart, even though the run store itself is only chosen once, at startup.
    """
    if not settings.database_url:
        return False
    engine = create_db_engine(settings)
    try:
        return await check_database(engine)
    finally:
        await engine.dispose()


async def check_redis(redis_url: str | None) -> bool:
    if not redis_url:
        return False
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(redis_url, socket_connect_timeout=1.5, socket_timeout=2.0)
        try:
            return bool(await client.ping())
        finally:
            await client.aclose()
    except Exception:
        return False


@dataclass
class Runtime:
    settings: Settings
    runner: ResearchRunner
    store: LocalRunStore | DbRunStore
    admission: RunAdmission
    providers: ProviderRegistry
    preferences: PreferenceStore
    memory: ResearchMemoryStore
    rate_limiter: RateLimiter
    db_available: bool
    redis_available: bool
    engine: AsyncEngine | None = None
    sessions: async_sessionmaker[AsyncSession] | None = None
    checkpointer: CheckpointerHandle | None = None
    dispatcher: RunDispatcher | None = None
    queue: RunQueue | None = None
    bus: EventBus | None = None
    background_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    def track(self, task: asyncio.Task[None]) -> None:
        """Keep a strong reference to a fire-and-forget task so it can't be GC'd mid-flight."""
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    @property
    def durable_runs(self) -> bool:
        """Whether an in-flight run would survive a restart of this process."""
        return self.checkpointer is not None and self.checkpointer.durable

    async def aclose(self) -> None:
        await self.rate_limiter.close()
        if self.queue is not None:
            await self.queue.aclose()
        if self.bus is not None:
            await self.bus.aclose()
        if self.checkpointer is not None:
            await self.checkpointer.aclose()
        if self.engine is not None:
            await self.engine.dispose()


async def _build_bus(settings: Settings) -> EventBus:
    """A Redis event bus when one is configured and reachable, else a no-op one.

    Only worker mode strictly needs it -- in-process fan-out already reaches local subscribers -- but
    it is harmless when idle and means an API replica can stream a run another replica is driving.
    """
    if not settings.redis_url:
        return NullEventBus()
    bus = RedisEventBus(settings.redis_url)
    try:
        await bus.start()
        return bus
    except Exception as exc:
        log.warning("event_bus_unavailable_falling_back", error=str(exc), detail="live progress stays in-process")
        return NullEventBus()


async def _build_dispatcher(
    settings: Settings, runner: ResearchRunner, store: RunStore, admission: RunAdmission
) -> tuple[RunQueue | None, RunDispatcher]:
    """The worker dispatcher when configured *and* usable, otherwise the in-process one.

    Falling back rather than failing to boot is deliberate: a misconfigured queue should degrade to the
    behaviour this build has always had, loudly, not take the API down.
    """
    in_process = InProcessDispatcher(runner, admission)
    if settings.run_executor != "worker":
        return None, in_process
    if not settings.redis_url:
        log.warning("worker_executor_requires_redis_falling_back", detail="running queries in-process instead")
        return None, in_process

    queue = RunQueue(settings.redis_url)
    try:
        await queue.start()
    except Exception as exc:
        log.warning("run_queue_unavailable_falling_back", error=str(exc), detail="running queries in-process instead")
        return None, in_process

    log.info("run_executor_worker", limit=settings.max_concurrent_runs)
    return queue, WorkerDispatcher(runner, queue, store, limit=settings.max_concurrent_runs)


async def build_runtime(settings: Settings, *, use_database: bool = True) -> Runtime:
    db_available = False
    engine: AsyncEngine | None = None
    sessions: async_sessionmaker[AsyncSession] | None = None

    if use_database and settings.database_url:
        engine = create_db_engine(settings)
        db_available = await check_database(engine)
        if db_available:
            sessions = session_factory(engine)
        else:
            log.warning(
                "database_unavailable_falling_back_to_memory",
                detail="could not reach Postgres; using an in-memory run store for this process",
            )
            await engine.dispose()
            engine = None

    providers = build_providers(settings)
    tools = build_tool_registry()
    retriever = build_retriever(settings, providers, engine if db_available else None)

    memory: ResearchMemoryStore
    preferences: PreferenceStore
    store: LocalRunStore | DbRunStore
    if db_available and sessions is not None:
        store = DbRunStore(sessions, settings)
        memory = DbResearchMemoryStore(sessions)
        preferences = DbPreferenceStore(sessions)
    else:
        store = LocalRunStore()
        memory = InMemoryResearchMemoryStore()
        preferences = InMemoryPreferenceStore()

    sink_proxy = _ForwardingEventSink()
    deps = AgentDeps(
        settings=settings, providers=providers, tools=tools, retriever=retriever, events=sink_proxy, memory=memory
    )
    agents = build_agent_set(deps)
    checkpointer = await build_checkpointer(settings, use_database=db_available)
    bus = await _build_bus(settings)
    runner = ResearchRunner(agents, settings, store=store, checkpointer=checkpointer.saver, bus=bus)
    sink_proxy.bind(runner._sink)

    rate_limiter = RateLimiter(settings.rate_limit_per_minute, settings.redis_url)
    await rate_limiter.start()
    redis_available = rate_limiter.backend == "redis"
    if settings.redis_url and not redis_available:
        log.warning("redis_unavailable_falling_back_to_inprocess", detail="rate limiting will use in-process counters")

    admission = RunAdmission()
    queue, dispatcher = await _build_dispatcher(settings, runner, store, admission)

    return Runtime(
        settings=settings,
        runner=runner,
        store=store,
        admission=admission,
        dispatcher=dispatcher,
        queue=queue,
        bus=bus,
        providers=providers,
        preferences=preferences,
        memory=memory,
        rate_limiter=rate_limiter,
        db_available=db_available,
        redis_available=redis_available,
        checkpointer=checkpointer,
        engine=engine,
        sessions=sessions,
    )
