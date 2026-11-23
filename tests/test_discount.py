"""Discount-curve identities and the published December 31, 2025 HQM node."""

import numpy as np
import pytest

from pension.discount import DiscountCurve, load_hqm_curve
from pension.liability import present_value, single_effective_rate


def test_discount_factor_at_zero_is_one():
    curve = DiscountCurve.flat_annual_effective(0.04)
    assert curve.discount_factor(0) == 1.0


def test_semiannual_spot_discount_matches_closed_form():
    curve = DiscountCurve(
        maturities=np.array([0.5, 10.0, 30.0]),
        spots=np.array([0.05, 0.05, 0.05]),
        name="flat 5% BEY",
        compounding="semiannual",
    )
    assert curve.discount_factor(10) == pytest.approx(1.0 / (1.025**20))


def test_interpolation_is_linear_in_the_spot():
    curve = DiscountCurve(
        maturities=np.array([10.0, 20.0]),
        spots=np.array([0.04, 0.06]),
        name="two node",
        compounding="semiannual",
    )
    assert float(curve.spot(15)) == pytest.approx(0.05)


def test_parallel_shock_lowers_a_present_value():
    curve = DiscountCurve.flat_annual_effective(0.04)
    times = np.array([5.0, 15.0])
    cash = np.array([100.0, 100.0])
    base = present_value(cash, times, curve)
    higher = present_value(cash, times, curve.shocked(100))
    assert higher < base


def test_hqm_december_2025_ten_year_spot():
    curve = load_hqm_curve(2025, 12)
    assert float(curve.spot(10)) == pytest.approx(0.0496, abs=1e-6)
    assert float(curve.spot(30)) == pytest.approx(0.0604, abs=1e-6)
    assert curve.compounding == "semiannual"


def test_effective_rate_recovers_a_flat_annual_curve():
    curve = DiscountCurve.flat_annual_effective(0.05)
    times = np.array([1.0, 5.0, 12.0, 20.0])
    cash = np.array([10.0, 20.0, 30.0, 15.0])
    pv = present_value(cash, times, curve)
    assert single_effective_rate(cash, times, pv) == pytest.approx(0.05, abs=1e-8)


def test_effective_rate_converts_semiannual_spots():
    """A flat 5% bond-equivalent yield is 5.0625% annual effective."""
    curve = DiscountCurve(
        maturities=np.array([1.0, 30.0]),
        spots=np.array([0.05, 0.05]),
        name="5% BEY",
        compounding="semiannual",
    )
    times = np.array([10.0])
    cash = np.array([1_000.0])
    pv = present_value(cash, times, curve)
    solved = single_effective_rate(cash, times, pv)
    assert solved == pytest.approx((1.025**2) - 1.0, abs=1e-8)
