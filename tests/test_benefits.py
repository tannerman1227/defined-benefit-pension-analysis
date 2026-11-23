"""Retirement age, early-retirement reduction, and projected unit credit."""

import pytest

from pension.assumptions import Assumptions
from pension.benefits import commencement_age, early_retirement_factor, valued_annual_benefits


def test_thirty_and_out_pulls_commencement_forward_to_62():
    assumptions = Assumptions()
    assert commencement_age(50, 20, "active", assumptions) == 62
    assert commencement_age(50, 5, "active", assumptions) == 65
    assert commencement_age(63, 31, "active", assumptions) == 63


def test_early_reduction_is_five_percent_simple_per_year():
    assumptions = Assumptions()
    assert early_retirement_factor(62, 10, assumptions) == pytest.approx(0.85)
    assert early_retirement_factor(62, 30, assumptions) == pytest.approx(1.0)
    assert early_retirement_factor(65, 10, assumptions) == pytest.approx(1.0)


def test_pbo_grows_pay_and_unlocks_the_unreduced_subsidy():
    assumptions = Assumptions()
    tape = 18_000.0
    abo, pbo, retire_at = valued_annual_benefits(
        age=50,
        service=20,
        status="active",
        tape_annual_benefit=tape,
        assumptions=assumptions,
    )
    assert retire_at == 62
    assert abo == pytest.approx(tape * 0.85)
    assert pbo == pytest.approx(tape * (1.035**12))
    assert pbo > abo


def test_pbo_without_the_subsidy_is_salary_scale_only():
    assumptions = Assumptions()
    tape = 10_000.0
    abo, pbo, retire_at = valued_annual_benefits(
        age=50,
        service=5,
        status="active",
        tape_annual_benefit=tape,
        assumptions=assumptions,
    )
    assert retire_at == 65
    assert abo == pytest.approx(tape)
    assert pbo == pytest.approx(tape * (1.035**15))


def test_deferred_vested_with_thirty_years_is_frozen_and_unreduced():
    assumptions = Assumptions()
    abo, pbo, retire_at = valued_annual_benefits(
        age=60,
        service=30,
        status="deferred_vested",
        tape_annual_benefit=8_000.0,
        assumptions=assumptions,
    )
    assert retire_at == 62
    assert abo == pytest.approx(8_000.0)
    assert pbo == pytest.approx(abo)


def test_in_pay_benefit_is_not_projected():
    assumptions = Assumptions()
    abo, pbo, retire_at = valued_annual_benefits(
        age=72,
        service=None,
        status="retiree",
        tape_annual_benefit=15_500.0,
        assumptions=assumptions,
    )
    assert retire_at == 72
    assert abo == pbo == pytest.approx(15_500.0)
