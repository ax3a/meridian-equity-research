"""`/api/v1/dashboard` -- the landing-page summary: recent runs, saved companies, system health, stats.

There is currently no endpoint that lets a user save a company (the frozen contract's `SavedCompany`
exists for future use), so `saved_companies` is always empty; everything else is real.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from meridian.api import live, views
from meridian.api.security import authenticate_and_throttle
from meridian.api.status import build_system_status
from meridian.api.wiring import Runtime, check_redis, probe_database
from meridian.schemas.api import DashboardView
from meridian.schemas.enums import TERMINAL_RUN_STATUSES

router = APIRouter(tags=["dashboard"], dependencies=[Depends(authenticate_and_throttle)])


@router.get("/dashboard", response_model=DashboardView)
async def dashboard(request: Request, recent_limit: int = Query(default=10, ge=1, le=50)) -> DashboardView:
    runtime: Runtime = request.app.state.runtime
    records = await runtime.store.list_recent(recent_limit)
    live_records = [await live.live_record(runtime, r.session_id) or r for r in records]
    recent_runs = [views.to_summary(runtime.settings, r) for r in live_records]

    db_available = await probe_database(runtime.settings)
    redis_available = await check_redis(runtime.settings.redis_url)
    active_runs = await runtime.store.count_active()
    system = build_system_status(
        runtime.settings, db_available=db_available, redis_available=redis_available, active_runs=active_runs
    )

    completed = sum(1 for r in recent_runs if r.status.value in {s.value for s in TERMINAL_RUN_STATUSES})
    stats = {
        "recent_runs": float(len(recent_runs)),
        "completed_runs": float(completed),
        "active_runs": float(active_runs),
    }

    return DashboardView(recent_runs=recent_runs, saved_companies=[], system=system, stats=stats)
