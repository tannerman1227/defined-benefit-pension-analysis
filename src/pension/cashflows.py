"""Seriatim expected benefit cash flows.

Payments are monthly. The December payment has already been made on the
measurement date, so the first modeled payment is one month later
(an annuity-immediate). Survival to a fractional age uses the uniform
distribution of deaths within the year of age. Mortality during calendar
year y at attained age x is q(x, y) from the mortality basis.

Benefit forms
- Retiree single life: pay while the member is alive.
- Retiree joint and survivor: full benefit while the member is alive, and the
  continuation percentage while only the spouse is alive. Lives are independent.
- Retiree 10-year certain and life: remaining certain payments are paid
  whether or not the member is alive, then a single life annuity.
- Beneficiary: single life on the beneficiary, using contingent-survivor
  mortality (employee mortality below age 50, where Pri-2012 does not
  publish a contingent rate).
- Active and deferred vested: a life annuity starting at the assumed
  commencement age, paid only if the member survives. Married participants
  also have a 50% qualified preretirement survivor annuity starting at that
  same commencement age if the member dies before it. Surviving to
  commencement and then dying does not create a spouse benefit: the normal
  form is a single life annuity. Spouses use contingent-survivor mortality.

The fraction returned for each month is the expected portion of one monthly
payment of (annual benefit / 12). ABO and PBO use the same fraction and
different annual amounts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pension.assumptions import Assumptions
from pension.benefits import valued_annual_benefits
from pension.discount import DiscountCurve
from pension.mortality import MortalityBasis

GLOBAL_MONTHS = 121 * 12
STATUSES = ("active", "deferred_vested", "retiree", "beneficiary")


def table_for_member(status: str, attained_age: int) -> str:
    """Pri-2012 table for the participant's own life at an attained age."""
    if status == "beneficiary":
        return "contingent" if attained_age >= 50 else "employee"
    if status == "retiree":
        return "retiree" if attained_age >= 50 else "employee"
    if attained_age >= 62:
        return "retiree"
    return "employee"


def table_for_spouse(attained_age: int) -> str:
    return "contingent" if attained_age >= 50 else "employee"


def annual_qx(mortality: MortalityBasis, sex: str, age: int, year0: int, n_years: int, table_at) -> np.ndarray:
    """One-year mortality rates for each year of age from `age` forward."""
    q = np.ones(n_years, dtype=float)
    usable = min(n_years, max(0, 121 - int(age)))
    for year_index in range(usable):
        attained = int(age) + year_index
        if attained >= 120:
            q[year_index] = 1.0
        else:
            q[year_index] = mortality.qx(sex, table_at(attained), attained, year0 + year_index)
    return q


def survival_at_months(q_annual: np.ndarray, month_counts: np.ndarray) -> np.ndarray:
    """Survival to each integer month-count under UDD.

    Month-count 0 is the measurement age. Month-count 12 is one year later.
    """
    counts = np.asarray(month_counts, dtype=np.int64)
    survival_to_year = np.empty(len(q_annual) + 1, dtype=float)
    survival_to_year[0] = 1.0
    survival_to_year[1:] = np.cumprod(np.clip(1.0 - q_annual, 0.0, 1.0))
    year = counts // 12
    fraction = (counts % 12) / 12.0
    out = np.zeros(len(counts), dtype=float)
    n_years = len(q_annual)
    inside = (year >= 0) & (year < n_years)
    if np.any(inside):
        y = year[inside]
        out[inside] = survival_to_year[y] * (1.0 - fraction[inside] * q_annual[y])
    at_horizon = (year == n_years) & ((counts % 12) == 0)
    if np.any(at_horizon):
        out[at_horizon] = survival_to_year[n_years]
    return np.clip(out, 0.0, 1.0)


@dataclass
class CashFlowBook:
    """Aggregate expected monthly cash flows aligned to `times` in years."""

    times: np.ndarray
    benefit_abo: dict[str, np.ndarray]
    benefit_pbo: dict[str, np.ndarray]
    inforce: dict[str, np.ndarray]
    participants: pd.DataFrame
    mortality: str

    def benefit(self, basis: str, statuses: tuple[str, ...] | None = None) -> np.ndarray:
        store = self.benefit_pbo if basis == "pbo" else self.benefit_abo
        chosen = STATUSES if statuses is None else statuses
        total = np.zeros_like(self.times)
        for status in chosen:
            total = total + store[status]
        return total

    def contracts(self, statuses: tuple[str, ...] | None = None) -> np.ndarray:
        chosen = STATUSES if statuses is None else statuses
        total = np.zeros_like(self.times)
        for status in chosen:
            total = total + self.inforce[status]
        return total


