"""Seeded synthetic defined-benefit census.

The population is a fictional hourly-and-salaried plan, Northwind Components.
It is not a Group 1001, American National, or client census. Draws come from
`numpy.random.Generator` seeded with `Assumptions.seed`. Do not reorder the
draws: the seed contract is the sequence in this module.

After a clean population is drawn, `_inject_known_defects` plants a short list
of bad records so the validation step has something real to catch. Those
defects are intentional and documented in `PLANTED_DEFECTS`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pension.assumptions import Assumptions

PLANTED_DEFECTS = (
    "A-0001 missing date of birth",
    "A-0002 sex code blank",
    "A-0003 negative accrued benefit",
    "A-0004 credited service greater than age minus 16",
    "A-0005 zero compensation",
    "A-0007 accrued benefit 1.5 times the plan formula (kept; soft flag)",
    "A-0008 compensation above the 2025 401(a)(17) limit (kept; soft flag)",
    "A-0009 hire date after the measurement date",
    "R-0002 duplicate of participant id R-0001",
    "R-0003 zero benefit",
    "R-0004 joint-and-survivor form with no spouse date of birth",
    "R-0005 retiree age 30",
    "R-0006 sex code X",
    "R-0007 annual benefit of $400 (kept; de minimis soft flag)",
    "R-0008 spouse 45 years younger (kept; soft flag)",
    "R-0009 retiree age 52 (kept; soft flag)",
    "D-0001 negative service",
    "D-0002 annual benefit of $750,000",
    "D-0003 missing final average pay",
    "D-0004 termination date before hire date",
    "B-0001 sex code blank",
)

COLUMNS = [
    "participant_id",
    "status",
    "sex",
    "date_of_birth",
    "age",
    "hire_date",
    "termination_date",
    "retirement_date",
    "service_years",
    "compensation",
    "final_average_pay",
    "annual_benefit",
    "payment_form",
    "continuation_pct",
    "certain_months_remaining",
    "married",
    "spouse_sex",
    "spouse_date_of_birth",
    "spouse_age",
]


def generate_census(assumptions: Assumptions | None = None, seed: int | None = None) -> pd.DataFrame:
    """Return the raw tape, including planted defects."""
    assumptions = assumptions or Assumptions()
    rng = np.random.default_rng(assumptions.seed if seed is None else seed)
    parts = [
        _actives(rng, assumptions),
        _deferred(rng, assumptions),
        _retirees(rng, assumptions),
        _beneficiaries(rng, assumptions),
    ]
    census = pd.concat(parts, ignore_index=True)
    census = _inject_known_defects(census)
    census = _refresh_ages(census, assumptions)
    return census[COLUMNS]


def _dates(years: np.ndarray, rng: np.random.Generator) -> pd.Series:
    frame = pd.DataFrame(
        {
            "year": np.asarray(years, dtype=int),
            "month": rng.integers(1, 13, size=len(years)),
            "day": rng.integers(1, 28, size=len(years)),
        }
    )
    return pd.to_datetime(frame)


def _spouse_block(
    rng: np.random.Generator,
    ages: np.ndarray,
    sexes: np.ndarray,
    married: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, pd.Series]:
    """Opposite-sex spouse, male about three years older, gap clipped at 20."""
    n = len(ages)
    gap = np.clip(rng.normal(3.0, 2.0, size=n), -8.0, 15.0)
    spouse_age = np.where(sexes == "M", ages - gap, ages + gap)
    spouse_age = np.rint(spouse_age).astype(int)
    spouse_age = np.clip(spouse_age, ages - 20, ages + 20)
    spouse_age = np.clip(spouse_age, 22, 100)
    spouse_sex = np.where(sexes == "M", "F", "M")
    spouse_year = 2025 - spouse_age
    spouse_dob = _dates(spouse_year, rng)
    spouse_age = spouse_age.astype(float)
    spouse_sex = spouse_sex.astype(object)
    spouse_age = np.where(married, spouse_age, np.nan)
    spouse_sex = np.where(married, spouse_sex, None)
    spouse_dob = spouse_dob.where(married, pd.NaT)
    return spouse_sex, spouse_age, spouse_dob


def _actives(rng: np.random.Generator, assumptions: Assumptions) -> pd.DataFrame:
    n = assumptions.n_active
    ages = np.clip(np.rint(28 + rng.beta(2.5, 2.2, size=n) * 36).astype(int), 28, 64)
    sexes = np.where(rng.random(n) < 0.64, "M", "F")
    hire_age = rng.integers(22, 35, size=n)
    service = np.clip(ages - hire_age, 1, 40).astype(float)
    service = np.minimum(service, (ages - 20).astype(float))
    service = np.maximum(service, 1.0)
    median = 76_000.0 * np.power(1.008, ages - 45)
    salary = np.clip(rng.lognormal(np.log(median), 0.27, size=n), 45_000.0, 230_000.0)
    salary = np.round(salary, 2)
    fap = np.round(salary * rng.uniform(0.93, 0.99, size=n), 2)
    benefit = np.round(assumptions.accrual_rate * fap * service, 2)
    married = rng.random(n) < np.where(sexes == "M", 0.78, 0.58)
    spouse_sex, spouse_age, spouse_dob = _spouse_block(rng, ages, sexes, married)
    hire_year = (2025 - service).astype(int)
    return pd.DataFrame(
        {
            "participant_id": [f"A-{i:04d}" for i in range(1, n + 1)],
            "status": "active",
            "sex": sexes,
            "date_of_birth": _dates(2025 - ages, rng),
            "age": ages,
            "hire_date": _dates(hire_year, rng),
            "termination_date": pd.NaT,
            "retirement_date": pd.NaT,
            "service_years": service,
            "compensation": salary,
            "final_average_pay": fap,
            "annual_benefit": benefit,
            "payment_form": "SLA",
            "continuation_pct": 0.0,
            "certain_months_remaining": 0,
            "married": married,
            "spouse_sex": spouse_sex,
            "spouse_date_of_birth": spouse_dob,
            "spouse_age": spouse_age,
        }
    )


def _deferred(rng: np.random.Generator, assumptions: Assumptions) -> pd.DataFrame:
    n = assumptions.n_deferred
    ages = np.clip(np.rint(42 + rng.beta(2.1, 2.0, size=n) * 22).astype(int), 42, 64)
    sexes = np.where(rng.random(n) < 0.58, "M", "F")
    high = np.maximum(ages - 24, 8).astype(float)
    low = np.minimum(np.full(n, 6.0), high - 1.0)
    service = np.round(np.clip(rng.uniform(low, high), 5.0, 32.0), 1)
    median = 62_000.0 * np.power(1.006, ages - 50)
    fap = np.clip(rng.lognormal(np.log(median), 0.30, size=n), 32_000.0, 160_000.0)
    fap = np.round(fap, 2)
    benefit = np.round(assumptions.accrual_rate * fap * service, 2)
    married = rng.random(n) < np.where(sexes == "M", 0.70, 0.52)
    spouse_sex, spouse_age, spouse_dob = _spouse_block(rng, ages, sexes, married)
    term_year = rng.integers(2009, 2025, size=n)
    hire_year = term_year - np.maximum(np.rint(service).astype(int), 1)
    return pd.DataFrame(
        {
            "participant_id": [f"D-{i:04d}" for i in range(1, n + 1)],
            "status": "deferred_vested",
            "sex": sexes,
            "date_of_birth": _dates(2025 - ages, rng),
            "age": ages,
            "hire_date": _dates(hire_year, rng),
            "termination_date": _dates(term_year, rng),
            "retirement_date": pd.NaT,
            "service_years": service,
            "compensation": np.nan,
            "final_average_pay": fap,
            "annual_benefit": benefit,
            "payment_form": "SLA",
            "continuation_pct": 0.0,
            "certain_months_remaining": 0,
            "married": married,
            "spouse_sex": spouse_sex,
            "spouse_date_of_birth": spouse_dob,
            "spouse_age": spouse_age,
        }
    )


def _retirees(rng: np.random.Generator, assumptions: Assumptions) -> pd.DataFrame:
    n = assumptions.n_retiree
    ages = np.clip(np.rint(62 + rng.beta(2.0, 2.4, size=n) * 32).astype(int), 62, 94)
    sexes = np.where(rng.random(n) < 0.72, "M", "F")
    years_retired = rng.integers(0, 18, size=n)
    years_retired = np.minimum(years_retired, np.maximum(ages - 62, 0))
    benefit = np.round(
        np.clip(rng.lognormal(np.log(16_800.0), 0.42, size=n), 3_600.0, 90_000.0),
        2,
    )
    forms = rng.choice(["SLA", "JS50", "JS100", "C10"], size=n, p=[0.42, 0.33, 0.18, 0.07])
    continuation = np.where(forms == "JS50", 0.5, np.where(forms == "JS100", 1.0, 0.0))
    certain = np.where(forms == "C10", np.maximum(0, 10 - years_retired) * 12, 0).astype(int)
    joint = np.isin(forms, ["JS50", "JS100"])
    spouse_sex, spouse_age, spouse_dob = _spouse_block(rng, ages, sexes, joint)
    retirement_year = 2025 - years_retired
    return pd.DataFrame(
        {
            "participant_id": [f"R-{i:04d}" for i in range(1, n + 1)],
            "status": "retiree",
            "sex": sexes,
            "date_of_birth": _dates(2025 - ages, rng),
            "age": ages,
            "hire_date": pd.NaT,
            "termination_date": pd.NaT,
            "retirement_date": _dates(retirement_year, rng),
            "service_years": np.nan,
            "compensation": np.nan,
            "final_average_pay": np.nan,
            "annual_benefit": benefit,
            "payment_form": forms,
            "continuation_pct": continuation,
            "certain_months_remaining": certain,
            "married": joint,
            "spouse_sex": spouse_sex,
            "spouse_date_of_birth": spouse_dob,
            "spouse_age": spouse_age,
        }
    )


def _beneficiaries(rng: np.random.Generator, assumptions: Assumptions) -> pd.DataFrame:
    n = assumptions.n_beneficiary
    ages = np.clip(np.rint(66 + rng.beta(2.0, 2.2, size=n) * 30).astype(int), 66, 96)
    sexes = np.where(rng.random(n) < 0.14, "M", "F")
    benefit = np.round(
        np.clip(rng.lognormal(np.log(9_200.0), 0.40, size=n), 2_400.0, 48_000.0),
        2,
    )
    return pd.DataFrame(
        {
            "participant_id": [f"B-{i:04d}" for i in range(1, n + 1)],
            "status": "beneficiary",
            "sex": sexes,
            "date_of_birth": _dates(2025 - ages, rng),
            "age": ages,
            "hire_date": pd.NaT,
            "termination_date": pd.NaT,
            "retirement_date": pd.NaT,
            "service_years": np.nan,
            "compensation": np.nan,
            "final_average_pay": np.nan,
            "annual_benefit": benefit,
            "payment_form": "SLA",
            "continuation_pct": 0.0,
            "certain_months_remaining": 0,
            "married": False,
            "spouse_sex": None,
            "spouse_date_of_birth": pd.NaT,
            "spouse_age": np.nan,
        }
    )


def _set(df: pd.DataFrame, record_id: str, **values) -> None:
    match = df.index[df["participant_id"] == record_id]
    if len(match) != 1:
        raise KeyError(record_id)
    for key, value in values.items():
        df.at[match[0], key] = value


def _inject_known_defects(df: pd.DataFrame) -> pd.DataFrame:
    """Plant the defects listed in PLANTED_DEFECTS. Ids refer to the clean draw."""
    df = df.copy()
    _set(df, "A-0001", date_of_birth=pd.NaT)
    _set(df, "A-0002", sex="")
    _set(df, "A-0003", annual_benefit=-500.0)
    row = df.index[df["participant_id"] == "A-0004"][0]
    df.at[row, "service_years"] = float(df.at[row, "age"])
    _set(df, "A-0005", compensation=0.0)
    row = df.index[df["participant_id"] == "A-0007"][0]
    df.at[row, "annual_benefit"] = round(float(df.at[row, "annual_benefit"]) * 1.5, 2)
    _set(df, "A-0008", compensation=410_000.0)
    _set(df, "A-0009", hire_date=pd.Timestamp("2026-03-01"))
    _set(df, "R-0002", participant_id="R-0001")
    _set(df, "R-0003", annual_benefit=0.0)
    _set(
        df,
        "R-0004",
        payment_form="JS100",
        continuation_pct=1.0,
        married=True,
        spouse_sex=None,
        spouse_date_of_birth=pd.NaT,
        spouse_age=np.nan,
    )
    _set(df, "R-0005", date_of_birth=pd.Timestamp("1995-06-15"))
    _set(df, "R-0006", sex="X")
    _set(df, "R-0007", annual_benefit=400.0)
    row = df.index[df["participant_id"] == "R-0008"][0]
    birth_year = int(pd.Timestamp(df.at[row, "date_of_birth"]).year)
    spouse_sex = "F" if df.at[row, "sex"] == "M" else "M"
    _set(
        df,
        "R-0008",
        payment_form="JS50",
        continuation_pct=0.5,
        married=True,
        spouse_sex=spouse_sex,
        spouse_date_of_birth=pd.Timestamp(year=birth_year + 45, month=6, day=15),
    )
    # Age 52 is an early retiree worth a look, but the spouse age should still
    # be plausible. Only R-0008 carries the planted age-gap defect.
    row = df.index[df["participant_id"] == "R-0009"][0]
    _set(df, "R-0009", date_of_birth=pd.Timestamp("1973-04-01"))
    if pd.notna(df.at[row, "spouse_date_of_birth"]):
        _set(df, "R-0009", spouse_date_of_birth=pd.Timestamp("1976-04-01"))
    _set(df, "D-0001", service_years=-1.0)
    _set(df, "D-0002", annual_benefit=750_000.0)
    _set(df, "D-0003", final_average_pay=np.nan)
    _set(
        df,
        "D-0004",
        hire_date=pd.Timestamp("2012-06-01"),
        termination_date=pd.Timestamp("2004-06-01"),
    )
    _set(df, "B-0001", sex="")
    return df


def _refresh_ages(df: pd.DataFrame, assumptions: Assumptions) -> pd.DataFrame:
    """Recompute integer ages from dates. December 31 makes this a year difference."""
    df = df.copy()
    valuation_year = assumptions.measurement_date.year
    dob = pd.to_datetime(df["date_of_birth"], errors="coerce")
    df["age"] = valuation_year - dob.dt.year
    spouse = pd.to_datetime(df["spouse_date_of_birth"], errors="coerce")
    df["spouse_age"] = valuation_year - spouse.dt.year
    return df
