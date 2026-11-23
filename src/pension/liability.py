"""Present values, funded status, and interest-rate sensitivity.

Cash flows are discounted on the spot curve one month at a time. There is no
single segment rate. The single effective rate reported alongside the curve
is the annual-effective yield that reproduces the curve present value of the
same expected payments. It is a disclosure summary, not an input.

Duration is reported two ways. The average payment time is the present-value
weighted mean of the payment dates. Effective duration and DV01 come from
parallel shifts of the spot curve, which is the statistic an LDI or PRT
hedge would use.
"""

from __future__ import annotations

import numpy as np

from pension.discount import DiscountCurve


def present_value(cashflows: np.ndarray, times: np.ndarray, curve: DiscountCurve) -> float:
    return float(np.sum(np.asarray(cashflows, dtype=float) * curve.discount_factor(times)))


def average_payment_time(cashflows: np.ndarray, times: np.ndarray, curve: DiscountCurve) -> float:
    """Present-value-weighted average time of expected payments, in years."""
    weighted = np.asarray(cashflows, dtype=float) * curve.discount_factor(times)
    total = float(weighted.sum())
    if total <= 0:
        return float("nan")
    return float(np.sum(np.asarray(times, dtype=float) * weighted) / total)


def single_effective_rate(cashflows: np.ndarray, times: np.ndarray, target_pv: float) -> float:
    """Annual-effective rate whose flat discounting matches `target_pv`."""
    flows = np.asarray(cashflows, dtype=float)
    time = np.asarray(times, dtype=float)

    def pv(rate: float) -> float:
        return float(np.sum(flows * np.power(1.0 + rate, -time)))

    low, high = -0.01, 0.08
    for _ in range(12):
        if pv(high) > target_pv:
            high += 0.05
        elif pv(low) < target_pv:
            low -= 0.02
        else:
            break
    for _ in range(80):
        mid = (low + high) / 2.0
        if pv(mid) > target_pv:
            low = mid
        else:
            high = mid
    return float((low + high) / 2.0)


def effective_duration(pv_down: float, pv_up: float, pv_base: float, shock: float = 0.01) -> float:
    """Central effective duration. `shock` is the absolute yield move (0.01 = 100 bp)."""
    if pv_base == 0:
        return float("nan")
    return (pv_down - pv_up) / (2.0 * pv_base * shock)


def effective_convexity(pv_down: float, pv_up: float, pv_base: float, shock: float = 0.01) -> float:
    if pv_base == 0:
        return float("nan")
    return (pv_down + pv_up - 2.0 * pv_base) / (pv_base * shock * shock)


def liability_dv01(pv_down_1bp: float, pv_up_1bp: float) -> float:
    """Dollar increase in the liability if the spot curve falls by about 1 bp.

    Central difference: (PV at -1 bp - PV at +1 bp) / 2.
    """
    return (pv_down_1bp - pv_up_1bp) / 2.0


def funded_status(assets: float, liability: float) -> dict[str, float]:
    return {
        "assets": assets,
        "liability": liability,
        "surplus": assets - liability,
        "funded_ratio": assets / liability if liability else float("nan"),
    }
