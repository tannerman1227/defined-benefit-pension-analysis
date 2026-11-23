"""Pri-2012 loader and the generational MP-2021 projection formula."""

import openpyxl
import pytest

from pension.mortality import build_mortality
from pension.paths import RAW_DATA


@pytest.fixture(scope="module")
def base():
    return build_mortality()


def test_2012_qx_matches_the_published_workbook(base):
    workbook = openpyxl.load_workbook(RAW_DATA / "pri-2012-mortality-tables-amount.xlsx", data_only=True)
    sheet = workbook["Total Dataset"]
    # Row 6 is age 18, so age 65 is row 53. Female retiree is column 5, male employee column 9.
    female_65 = float(sheet.cell(6 + (65 - 18), 5).value)
    male_40 = float(sheet.cell(6 + (40 - 18), 9).value)
    workbook.close()
    assert base.qx("F", "retiree", 65, 2012) == pytest.approx(female_65)
    assert base.qx("M", "employee", 40, 2012) == pytest.approx(male_40)


def test_improvement_reduces_a_retiree_qx_after_the_base_year(base):
    assert base.qx("F", "retiree", 65, 2026) < base.qx("F", "retiree", 65, 2012)
    assert base.qx("M", "employee", 40, 2013) < base.qx("M", "employee", 40, 2012)


def test_one_year_of_scale_matches_the_product_formula():
    """q in 2013 is the 2012 rate times one minus the 2012 improvement at that age."""
    basis = build_mortality()
    workbook = openpyxl.load_workbook(RAW_DATA / "mp-2021-rates.xlsx", data_only=True)
    sheet = workbook["Male"]
    year_col = next(col for col in range(2, sheet.max_column + 1) if sheet.cell(2, col).value == 2012)
    age_row = next(row for row in range(3, sheet.max_row + 1) if sheet.cell(row, 1).value == 40)
    improvement = float(sheet.cell(age_row, year_col).value)
    workbook.close()
    base_q = basis.qx("M", "employee", 40, 2012)
    assert basis.qx("M", "employee", 40, 2013) == pytest.approx(base_q * (1.0 - improvement))


def test_terminal_age_is_certain_death(base):
    assert base.qx("F", "retiree", 120, 2026) == 1.0
    assert base.qx("M", "employee", 120, 2012) == 1.0


def test_static_basis_freezes_future_qx():
    frozen = build_mortality(static_from_year=2026)
    assert frozen.qx("F", "retiree", 70, 2040) == pytest.approx(frozen.qx("F", "retiree", 70, 2026))
    generational = build_mortality()
    assert generational.qx("F", "retiree", 70, 2040) < frozen.qx("F", "retiree", 70, 2040)


def test_extra_improvement_lowers_later_qx():
    base = build_mortality()
    stressed = build_mortality(extra_improvement=0.005, extra_improvement_from_year=2026)
    assert stressed.qx("M", "retiree", 75, 2026) == pytest.approx(base.qx("M", "retiree", 75, 2026))
    assert stressed.qx("M", "retiree", 75, 2050) < base.qx("M", "retiree", 75, 2050)
