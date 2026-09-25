"""`/api/v1/companies/search` -- ticker/name lookup used by the frontend's company picker."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from meridian.api.security import authenticate_and_throttle
from meridian.api.wiring import Runtime
from meridian.schemas.api import CompanySearchResult

router = APIRouter(tags=["companies"], dependencies=[Depends(authenticate_and_throttle)])


@router.get("/companies/search", response_model=CompanySearchResult)
async def search_companies(request: Request, q: str = Query(min_length=1, max_length=100)) -> CompanySearchResult:
    runtime: Runtime = request.app.state.runtime
    results = await runtime.providers.directory.search(q, limit=10)
    return CompanySearchResult(results=results)
