"""Annuity factors, including the SOA's published MP-2021 Table 1.1 values.

Table 1.1 in the October 2021 MP-2021 report gives monthly deferred-to-62
annuity-due factors at 4% as of January 1, 2021, on Pri-2012 total-dataset
rates with generational MP-2021. Employee rates apply below 62 and retiree
rates at 62 and older.
"""

import numpy as np
import pandas as pd
import pytest

from pension.assumptions import Assumptions
from pension.cashflows import life_annuity_factor, project_census
from pension.discount import DiscountCurve
from pension.mortality import MortalityBasis, build_mortality

# Published monthly deferred-to-62 annuity-due values at 4.0%, January 1, 2021.
PUBLISHED = {
    "F": {
        25: 3.7396,
        35: 5.4447,
        45: 7.9383,
        55: 11.6099,
        65: 14.2572,
        75: 10.2580,
        85: 6.1979,
        95: 3.3605,
    },
    "M": {
        25: 3.5054,
        35: 5.1011,
        45: 7.4405,
        55: 10.8960,
        65: 13.3798,
        75: 9.4558,
        85: 5.4867,
        95: 2.8883,
    },
}


@pytest.fixture(scope="module")
def mortality():
    return build_mortality()


def test_ten_year_certain_annuity_at_zero_interest():
    factor = life_annuity_factor(
        MortalityBasis.constant_q(0.0),
        "F",
        65,
        2026,
        DiscountCurve.flat_annual_effective(0.0),
        due=True,
        max_years=10,
    )
    assert factor == pytest.approx(10.0)


def test_ten_year_certain_annuity_at_four_percent():
    curve = DiscountCurve.flat_annual_effective(0.04)
    factor = life_annuity_factor(
        MortalityBasis.constant_q(0.0),
        "M",
        65,
        2026,
        curve,
        due=True,
        max_years=10,
    )
    monthly = 1.04 ** (-1.0 / 12.0)
    closed_form = (1.0 / 12.0) * (1.0 - monthly**120) / (1.0 - monthly)
    assert factor == pytest.approx(closed_form, rel=1e-12)


def test_udd_in_a_year_of_certain_death_at_zero_interest():
    """q = 1 at the attained age, so survival to month m is 1 - m/12."""
    basis = MortalityBasis.constant_q(0.0)
    basis.qx_cube[:, :, 65, :] = 1.0
    factor = life_annuity_factor(
        basis,
        "F",
        65,
        2026,
        DiscountCurve.flat_annual_effective(0.0),
        due=True,
        max_years=1,
    )
    expected = sum((1.0 / 12.0) * (1.0 - month / 12.0) for month in range(12))
    assert factor == pytest.approx(expected)


def test_soa_mp2021_table_1_1(mortality):
    curve = DiscountCurve.flat_annual_effective(0.04)
    for sex, factors in PUBLISHED.items():
        for age, published in factors.items():
            modeled = life_annuity_factor(
                mortality,
                sex,
                age,
                2021,
                curve,
                due=True,
                defer_to_age=62,
            )
            assert modeled == pytest.approx(published, rel=0.0012)


def test_seriatim_retiree_matches_the_annuity_factor(mortality):
    curve = DiscountCurve.flat_annual_effective(0.04)
    benefit = 12_000.0
    census = pd.DataFrame(
        [
            {
                "participant_id": "T-0001",
                "status": "retiree",
                "sex": "M",
                "age": 65,
                "service_years": np.nan,
                "annual_benefit": benefit,
                "payment_form": "SLA",
                "continuation_pct": 0.0,
                "certain_months_remaining": 0,
                "married": False,
                "spouse_sex": None,
                "spouse_age": np.nan,
            }
        ]
    )
    book = project_census(census, Assumptions(), mortality, curve)
    factor = life_annuity_factor(
        mortality,
        "M",
        65,
        2026,
        curve,
        due=False,
        table_at=lambda attained: "retiree" if attained >= 50 else "employee",
    )
    assert book.participants.loc[0, "pbo"] == pytest.approx(benefit * factor, rel=1e-10)
    assert book.participants.loc[0, "abo"] == pytest.approx(book.participants.loc[0, "pbo"])
