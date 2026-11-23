"""Stated assumptions for the Northwind Components illustration.

Every number that is an input, rather than a calculated result, lives here.
The asset value, pricing loads, and salary scale were chosen before the
valuation was run and are not calibrated to a target funded status or premium.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Assumptions:
    """Valuation and plan provisions for one hypothetical measurement."""

    plan_name: str = "Northwind Components Pension Plan"
    measurement_date: date = date(2025, 12, 31)

    # Treasury HQM end-of-month spot curve. December 31, 2025 is the latest
    # year-end in the published 2024-2028 file used here.
    curve_year: int = 2025
    curve_month: int = 12

    # Hypothetical market value of plan assets at the measurement date.
    # A round assumption, fixed before any liability was calculated.
    market_value_of_assets: float = 200_000_000.0

    # Plan formula. Noncontributory final-average-pay plan, no COLA.
    accrual_rate: float = 0.015
    max_credited_service: float = 40.0
    normal_retirement_age: int = 65
    # Unreduced "30-and-out" at 62. Otherwise the model assumes participants
    # wait for the earliest unreduced commencement (no reduced early retirement).
    unreduced_age: int = 62
    unreduced_service: float = 30.0
    early_reduction_per_year: float = 0.05
    salary_scale: float = 0.035

    # ERISA-style qualified preretirement survivor annuity for married
    # non-retired participants: 50% of the valued life annuity, starting at the
    # member's assumed commencement age, only if the member dies before then.
    # Unmarried participants have no preretirement death benefit (the plan is
    # noncontributory, so there is no employee-contribution return).
    qpsa_continuation: float = 0.50

    # Insurer pricing indication. These are illustrative loads, not a carrier
    # price. qx multiplier below 1 lengthens longevity. A negative spread
    # discounts at a lower yield than the accounting curve.
    pricing_qx_multiplier: float = 0.90
    pricing_spread_bp: float = -50.0
    expense_per_life_per_year: float = 240.0
    premium_load: float = 0.035

    # Census generator.
    seed: int = 1001
    n_active: int = 520
    n_deferred: int = 310
    n_retiree: int = 640
    n_beneficiary: int = 110

    # Mortality scenarios applied on top of Pri-2012 / MP-2021.
    extra_improvement: float = 0.005  # +50 bps per year after the measurement date
    static_improvement_year: int = 2026  # freeze qx at the measurement-year rate

    omega: int = 120

    # Published statutory thresholds used only as data-review flags.
    # IRS 2025 415(b) dollar limit and 401(a)(17) compensation limit.
    limit_415b: float = 280_000.0
    limit_401a17: float = 350_000.0

    @property
    def valuation_year(self) -> int:
        return self.measurement_date.year

    @property
    def first_exposure_year(self) -> int:
        """Calendar year of the first year of mortality after the measurement date.

        The measurement is December 31, after that month's payment. The next
        year of life is the following calendar year.
        """
        return self.measurement_date.year + 1

    @property
    def expense_per_month(self) -> float:
        return self.expense_per_life_per_year / 12.0


def default_assumptions() -> Assumptions:
    return Assumptions()
