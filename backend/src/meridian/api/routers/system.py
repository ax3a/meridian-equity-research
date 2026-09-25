"""`/api/v1/system/status` -- version, LLM/data mode, DB/Redis reachability, provider configuration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from meridian.api.security import authenticate_and_throttle
from meridian.api.status import build_system_status
from meridian.api.wiring import Runtime, check_redis, probe_database
from meridian.schemas.api import SystemStatus

router = APIRouter(tags=["system"], dependencies=[Depends(authenticate_and_throttle)])


@router.get("/system/status", response_model=SystemStatus)
async def system_status(request: Request) -> SystemStatus:
    runtime: Runtime = request.app.state.runtime
    db_available = await probe_database(runtime.settings)
    redis_available = await check_redis(runtime.settings.redis_url)
    active_runs = await runtime.store.count_active()
    return build_system_status(
        runtime.settings, db_available=db_available, redis_available=redis_available, active_runs=active_runs
    )
