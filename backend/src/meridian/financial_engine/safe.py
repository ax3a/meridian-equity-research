"""Arithmetic helpers that never raise.

Every other module in ``financial_engine`` builds on these primitives so that missing or
zero data always degrades to ``None`` (plus an explanatory note upstream) instead of raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median as _median


@dataclass(frozen=True)
class Calc:
    """An intermediate calculation result, carrying its own provenance.

    ``value`` is the computed number (or ``None`` when it could not be computed), ``formula``
    is a human-readable description of the calculation, ``inputs`` records every raw input that
    was consulted (present even when the value is ``None``, so a caller can see what was
    missing), and ``note`` explains why the value is ``None`` or otherwise not meaningful.
    """

    value: float | None
    formula: str
    inputs: dict[str, float | None] = field(default_factory=dict)
    note: str | None = None


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    """Divide, returning ``None`` for missing operands or a zero denominator."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def safe_sub(*values: float | None) -> float | None:
    """Left-to-right subtraction; ``None`` if any operand is ``None``."""
    if any(v is None for v in values):
        return None
    result = values[0]
    for v in values[1:]:
        result = result - v
    return result


def safe_add(*values: float | None) -> float | None:
    """Sum; ``None`` if any operand is ``None``."""
    if any(v is None for v in values):
        return None
    return sum(values)


def safe_mul(*values: float | None) -> float | None:
    """Product; ``None`` if any operand is ``None``."""
    if any(v is None for v in values):
        return None
    result = 1.0
    for v in values:
        result *= v
    return result


def median(values: list[float | None]) -> float | None:
    """Median of the non-``None`` values, or ``None`` if none are present."""
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return _median(clean)
