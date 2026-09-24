"""Deterministic financial calculation engine.

Pure functions only: no I/O, no logging of values, no LLM calls. Every number an agent reports
must trace back to a :class:`~meridian.schemas.financials.MetricValue` produced here, with its
formula and inputs recorded, so a critic agent can verify the claim.

Public API:

- :func:`compute_metrics` -- compute every supported metric for a company's statements.
- :func:`calculate` -- single-metric dispatch (used by the ``calculate_metric`` tool).
- :func:`run_dcf` -- discounted cash flow valuation.
- :func:`median` -- ``None``-safe median, for peer comparisons.
"""

from __future__ import annotations

from meridian.financial_engine.dcf import run_dcf
from meridian.financial_engine.metrics import calculate, compute_metrics
from meridian.financial_engine.safe import median

__all__ = ["calculate", "compute_metrics", "median", "run_dcf"]
