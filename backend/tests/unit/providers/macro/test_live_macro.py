"""Live reachability check for the Treasury macro provider. Excluded by default; run with `-m live`.

Findings (recorded 2026-09-24, see task report for detail): the Fiscal Data `avg_interest_rates` dataset
is reachable but has no 3M/2Y/10Y tenor breakdown, so `TreasuryMacroProvider` uses the Daily Treasury Par
Yield Curve CSV (`home.treasury.gov`) instead -- this test confirms *that* endpoint is reachable and
produces the three required indicator keys.
"""

from __future__ import annotations

import pytest

from meridian.providers.macro.treasury import TreasuryMacroProvider

pytestmark = pytest.mark.live


async def test_treasury_par_yield_csv_is_reachable(http_client) -> None:
    provider = TreasuryMacroProvider(http_client)

    result = await provider.get_indicators()

    keys = {ind.key for ind in result.data}
    assert keys == {"ust_3m", "ust_2y", "ust_10y"}
    assert all(ind.latest is not None for ind in result.data)
