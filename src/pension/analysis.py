"""Run the full measurement and write the tables, charts, and workbook.

The asset value and the pricing loads are read from `Assumptions`. They are
not adjusted after the present values are known.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import numpy as np
import pandas as pd

from pension.assumptions import Assumptions
from pension.cashflows import STATUSES, annual_cash_flows, project_census
from pension.census import generate_census
from pension.discount import load_hqm_curve
from pension.liability import (
    average_payment_time,
    effective_convexity,
    effective_duration,
    funded_status,
    liability_dv01,
    present_value,
    single_effective_rate,
)
from pension.mortality import build_mortality
from pension.paths import FIGURES, OUTPUT_DATA, REPORTS
from pension.prt import IN_PAY, deal_comparison, indication
from pension.reporting import write_figures, write_workbook
from pension.validation import (
    clean_census,
    run_sql_checks,
    validate_census,
    validation_summary,
    write_sqlite,
)


def _cents(value: float) -> float:
    return round(float(value), 2)


def _jsonable(value):
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, float):
        if np.isnan(value):
            return None
        return value
    return value


def _status_table(census: pd.DataFrame, participants: pd.DataFrame) -> list[dict]:
    rows = []
    for status in STATUSES:
        tape = census.loc[census["status"] == status]
        valued = participants.loc[participants["status"] == status]
        pbo = float(valued["pbo"].sum())
        rows.append(
            {
                "status": status,
                "participants": int(len(tape)),
                "average_age": round(float(tape["age"].mean()), 2),
                "pbo_weighted_age": round(float((valued["age"] * valued["pbo"]).sum() / pbo), 2) if pbo else None,
                "tape_annual_benefit": _cents(tape["annual_benefit"].sum()),
                "abo_annual_benefit": _cents(valued["abo_annual_benefit"].sum()),
                "pbo_annual_benefit": _cents(valued["pbo_annual_benefit"].sum()),
                "abo": _cents(valued["abo"].sum()),
                "pbo": _cents(pbo),
            }
        )
    return rows


def run(assumptions: Assumptions | None = None) -> dict:
    """Generate, scrub, value, price, and write every output. Return the summary."""
    assumptions = assumptions or Assumptions()
    raw = generate_census(assumptions)
    findings = validate_census(raw, assumptions)
    clean = clean_census(raw, findings)
    validation = validation_summary(findings, len(raw), len(clean))

    curve = load_hqm_curve(assumptions.curve_year, assumptions.curve_month)
    accounting = build_mortality()
    book = project_census(clean, assumptions, accounting, curve)

    pbo_cash = book.benefit("pbo")
    abo_cash = book.benefit("abo")
    pbo = present_value(pbo_cash, book.times, curve)
    abo = present_value(abo_cash, book.times, curve)
    seriatim_gap = abs(float(book.participants["pbo"].sum()) - pbo)
    if seriatim_gap > 1.0:
        raise RuntimeError(f"Seriatim PBO and aggregate PBO differ by ${seriatim_gap:,.2f}")

    pbo_up_100 = present_value(pbo_cash, book.times, curve.shocked(100))
    pbo_down_100 = present_value(pbo_cash, book.times, curve.shocked(-100))
    pbo_up_1 = present_value(pbo_cash, book.times, curve.shocked(1))
    pbo_down_1 = present_value(pbo_cash, book.times, curve.shocked(-1))
    effective_rate = single_effective_rate(pbo_cash, book.times, pbo)
    duration = effective_duration(pbo_down_100, pbo_up_100, pbo, shock=0.01)
    payment_time = average_payment_time(pbo_cash, book.times, curve)
    convexity = effective_convexity(pbo_down_100, pbo_up_100, pbo, shock=0.01)
    dv01 = liability_dv01(pbo_down_1, pbo_up_1)
    funding = funded_status(assumptions.market_value_of_assets, pbo)

    rate_rows = []
    for shock in (-100, -50, 0, 50, 100):
        shocked = curve if shock == 0 else curve.shocked(shock)
        value = pbo if shock == 0 else present_value(pbo_cash, book.times, shocked)
        ratio = assumptions.market_value_of_assets / value
        rate_rows.append(
            {
                "shock_bp": shock,
                "pbo": _cents(value),
                "funded_ratio": ratio,
                "surplus": _cents(assumptions.market_value_of_assets - value),
            }
        )

    mortality_runs = [
        ("No future improvement", build_mortality(static_from_year=assumptions.static_improvement_year)),
        ("MP-2021 generational", accounting),
        (
            "MP-2021 +50 bp",
            build_mortality(
                extra_improvement=assumptions.extra_improvement,
                extra_improvement_from_year=assumptions.first_exposure_year,
            ),
        ),
    ]
    mortality_rows = []
    for label, basis in mortality_runs:
        if label == "MP-2021 generational":
            value = pbo
        else:
            scenario_book = project_census(clean, assumptions, basis, curve=None)
            value = present_value(scenario_book.benefit("pbo"), scenario_book.times, curve)
        mortality_rows.append(
            {
                "label": label,
                "pbo": _cents(value),
                "change_vs_base": value / pbo - 1.0,
            }
        )

    pricing_curve = curve.shocked(assumptions.pricing_spread_bp, name="Pricing curve")
    pricing_mortality = build_mortality(qx_multiplier=assumptions.pricing_qx_multiplier)
    pricing_book = project_census(clean, assumptions, pricing_mortality, curve=None)
    liftout = indication(pricing_book, pricing_curve, assumptions, basis="pbo", statuses=IN_PAY)
    termination = indication(pricing_book, pricing_curve, assumptions, basis="abo")
    in_pay_pbo = present_value(book.benefit("pbo", IN_PAY), book.times, curve)
    prt = deal_comparison(
        accounting_pbo=pbo,
        accounting_abo=abo,
        in_pay_pbo=in_pay_pbo,
        liftout=liftout,
        termination=termination,
        assets=assumptions.market_value_of_assets,
    )
    for key, value in list(prt.items()):
        if key.endswith("ratio") or key.endswith("over_pbo") or key.endswith("over_abo") or key == "lives":
            continue
        if isinstance(value, float):
            prt[key] = _cents(value)

    annual = annual_cash_flows(book, curve, assumptions.first_exposure_year)
    status_rows = _status_table(clean, book.participants)
    # Official totals are the aggregate cash-flow present values, rounded to the cent.
    # Status rows are the seriatim sum and can differ by a few cents.
    spots = {
        f"{maturity:.1f}": round(float(rate), 6)
        for maturity, rate in zip(curve.maturities, curve.spots)
    }

    results = {
        "plan_name": assumptions.plan_name,
        "measurement_date": assumptions.measurement_date.isoformat(),
        "disclaimer": (
            "Synthetic census and a hypothetical plan. Public Pri-2012, MP-2021, and "
            "Treasury HQM data. Not actuarial advice, not a PRT quote, and not the "
            "experience of any insurer or plan sponsor."
        ),
        "assumptions": {
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in asdict(assumptions).items()
        },
        "census": {
            "raw_records": int(len(raw)),
            "clean_records": int(len(clean)),
            "by_status": status_rows,
            "male_participants": int((clean["sex"] == "M").sum()),
            "female_participants": int((clean["sex"] == "F").sum()),
            "tape_annual_benefit": _cents(clean["annual_benefit"].sum()),
        },
        "validation": validation,
        "discount_curve": {
            "name": curve.name,
            "compounding": curve.compounding,
            "spots": spots,
            "selected": {
                f"{tenor:g}": float(curve.spot(tenor))
                for tenor in (0.5, 1, 2, 5, 10, 15, 20, 30)
            },
        },
        "liability": {
            "abo": _cents(abo),
            "pbo": _cents(pbo),
            "pbo_minus_abo": _cents(pbo - abo),
            "assets": assumptions.market_value_of_assets,
            "surplus": _cents(funding["surplus"]),
            "funded_ratio": funding["funded_ratio"],
            "abo_funded_ratio": assumptions.market_value_of_assets / abo,
            "effective_annual_rate": effective_rate,
            "effective_duration": duration,
            "average_payment_time": payment_time,
            "convexity": convexity,
            "dv01": _cents(dv01),
            "pbo_up_100bp": _cents(pbo_up_100),
            "pbo_down_100bp": _cents(pbo_down_100),
            "in_pay_pbo": _cents(in_pay_pbo),
            "seriatim_aggregate_gap": round(seriatim_gap, 4),
            "mortality": accounting.description,
        },
        "by_status": status_rows,
        "rate_scenarios": rate_rows,
        "mortality_scenarios": mortality_rows,
        "prt": prt,
    }

    OUTPUT_DATA.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    raw.to_csv(OUTPUT_DATA / "census_raw.csv", index=False)
    clean.to_csv(OUTPUT_DATA / "census_clean.csv", index=False)
    findings.to_csv(OUTPUT_DATA / "validation_findings.csv", index=False)
    book.participants.to_csv(OUTPUT_DATA / "participant_values.csv", index=False)
    annual.to_csv(OUTPUT_DATA / "annual_cash_flows.csv", index=False)
    database = OUTPUT_DATA / "census.sqlite"
    write_sqlite(raw, database)
    sql_results = run_sql_checks(database)
    for name, frame in sql_results.items():
        frame.to_csv(OUTPUT_DATA / f"sql_{name}.csv", index=False)

    results = _jsonable(results)
    (OUTPUT_DATA / "summary.json").write_text(json.dumps(results, indent=2))
    (REPORTS / "summary.json").write_text(json.dumps(results, indent=2))

    write_figures(
        FIGURES,
        census=clean,
        annual=annual,
        curve_maturities=np.asarray(curve.maturities),
        curve_spots=np.asarray(curve.spots),
        liability=results["liability"],
        rate_scenarios=results["rate_scenarios"],
        mortality_scenarios=results["mortality_scenarios"],
        prt=results["prt"],
        measurement_date=results["measurement_date"],
    )
    write_workbook(REPORTS / "pension_summary.xlsx", results, annual, findings)
    _print_summary(results)
    return results


def _print_summary(results: dict) -> None:
    liability = results["liability"]
    prt = results["prt"]
    print(results["plan_name"], results["measurement_date"])
    print(f"Clean lives {results['census']['clean_records']} of {results['census']['raw_records']}")
    print(f"ABO {liability['abo']:,.2f}   PBO {liability['pbo']:,.2f}")
    print(
        f"Funded ratio {liability['funded_ratio'] * 100:.2f}%   "
        f"effective rate {liability['effective_annual_rate'] * 100:.2f}%   "
        f"duration {liability['effective_duration']:.2f}"
    )
    print(
        f"Lift-out premium {prt['liftout_premium']:,.2f}   "
        f"termination premium {prt['termination_premium']:,.2f}"
    )


def main() -> None:
    run()


if __name__ == "__main__":
    main()
