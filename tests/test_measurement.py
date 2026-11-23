"""The published measurement. These cents are the model output, not targets.

If a methodology change moves them, update the README from a fresh
`python -m pension` run rather than editing the assertions to match a story.
"""

import pytest

from pension.analysis import run
from pension.assumptions import Assumptions
from pension.liability import effective_duration


@pytest.fixture(scope="module")
def results():
    return run(Assumptions())


def test_headline_present_values(results):
    liability = results["liability"]
    assert liability["abo"] == 223_036_093.95
    assert liability["pbo"] == 262_950_594.69
    assert liability["pbo_minus_abo"] == 39_914_500.74
    assert liability["assets"] == 200_000_000.0
    assert liability["surplus"] == -62_950_594.69
    assert liability["funded_ratio"] == pytest.approx(200_000_000 / 262_950_594.69)
    assert liability["seriatim_aggregate_gap"] == 0.0


def test_duration_matches_the_hundred_basis_point_repricing(results):
    liability = results["liability"]
    recomputed = effective_duration(
        liability["pbo_down_100bp"],
        liability["pbo_up_100bp"],
        liability["pbo"],
        shock=0.01,
    )
    assert liability["effective_duration"] == pytest.approx(recomputed, rel=1e-9)
    assert liability["effective_duration"] == pytest.approx(13.89136344697913, rel=1e-9)
    assert liability["effective_annual_rate"] == pytest.approx(0.05704822710997248, rel=1e-9)


def test_rate_shock_direction(results):
    by_shock = {row["shock_bp"]: row["pbo"] for row in results["rate_scenarios"]}
    assert by_shock[-100] > by_shock[0] > by_shock[100]
    assert by_shock[-100] == 303_391_010.24
    assert by_shock[100] == 230_336_164.65


def test_buyout_indications(results):
    prt = results["prt"]
    assert prt["liftout_lives"] == 743
    assert prt["liftout_pbo_released"] == 112_525_063.42
    assert prt["liftout_premium"] == 126_850_139.06
    assert prt["liftout_settlement_loss"] == pytest.approx(
        prt["liftout_premium"] - prt["liftout_pbo_released"]
    )
    assert prt["residual_funded_ratio"] == pytest.approx(
        prt["residual_assets"] / prt["residual_pbo"]
    )
    assert prt["termination_lives"] == 1563
    assert prt["termination_premium"] == 258_000_058.95
    assert prt["termination_cash_shortfall"] == pytest.approx(prt["termination_premium"] - prt["assets"])
    assert prt["curtailment_gain"] == pytest.approx(results["liability"]["pbo"] - results["liability"]["abo"])


def test_clean_census_counts(results):
    assert results["census"]["raw_records"] == 1580
    assert results["census"]["clean_records"] == 1563
    assert results["validation"]["records_excluded"] == 17
    counts = {row["status"]: row["participants"] for row in results["by_status"]}
    assert counts == {
        "active": 514,
        "deferred_vested": 306,
        "retiree": 634,
        "beneficiary": 109,
    }
    assert sum(row["pbo"] for row in results["by_status"]) == pytest.approx(results["liability"]["pbo"])
