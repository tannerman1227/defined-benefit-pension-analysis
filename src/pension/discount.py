"""Discount curves.

The accounting curve is the U.S. Treasury High Quality Market (HQM) corporate
bond spot curve, the public curve specified for Pension Protection Act funding
targets. Rates are the end-of-month series published by Treasury.

Treasury's HQM methodology quotes spot rates as semiannually compounded
bond-equivalent yields (the same convention as Treasury securities). A cash
flow at time t years is discounted with

    DF(t) = 1 / (1 + s(t) / 2) ** (2 t)

where s(t) is the spot rate linearly interpolated in maturity. The curve is
published at half-year maturities from 0.5 through 100 years. Before 0.5 years
the 6-month rate is used; past 100 years the 100-year rate is held flat.

The FTSE Pension Discount Curve is a commercial AA curve and is not
redistributed here. HQM includes AAA, AA, and A bonds, so it is a high-quality
corporate curve, not a pure AA GAAP curve. It is used as the documented public
stand-in for a pension discount curve.

Source file: data/raw/hqm_eom_spot_2024_2028.xls
https://home.treasury.gov/data/treasury-coupon-issues-and-corporate-bond-yield-curve/corporate-bond-yield-curve
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import xlrd

from pension.paths import RAW_DATA

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_HQM_FILE = RAW_DATA / "hqm_eom_spot_2024_2028.xls"


@dataclass(frozen=True)
class DiscountCurve:
    """A spot curve with either semiannual bond-equivalent or annual-effective compounding."""

    maturities: np.ndarray
    spots: np.ndarray
    name: str
    compounding: str  # "semiannual" or "annual_effective"
    shock_bp: float = 0.0

    def __post_init__(self) -> None:
        if self.compounding not in {"semiannual", "annual_effective"}:
            raise ValueError(f"Unknown compounding {self.compounding}")
        if len(self.maturities) != len(self.spots):
            raise ValueError("Maturity and spot arrays differ in length")
        if np.any(self.spots <= -0.99):
            raise ValueError("Spot rate implies a non-positive discount base")

    def spot(self, t: np.ndarray | float) -> np.ndarray:
        query = np.asarray(t, dtype=float)
        scalar = query.ndim == 0
        interpolated = np.interp(
            np.atleast_1d(query),
            self.maturities,
            self.spots,
            left=float(self.spots[0]),
            right=float(self.spots[-1]),
        )
        return interpolated[0] if scalar else interpolated

    def discount_factor(self, t: np.ndarray | float) -> np.ndarray:
        """Present-value factor for a cash flow at time t, with DF(0) = 1."""
        query = np.asarray(t, dtype=float)
        scalar = query.ndim == 0
        time = np.atleast_1d(query).astype(float)
        out = np.ones_like(time)
        positive = time > 0
        if np.any(positive):
            spot = np.asarray(self.spot(time[positive]), dtype=float)
            elapsed = time[positive]
            if self.compounding == "semiannual":
                out[positive] = 1.0 / np.power(1.0 + spot / 2.0, 2.0 * elapsed)
            else:
                out[positive] = np.power(1.0 + spot, -elapsed)
        return out[0] if scalar else out

    def shocked(self, basis_points: float, name: str | None = None) -> "DiscountCurve":
        """Parallel move of every spot, floored so the discount base stays positive."""
        moved = np.maximum(self.spots + basis_points / 10_000.0, 1e-6)
        label = name or f"{self.name} {basis_points:+.0f} bp"
        return DiscountCurve(
            maturities=self.maturities.copy(),
            spots=moved,
            name=label,
            compounding=self.compounding,
            shock_bp=self.shock_bp + basis_points,
        )

    @staticmethod
    def flat_annual_effective(rate: float, name: str = "Flat annual effective") -> "DiscountCurve":
        """Single annual-effective rate, stored as a one-node curve."""
        if rate <= -0.99:
            raise ValueError("Flat rate is not discountable")
        return DiscountCurve(
            maturities=np.array([1.0]),
            spots=np.array([float(rate)]),
            name=name,
            compounding="annual_effective",
        )

    def rate_table(self, tenors: tuple[float, ...] = (0.5, 1, 2, 5, 10, 15, 20, 30)) -> dict[float, float]:
        return {tenor: float(self.spot(tenor)) for tenor in tenors}


def load_hqm_curve(year: int, month: int, path=None) -> DiscountCurve:
    """Load one Treasury HQM end-of-month spot curve. `month` is 1-12."""
    if month < 1 or month > 12:
        raise ValueError("month must be 1-12")
    source = path or _HQM_FILE
    book = xlrd.open_workbook(source)
    sheet = book.sheet_by_index(0)
    target_month = _MONTHS[month - 1]
    column = None
    current_year = None
    for col in range(sheet.ncols):
        year_cell = sheet.cell_value(3, col)
        if year_cell != "":
            current_year = int(year_cell)
        month_cell = sheet.cell_value(4, col)
        if current_year == year and month_cell == target_month:
            column = col
            break
    if column is None:
        raise ValueError(f"No HQM end-of-month curve for {year}-{month:02d} in {source}")

    maturities: list[float] = []
    spots: list[float] = []
    for row in range(6, sheet.nrows):
        maturity = sheet.cell_value(row, 0)
        rate = sheet.cell_value(row, column)
        if maturity == "" or rate == "":
            continue
        maturities.append(float(maturity))
        spots.append(float(rate) / 100.0)
    if len(maturities) < 10:
        raise ValueError(f"HQM curve for {year}-{month:02d} has too few nodes")
    return DiscountCurve(
        maturities=np.asarray(maturities, dtype=float),
        spots=np.asarray(spots, dtype=float),
        name=f"Treasury HQM end-of-month {year}-{month:02d}",
        compounding="semiannual",
    )