def life_annuity_factor(
    mortality: MortalityBasis,
    sex: str,
    age: int,
    start_year: int,
    curve: DiscountCurve,
    *,
    due: bool = True,
    defer_to_age: int | None = None,
    max_years: int | None = None,
    table_at=None,
) -> float:
    """Monthly life annuity of 1 per year.

    `due=True` pays at the start of each month, including a payment at once.
    `due=False` pays at the end of each month. `defer_to_age` suppresses
    payments before that exact age. `max_years` truncates the annuity.
    """
    if table_at is None:
        table_at = lambda attained: "employee" if attained < 62 else "retiree"
    n_years = 121 - int(age)
    if max_years is not None:
        n_years = min(n_years, int(max_years))
    if n_years <= 0:
        return 0.0
    q = annual_qx(mortality, sex, age, start_year, n_years, table_at)
    if due:
        month_counts = np.arange(0, n_years * 12, dtype=np.int64)
    else:
        month_counts = np.arange(1, n_years * 12 + 1, dtype=np.int64)
    survival = survival_at_months(q, month_counts)
    if defer_to_age is not None and defer_to_age > age:
        survival = np.where(month_counts >= (defer_to_age - age) * 12, survival, 0.0)
    discount = curve.discount_factor(month_counts / 12.0)
    return float(np.sum(survival * discount / 12.0))


