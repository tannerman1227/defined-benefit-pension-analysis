"""Buyout premium identity, and the shape of a lift-out versus a termination."""

import numpy as np
import pandas as pd
import pytest

from pension.assumptions import Assumptions
from pension.cashflows import STATUSES, CashFlowBook, project_census
from pension.discount import DiscountCurve
from pension.mortality import build_mortality
from pension.prt import indication


def _book(benefit_by_status, inforce_by_status, lives):
    times = np.array([1.0, 2.0])
    benefit_abo = {}
    benefit_pbo = {}
    inforce = {}
    for status in STATUSES:
        benefit_abo[status] = np.array(benefit_by_status.get(status, [0.0, 0.0]), dtype=float)
        benefit_pbo[status] = benefit_abo[status].copy()
        inforce[status] = np.array(inforce_by_status.get(status, [0.0, 0.0]), dtype=float)
    participants = pd.DataFrame({"status": lives})
    return CashFlowBook(times, benefit_abo, benefit_pbo, inforce, participants, "test")


def test_premium_grosses_up_benefits_and_expenses():
    assumptions = Assumptions(expense_per_life_per_year=120.0, premium_load=0.20)
    book = _book({"retiree": [1_000.0, 1_000.0]}, {"retiree": [1.0, 1.0]}, ["retiree"])
    curve = DiscountCurve.flat_annual_effective(0.0)
    price = indication(book, curve, assumptions, basis="pbo", statuses=("retiree",))
    # Two annual payments of 1,000 and two years of one life at $120, undiscounted.
    assert price["pv_benefits"] == pytest.approx(2_000.0)
    assert price["pv_expenses"] == pytest.approx(20.0)
    assert price["premium"] == pytest.approx(2_020.0 / 0.80)
    assert price["lives"] == 1


def test_liftout_prices_only_in_pay_lives():
    assumptions = Assumptions(expense_per_life_per_year=0.0, premium_load=0.0)
    book = _book(
        {"retiree": [500.0, 500.0], "active": [800.0, 800.0]},
        {"retiree": [1.0, 1.0], "active": [1.0, 1.0]},
        ["retiree", "active"],
    )
    curve = DiscountCurve.flat_annual_effective(0.0)
    liftout = indication(book, curve, assumptions, basis="pbo", statuses=("retiree", "beneficiary"))
    whole = indication(book, curve, assumptions, basis="abo")
    assert liftout["pv_benefits"] == pytest.approx(1_000.0)
    assert whole["pv_benefits"] == pytest.approx(2_600.0)
    assert liftout["lives"] == 1
    assert whole["lives"] == 2


def test_married_qpsa_increases_the_active_liability():
    mortality = build_mortality()
    curve = DiscountCurve.flat_annual_effective(0.04)
    assumptions = Assumptions()

    def one(married, spouse_age, spouse_sex):
        frame = pd.DataFrame(
            [
                {
                    "participant_id": "A-1",
                    "status": "active",
                    "sex": "M",
                    "age": 45,
                    "service_years": 15.0,
                    "annual_benefit": 12_000.0,
                    "payment_form": "SLA",
                    "continuation_pct": 0.0,
                    "certain_months_remaining": 0,
                    "married": married,
                    "spouse_sex": spouse_sex,
                    "spouse_age": spouse_age,
                }
            ]
        )
        book = project_census(frame, assumptions, mortality, curve)
        return float(book.participants.loc[0, "pbo"])

    single = one(False, np.nan, None)
    married = one(True, 42, "F")
    assert married > single
    assert single > 0
