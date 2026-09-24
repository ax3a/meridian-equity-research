"""Live reachability check for GDELT. Excluded by default; run explicitly with `-m live`.

GDELT enforces an informal "one request per 5 seconds" rate limit (see `providers.news.gdelt` and the
`api.gdeltproject.org` entry added to `HOST_RATE`), so this suite intentionally contains a single test.
"""

from __future__ import annotations

import pytest

from meridian.providers.news.gdelt import GdeltNewsProvider
from meridian.schemas.research import CompanyIdentity

pytestmark = pytest.mark.live


async def test_gdelt_doc_api_is_reachable(http_client) -> None:
    provider = GdeltNewsProvider(http_client)
    company = CompanyIdentity(name="Apple Inc.", ticker="AAPL", cik="320193")

    result = await provider.search_news(company, days=7, limit=5)

    assert isinstance(result.data, list)
