"""`/api/v1/preferences` -- per-user report/valuation defaults.

There is no login system yet, so callers may pass `?user_id=`; everyone else shares a single
`"default"` user's preferences, which is enough for the single-operator local-dev deployment this
platform ships as today.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from meridian.api.security import authenticate_and_throttle
from meridian.api.wiring import Runtime
from meridian.schemas.api import UserPreferences

router = APIRouter(tags=["preferences"], dependencies=[Depends(authenticate_and_throttle)])

DEFAULT_USER_ID = "default"


@router.get("/preferences", response_model=UserPreferences)
async def get_preferences(request: Request, user_id: str = Query(default=DEFAULT_USER_ID)) -> UserPreferences:
    runtime: Runtime = request.app.state.runtime
    return await runtime.preferences.get(user_id)


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    payload: UserPreferences, request: Request, user_id: str = Query(default=DEFAULT_USER_ID)
) -> UserPreferences:
    runtime: Runtime = request.app.state.runtime
    await runtime.preferences.put(user_id, payload)
    return payload