def _horizon_years(age: int, spouse_age: int | None, certain_months: int, defer_months: int) -> int:
    member_years = max(1, 121 - age)
    spouse_years = max(1, 121 - spouse_age) if spouse_age is not None else 1
    certain_years = int(np.ceil(certain_months / 12.0)) + 1 if certain_months else 1
    defer_years = defer_months // 12 + 1
    return min(GLOBAL_MONTHS // 12, max(member_years, spouse_years, certain_years, defer_years))


def _expected_fraction(
    status: str,
    form: str,
    continuation: float,
    certain_months: int,
    defer_months: int,
    married: bool,
    qpsa: float,
    month_counts: np.ndarray,
    member_q: np.ndarray,
    member_survival: np.ndarray,
    spouse_survival: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Expected fraction of the monthly benefit, and probability the contract is in force."""
    if status == "beneficiary" or (status == "retiree" and form == "SLA"):
        return member_survival.copy(), member_survival.copy()

    if status == "retiree" and form in {"JS50", "JS100"}:
        if spouse_survival is None:
            raise ValueError("Joint-and-survivor record has no spouse survival")
        fraction = member_survival + (1.0 - member_survival) * spouse_survival * continuation
        inforce = 1.0 - (1.0 - member_survival) * (1.0 - spouse_survival)
        return fraction, inforce

    if status == "retiree" and form == "C10":
        guaranteed = month_counts <= certain_months
        fraction = np.where(guaranteed, 1.0, member_survival)
        inforce = np.where(guaranteed, 1.0, member_survival)
        return fraction.astype(float), inforce.astype(float)

    if status in {"active", "deferred_vested"}:
        started = np.ones(len(month_counts), dtype=bool) if defer_months <= 0 else month_counts >= defer_months
        fraction = np.where(started, member_survival, 0.0)
        if married and defer_months > 0 and spouse_survival is not None:
            alive_at_commencement = float(survival_at_months(member_q, np.array([defer_months]))[0])
            survivor = np.where(
                started,
                (1.0 - alive_at_commencement) * spouse_survival * qpsa,
                0.0,
            )
            fraction = fraction + survivor
            inforce = 1.0 - (1.0 - member_survival) * (1.0 - spouse_survival)
        else:
            inforce = member_survival
        return fraction.astype(float), inforce.astype(float)

    raise ValueError(f"Unsupported status/form: {status} / {form}")


def project_census(
    census: pd.DataFrame,
    assumptions: Assumptions,
    mortality: MortalityBasis,
    curve: DiscountCurve | None = None,
) -> CashFlowBook:
    """Project every clean record and aggregate expected payments by status."""
    times = np.arange(1, GLOBAL_MONTHS + 1, dtype=float) / 12.0
    benefit_abo = {status: np.zeros(GLOBAL_MONTHS) for status in STATUSES}
    benefit_pbo = {status: np.zeros(GLOBAL_MONTHS) for status in STATUSES}
    inforce = {status: np.zeros(GLOBAL_MONTHS) for status in STATUSES}
    discount = None if curve is None else curve.discount_factor(times)
    rows: list[dict] = []

    for record in census.itertuples(index=False):
        status = record.status
        if status not in STATUSES:
            raise ValueError(f"{record.participant_id} has status {status}")
        age = int(record.age)
        sex = record.sex
        form = record.payment_form
        benefit = float(record.annual_benefit)
        service = None if pd.isna(record.service_years) else float(record.service_years)
        abo_annual, pbo_annual, retire_at = valued_annual_benefits(
            age=age,
            service=service,
            status=status,
            tape_annual_benefit=benefit,
            assumptions=assumptions,
        )
        defer_months = 0 if status in {"retiree", "beneficiary"} else (retire_at - age) * 12
        spouse_age = None if pd.isna(record.spouse_age) else int(record.spouse_age)
        spouse_sex = record.spouse_sex if record.spouse_sex in {"M", "F"} else None
        has_spouse = spouse_age is not None and spouse_sex is not None
        if form in {"JS50", "JS100"} and not has_spouse:
            raise ValueError(f"{record.participant_id} is {form} without a spouse")
        certain = int(record.certain_months_remaining or 0)
        married = bool(record.married) and has_spouse and status in {"active", "deferred_vested"}
        n_years = _horizon_years(age, spouse_age, certain, defer_months)
        month_counts = np.arange(1, n_years * 12 + 1, dtype=np.int64)
        member_q = annual_qx(
            mortality,
            sex,
            age,
            assumptions.first_exposure_year,
            n_years,
            lambda attained, status=status: table_for_member(status, attained),
        )
        member_survival = survival_at_months(member_q, month_counts)
        spouse_survival = None
        if has_spouse:
            spouse_q = annual_qx(
                mortality,
                spouse_sex,
                spouse_age,
                assumptions.first_exposure_year,
                n_years,
                table_for_spouse,
            )
            spouse_survival = survival_at_months(spouse_q, month_counts)
        fraction, alive = _expected_fraction(
            status=status,
            form=form,
            continuation=float(record.continuation_pct or 0.0),
            certain_months=certain,
            defer_months=defer_months,
            married=married,
            qpsa=assumptions.qpsa_continuation,
            month_counts=month_counts,
            member_q=member_q,
            member_survival=member_survival,
            spouse_survival=spouse_survival,
        )
        fraction = np.clip(fraction, 0.0, 1.0)
        alive = np.clip(alive, 0.0, 1.0)
        length = len(month_counts)
        abo_cash = fraction * (abo_annual / 12.0)
        pbo_cash = fraction * (pbo_annual / 12.0)
        benefit_abo[status][:length] += abo_cash
        benefit_pbo[status][:length] += pbo_cash
        inforce[status][:length] += alive
        row = {
            "participant_id": record.participant_id,
            "status": status,
            "sex": sex,
            "age": age,
            "commencement_age": retire_at,
            "abo_annual_benefit": abo_annual,
            "pbo_annual_benefit": pbo_annual,
        }
        if discount is not None:
            row["abo"] = float(abo_cash @ discount[:length])
            row["pbo"] = float(pbo_cash @ discount[:length])
        rows.append(row)

    return CashFlowBook(
        times=times,
        benefit_abo=benefit_abo,
        benefit_pbo=benefit_pbo,
        inforce=inforce,
        participants=pd.DataFrame(rows),
        mortality=mortality.description,
    )


def annual_cash_flows(book: CashFlowBook, curve: DiscountCurve, first_year: int) -> pd.DataFrame:
    """Collapse monthly expected payments to calendar years."""
    year_index = (np.arange(1, len(book.times) + 1) - 1) // 12
    years = first_year + year_index
    discount = curve.discount_factor(book.times)
    frames = []
    for status in STATUSES:
        abo = book.benefit_abo[status]
        pbo = book.benefit_pbo[status]
        frame = pd.DataFrame(
            {
                "calendar_year": years,
                "status": status,
                "expected_benefit_abo": abo,
                "expected_benefit_pbo": pbo,
                "pbo_present_value": pbo * discount,
            }
        )
        grouped = frame.groupby(["calendar_year", "status"], as_index=False).sum()
        frames.append(grouped)
    return pd.concat(frames, ignore_index=True)
