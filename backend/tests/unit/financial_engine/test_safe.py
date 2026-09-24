from __future__ import annotations

import pytest

from meridian.financial_engine.safe import median, safe_add, safe_div, safe_mul, safe_sub


class TestSafeDiv:
    def test_normal_division(self):
        assert safe_div(10.0, 4.0) == pytest.approx(2.5)

    def test_none_numerator(self):
        assert safe_div(None, 4.0) is None

    def test_none_denominator(self):
        assert safe_div(10.0, None) is None

    def test_zero_denominator(self):
        assert safe_div(10.0, 0.0) is None

    def test_negative_denominator_still_divides(self):
        assert safe_div(10.0, -2.0) == pytest.approx(-5.0)


class TestSafeSub:
    def test_normal(self):
        assert safe_sub(10.0, 3.0, 2.0) == pytest.approx(5.0)

    def test_none_anywhere(self):
        assert safe_sub(10.0, None) is None
        assert safe_sub(None, 3.0) is None


class TestSafeAdd:
    def test_normal(self):
        assert safe_add(1.0, 2.0, 3.0) == pytest.approx(6.0)

    def test_none_anywhere(self):
        assert safe_add(1.0, None) is None


class TestSafeMul:
    def test_normal(self):
        assert safe_mul(2.0, 3.0) == pytest.approx(6.0)

    def test_none_anywhere(self):
        assert safe_mul(2.0, None) is None


class TestMedian:
    def test_basic(self):
        assert median([1.0, 2.0, 3.0]) == pytest.approx(2.0)

    def test_ignores_none(self):
        assert median([1.0, None, 3.0]) == pytest.approx(2.0)

    def test_all_none(self):
        assert median([None, None]) is None

    def test_empty(self):
        assert median([]) is None

    def test_even_count(self):
        assert median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)
