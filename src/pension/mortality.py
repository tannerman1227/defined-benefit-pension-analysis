"""Pri-2012 amount-weighted mortality with generational Scale MP-2021.

Base rates are the Society of Actuaries Pri-2012 private retirement plans
tables, total dataset, amount-weighted. The base year is 2012. Scale MP-2021
projects those rates generationally:

    q(x, y) = q(x, 2012) * product_{t=2012}^{y-1} (1 - MP(x, t))

Improvement during calendar year t is applied at the attained age x for which
q is being computed (the SOA scale is not walked along the cohort diagonal).
Years after 2036 use the published "2037+" ultimate column. Ages 20 and under
use the published "≤ 20" row.

Table choice in the valuation, documented in `cashflows.table_for_age`:
employee rates before retirement eligibility ages, retiree rates for retirees
and for ages 62 and older, contingent-survivor rates for beneficiaries and
spouses. Pri-2012 does not publish retiree or contingent rates below 50, and
employee rates stop at 80. Missing adult ages are filled from the other adult
table at the same sex; ages under 18 use the Pri-2012 juvenile rates. Age 120
is certain death, as in the published tables.

Sources, included for reproducibility:
- data/raw/pri-2012-mortality-tables-amount.xlsx
  https://www.soa.org/resources/experience-studies/2019/pri-2012-private-mortality-tables/
- data/raw/mp-2021-rates.xlsx
  https://www.soa.org/resources/experience-studies/2021/mortality-improvement-scale-mp-2021/

These tables are Society of Actuaries publications. They are bundled so the
study can be rerun without a download. They are not a mortality opinion for
any real plan.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import openpyxl

from pension.paths import RAW_DATA

SEXES = ("M", "F")
TABLES = ("employee", "retiree", "contingent")
SEX_INDEX = {"M": 0, "F": 1}
TABLE_INDEX = {"employee": 0, "retiree": 1, "contingent": 2}

_PRI_FILE = RAW_DATA / "pri-2012-mortality-tables-amount.xlsx"
_MP_FILE = RAW_DATA / "mp-2021-rates.xlsx"

# Total-dataset sheet columns (1-indexed), by sex and table.
_PRI_COLUMNS = {
    "F": {"employee": 4, "retiree": 5, "contingent": 6},
    "M": {"employee": 9, "retiree": 10, "contingent": 11},
}

_YEAR_MIN = 1990
_YEAR_MAX = 2250


@dataclass
class MortalityBasis:
    """Projected mortality rates on a fixed basis, looked up by sex, table, age, year."""

    qx_cube: np.ndarray  # [sex, table, age, year - year_min]
    year_min: int
    year_max: int
    description: str

    def qx(self, sex: str, table: str, age: int, year: int) -> float:
        age_i = int(age)
        if age_i >= 120:
            return 1.0
        if age_i < 0:
            age_i = 0
        year_i = min(max(int(year), self.year_min), self.year_max)
        value = float(
            self.qx_cube[SEX_INDEX[sex], TABLE_INDEX[table], age_i, year_i - self.year_min]
        )
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value

    @classmethod
    def constant_q(cls, q: float, description: str = "Constant q") -> "MortalityBasis":
        """Every age, sex, and table returns the same q, except age 120 which is 1."""
        if not 0 <= q < 1:
            raise ValueError("constant q must be in [0, 1)")
        cube = np.full((2, 3, 121, _YEAR_MAX - _YEAR_MIN + 1), float(q))
        cube[:, :, 120, :] = 1.0
        return cls(cube, _YEAR_MIN, _YEAR_MAX, description)


def _blank(value) -> bool:
    return value is None or value == ""


def _load_pri_base() -> dict[tuple[str, str], dict[int, float]]:
    workbook = openpyxl.load_workbook(_PRI_FILE, data_only=True, read_only=True)
    sheet = workbook["Total Dataset"]
    rates: dict[tuple[str, str], dict[int, float]] = {
        (sex, table): {} for sex in SEXES for table in TABLES
    }
    for row in sheet.iter_rows(min_row=6, max_row=108, max_col=12, values_only=True):
        age = row[1]
        if _blank(age):
            continue
        age_i = int(age)
        for sex, columns in _PRI_COLUMNS.items():
            for table, col in columns.items():
                value = row[col - 1]
                if not _blank(value):
                    rates[(sex, table)][age_i] = float(value)
    juvenile = workbook["Juvenile"]
    for row in juvenile.iter_rows(min_row=5, max_row=23, max_col=5, values_only=True):
        age = row[1]
        if _blank(age):
            continue
        age_i = int(age)
        female = row[3]
        male = row[4]
        if not _blank(female):
            rates[("F", "employee")].setdefault(age_i, float(female))
        if not _blank(male):
            rates[("M", "employee")].setdefault(age_i, float(male))
    workbook.close()
    return rates


def _fill_base_ages(rates: dict[tuple[str, str], dict[int, float]]) -> np.ndarray:
    """Return base q in 2012 with shape [sex, table, age]."""
    base = np.ones((2, 3, 121), dtype=float)
    for sex in SEXES:
        for table in TABLES:
            for age, q in rates[(sex, table)].items():
                if 0 <= age <= 120:
                    base[SEX_INDEX[sex], TABLE_INDEX[table], age] = q
        employee = rates[(sex, "employee")]
        retiree = rates[(sex, "retiree")]
        contingent = rates[(sex, "contingent")]
        for age in range(0, 121):
            if age not in retiree:
                donor = employee.get(age, contingent.get(age))
                if donor is not None:
                    base[SEX_INDEX[sex], TABLE_INDEX["retiree"], age] = donor
            if age not in contingent:
                donor = employee.get(age, retiree.get(age))
                if donor is not None:
                    base[SEX_INDEX[sex], TABLE_INDEX["contingent"], age] = donor
            if age not in employee:
                donor = retiree.get(age, contingent.get(age))
                if donor is not None:
                    base[SEX_INDEX[sex], TABLE_INDEX["employee"], age] = donor
    base[:, :, 120] = 1.0
    return base


def _load_mp() -> tuple[np.ndarray, np.ndarray]:
    """Return improvement rates [sex, age, year_index] and the year labels.

    The year axis runs 1951 through the projection horizon. 2037 and later
    repeat the published 2037+ column. Ages 0-20 repeat the published '≤ 20' row.
    """
    parsed: dict[str, dict[tuple[int, int], float]] = {"M": {}, "F": {}}
    ultimate: dict[str, dict[int, float]] = {"M": {}, "F": {}}
    young: dict[str, dict[int, float]] = {"M": {}, "F": {}}
    young_ultimate: dict[str, float] = {"M": 0.0, "F": 0.0}

    workbook = openpyxl.load_workbook(_MP_FILE, data_only=True, read_only=False)
    for sex, sheet_name in (("M", "Male"), ("F", "Female")):
        sheet = workbook[sheet_name]
        year_by_col: dict[int, object] = {}
        for col in range(2, sheet.max_column + 1):
            year = sheet.cell(2, col).value
            if year is not None:
                year_by_col[col] = year
        for row in range(3, sheet.max_row + 1):
            age_label = sheet.cell(row, 1).value
            if age_label is None:
                continue
            young_row = not isinstance(age_label, (int, float))
            age = 20 if young_row else int(age_label)
            for col, year in year_by_col.items():
                value = sheet.cell(row, col).value
                if value is None:
                    continue
                rate = float(value)
                if year == "2037+":
                    if young_row:
                        young_ultimate[sex] = rate
                    else:
                        ultimate[sex][age] = rate
                elif isinstance(year, int):
                    if young_row:
                        young[sex][year] = rate
                    else:
                        parsed[sex][(age, year)] = rate
    workbook.close()

    years = np.arange(1951, _YEAR_MAX + 1)
    cube = np.zeros((2, 121, len(years)), dtype=float)
    year_index = {int(year): i for i, year in enumerate(years)}
    for sex in SEXES:
        s = SEX_INDEX[sex]
        for (age, year), rate in parsed[sex].items():
            if year in year_index and 0 <= age <= 120:
                cube[s, age, year_index[year]] = rate
        for year, rate in young[sex].items():
            if year in year_index:
                cube[s, 0:21, year_index[year]] = rate
        # Extend the ultimate column from 2037 forward, and fill any gap year.
        for age in range(21, 121):
            ult = ultimate[sex].get(age, 0.0)
            for year in range(2037, int(years[-1]) + 1):
                cube[s, age, year_index[year]] = ult
        for year in range(2037, int(years[-1]) + 1):
            cube[s, 0:21, year_index[year]] = young_ultimate[sex]
    return cube, years


_PUBLISHED_CACHE: dict[str, object] = {}


def _published_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load and cache the Pri-2012 base q and the MP-2021 scale."""
    if "base" not in _PUBLISHED_CACHE:
        _PUBLISHED_CACHE["base"] = _fill_base_ages(_load_pri_base())
        improvement, years = _load_mp()
        _PUBLISHED_CACHE["improvement"] = improvement
        _PUBLISHED_CACHE["years"] = years
    return (
        _PUBLISHED_CACHE["base"],  # type: ignore[return-value]
        _PUBLISHED_CACHE["improvement"],  # type: ignore[return-value]
        _PUBLISHED_CACHE["years"],  # type: ignore[return-value]
    )


