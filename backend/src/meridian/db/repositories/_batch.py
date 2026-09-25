"""Splitting bulk inserts so they stay inside the driver's bind-parameter limit.

A single multi-row `INSERT ... VALUES (...), (...)` carries one bind parameter per column per row, and
asyncpg's protocol caps a statement at 32767 of them. One research run produces thousands of evidence
rows, so writing them in one statement fails with "the number of query arguments cannot exceed 32767".
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

MAX_BIND_PARAMS = 32767
# Well under the protocol cap, and small enough to keep individual statements quick.
MAX_ROWS_PER_STATEMENT = 500


def batched_rows(rows: Sequence[dict[str, Any]], *, columns_per_row: int) -> Iterator[list[dict[str, Any]]]:
    """Yield row chunks that stay within the bind-parameter limit."""
    if not rows:
        return
    per_statement = max(1, min(MAX_ROWS_PER_STATEMENT, MAX_BIND_PARAMS // max(1, columns_per_row)))
    for start in range(0, len(rows), per_statement):
        yield list(rows[start : start + per_statement])
