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


def _all_present(values: tuple[float | None, ...]) -> tuple[float, ...] | None:
    """The operands with every ``None`` ruled out, or ``None`` if one was missing.

    An ``any(v is None for v in values)`` guard is correct but invisible to a type checker, which then
    reads the rest of the function as arithmetic on ``float | None``. Narrowing once, here, keeps these
    helpers both checkable and honest about what they accept.
    """
    present: list[float] = []
    for value in values:
        if value is None:
            return None
        present.append(value)
    return tuple(present)


def safe_sub(*values: float | None) -> float | None:
    """Left-to-right subtraction; ``None`` if any operand is ``None`` or none were given."""
    present = _all_present(values)
    # Subtraction has no identity element to return for an empty call, and this module never raises.
    if not present:
        return None
    result = present[0]
    for value in present[1:]:
        result -= value
    return result


def safe_add(*values: float | None) -> float | None:
    """Sum; ``None`` if any operand is ``None``."""
    present = _all_present(values)
    return None if present is None else sum(present)


def safe_mul(*values: float | None) -> float | None:
    """Product; ``None`` if any operand is ``None``."""
    present = _all_present(values)
    if present is None:
        return None
    result = 1.0
    for value in present:
        result *= value
    return result


def median(values: list[float | None]) -> float | None:
    """Median of the non-``None`` values, or ``None`` if none are present."""
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return _median(clean)