def build_mortality(
    *,
    extra_improvement: float = 0.0,
    extra_improvement_from_year: int = 2026,
    static_from_year: int | None = None,
    qx_multiplier: float = 1.0,
) -> MortalityBasis:
    """Project Pri-2012 with MP-2021.

    `extra_improvement` is added to scale rates in calendar years on and after
    `extra_improvement_from_year` (a longevity stress, not a rewrite of history).

    `static_from_year`, if set, freezes each age's q at that calendar year's
    projected rate for every later year. Improvement from 2012 up to that year
    is kept. This is the "no future improvement" case when the freeze year is
    the first year of exposure.
    """
    if qx_multiplier < 0:
        raise ValueError("qx multiplier cannot be negative")
    base, improvement, years = _published_arrays()
    year_index = {int(year): i for i, year in enumerate(years)}
    n_years = _YEAR_MAX - _YEAR_MIN + 1
    cube = np.zeros((2, 3, 121, n_years), dtype=float)

    for sex_i in range(2):
        for age in range(121):
            # Log of the product of (1 - MP) from 2012 through the prior year.
            running = 0.0
            for year in range(_YEAR_MIN, _YEAR_MAX + 1):
                factor = 1.0 if year <= 2012 else float(np.exp(running))
                for table_i in range(3):
                    q = base[sex_i, table_i, age] * factor * qx_multiplier
                    cube[sex_i, table_i, age, year - _YEAR_MIN] = min(max(q, 0.0), 1.0)
                # Improvement during `year` reduces next year's q. The product
                # that defines Pri-2012 generational projection starts in 2012.
                if year >= 2012 and age < 120 and year in year_index:
                    raw = float(improvement[sex_i, age, year_index[year]])
                    if extra_improvement and year >= extra_improvement_from_year:
                        raw += extra_improvement
                    raw = min(raw, 0.20)
                    running += float(np.log(1.0 - raw))

    if static_from_year is not None:
        freeze = min(max(static_from_year, _YEAR_MIN), _YEAR_MAX)
        freeze_col = freeze - _YEAR_MIN
        for later in range(freeze_col + 1, n_years):
            cube[:, :, :, later] = cube[:, :, :, freeze_col]
    cube[:, :, 120, :] = 1.0

    pieces = ["Pri-2012 amount-weighted total dataset, generational MP-2021"]
    if extra_improvement:
        pieces.append(
            f"plus {extra_improvement:.3%} improvement from {extra_improvement_from_year}"
        )
    if static_from_year is not None:
        pieces.append(f"qx frozen from {static_from_year}")
    if qx_multiplier != 1:
        pieces.append(f"qx times {qx_multiplier:.2f}")
    return MortalityBasis(cube, _YEAR_MIN, _YEAR_MAX, "; ".join(pieces))


def load_published_mortality() -> MortalityBasis:
    """Accounting basis: unmodified Pri-2012 total dataset with MP-2021."""
    return build_mortality()
