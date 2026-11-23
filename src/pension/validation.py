"""Data checks run before a pension risk transfer pricing tape is trusted.

Hard findings drop the record from the valuation. Soft findings stay in the
valuation and are reported. The rules are the kind of census scrub a PRT
desk does before an annuity indication: identity, sex, dates of birth,
benefit amount, service that is possible, pay, and contingent annuitant data
on joint-and-survivor forms.

The planted defects in the generator are what make several of these rules fire.
A clean synthetic tape with no defects would be a poor demonstration of the
control.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from pension.assumptions import Assumptions
from pension.paths import SQL_DIR

HARD = "hard"
SOFT = "soft"


def _age_from(dob: pd.Series, year: int) -> pd.Series:
    parsed = pd.to_datetime(dob, errors="coerce")
    return year - parsed.dt.year


def validate_census(census: pd.DataFrame, assumptions: Assumptions | None = None) -> pd.DataFrame:
    """Return one row per finding. A participant can have several findings."""
    assumptions = assumptions or Assumptions()
    frame = census.reset_index(drop=True)
    year = assumptions.measurement_date.year
    valuation_ts = pd.Timestamp(assumptions.measurement_date)

    participant_id = frame["participant_id"].astype("string")
    status = frame["status"].astype("string")
    sex = frame["sex"].astype("string")
    age = _age_from(frame["date_of_birth"], year)
    spouse_age = _age_from(frame["spouse_date_of_birth"], year)
    benefit = pd.to_numeric(frame["annual_benefit"], errors="coerce")
    compensation = pd.to_numeric(frame["compensation"], errors="coerce")
    service = pd.to_numeric(frame["service_years"], errors="coerce")
    final_pay = pd.to_numeric(frame["final_average_pay"], errors="coerce")
    form = frame["payment_form"].astype("string")
    spouse_sex = frame["spouse_sex"].astype("string")
    hire = pd.to_datetime(frame["hire_date"], errors="coerce")
    termination = pd.to_datetime(frame["termination_date"], errors="coerce")
    married = frame["married"].fillna(False).astype(bool)

    findings: list[dict] = []

    def add(mask: pd.Series, severity: str, rule_id: str, message: str) -> None:
        hits = frame.index[mask.fillna(False).to_numpy()]
        for idx in hits:
            findings.append(
                {
                    "row_number": int(idx) + 1,
                    "participant_id": None if pd.isna(participant_id.iloc[idx]) else str(participant_id.iloc[idx]),
                    "status": None if pd.isna(status.iloc[idx]) else str(status.iloc[idx]),
                    "severity": severity,
                    "rule_id": rule_id,
                    "message": message,
                }
            )

    known_status = status.isin(["active", "deferred_vested", "retiree", "beneficiary"])
    active = status.eq("active")
    deferred = status.eq("deferred_vested")
    needs_accrual = active | deferred
    joint = form.isin(["JS50", "JS100"])

    duplicate = participant_id.duplicated(keep=False) | participant_id.isna()
    add(duplicate, HARD, "duplicate_id", "Participant id is missing or duplicated; both rows are dropped.")
    add(~known_status, HARD, "bad_status", "Status is not active, deferred vested, retiree, or beneficiary.")
    add(~sex.isin(["M", "F"]), HARD, "bad_sex", "Sex code is missing or not M/F.")
    add(age.isna() | age.lt(16) | age.gt(105), HARD, "bad_age", "Date of birth is missing or age is outside 16 to 105.")
    add(
        benefit.isna() | benefit.le(0) | benefit.gt(400_000),
        HARD,
        "bad_benefit",
        "Annual benefit is missing, not positive, or above $400,000.",
    )
    add(
        active & (compensation.isna() | compensation.le(0) | compensation.gt(1_000_000)),
        HARD,
        "bad_compensation",
        "Active compensation is missing, not positive, or above $1,000,000.",
    )
    add(
        needs_accrual & (service.isna() | service.lt(0) | service.gt(age - 16)),
        HARD,
        "impossible_service",
        "Credited service is missing, negative, or greater than age minus 16.",
    )
    add(
        needs_accrual & (final_pay.isna() | final_pay.le(0)),
        HARD,
        "bad_final_average_pay",
        "Final average pay is missing or not positive.",
    )
    add(~form.isin(["SLA", "JS50", "JS100", "C10"]), HARD, "bad_form", "Payment form is not SLA, JS50, JS100, or C10.")
    add(
        joint & (spouse_age.isna() | ~spouse_sex.isin(["M", "F"]) | spouse_age.lt(18) | spouse_age.gt(105)),
        HARD,
        "joint_missing_spouse",
        "Joint-and-survivor form is missing a usable spouse sex or date of birth.",
    )
    add(
        needs_accrual & married & (spouse_age.isna() | ~spouse_sex.isin(["M", "F"])),
        HARD,
        "married_missing_spouse",
        "Married non-retired participant is missing a usable spouse sex or date of birth.",
    )
    add(
        active & hire.notna() & hire.gt(valuation_ts),
        HARD,
        "hire_after_measurement",
        "Hire date is after the measurement date.",
    )
    add(
        deferred & hire.notna() & termination.notna() & termination.lt(hire),
        HARD,
        "termination_before_hire",
        "Termination date is before the hire date.",
    )
    add(
        status.eq("retiree") & age.notna() & age.lt(45),
        HARD,
        "retiree_too_young",
        "Retiree is under age 45, which is not a credible in-pay record.",
    )

    accrual_base = final_pay * service
    accrual = benefit.div(accrual_base.where(accrual_base > 0))
    add(
        active & benefit.gt(0) & accrual.notna() & (accrual - assumptions.accrual_rate).abs().gt(0.002),
        SOFT,
        "formula_mismatch",
        "Implied accrual rate differs from the 1.50% plan formula by more than 0.20 percentage points.",
    )
    add(
        active & compensation.gt(assumptions.limit_401a17),
        SOFT,
        "compensation_over_401a17",
        "Compensation is above the 2025 401(a)(17) limit of $350,000.",
    )
    add(
        benefit.gt(assumptions.limit_415b),
        SOFT,
        "benefit_over_415b",
        "Annual benefit is above the 2025 415(b) dollar limit of $280,000.",
    )
    add(
        benefit.gt(0) & benefit.lt(600),
        SOFT,
        "de_minimis_benefit",
        "Annual benefit is under $600 and would be reviewed for a lump-sum cashout.",
    )
    add(
        status.eq("retiree") & age.notna() & age.ge(45) & age.lt(55),
        SOFT,
        "early_retiree",
        "Retiree is under age 55. Confirm the early-retirement commencement.",
    )
    add(
        deferred & age.notna() & age.ge(assumptions.normal_retirement_age),
        SOFT,
        "deferred_past_nra",
        "Deferred vested participant is past normal retirement age but not in pay.",
    )
    add(
        age.notna() & spouse_age.notna() & (age - spouse_age).abs().gt(25),
        SOFT,
        "spouse_age_gap",
        "Member and spouse ages differ by more than 25 years.",
    )
    elapsed = (valuation_ts - hire).dt.days / 365.25
    add(
        active & hire.notna() & service.notna() & (elapsed - service).abs().gt(1.5),
        SOFT,
        "service_date_mismatch",
        "Credited service and hire date differ by more than 1.5 years.",
    )

    columns = ["row_number", "participant_id", "status", "severity", "rule_id", "message"]
    if not findings:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(findings)[columns]


def clean_census(census: pd.DataFrame, findings: pd.DataFrame) -> pd.DataFrame:
    """Drop every row whose participant id has a hard finding.

    Duplicate ids are hard findings on every copy, so the whole id is removed.
    """
    if findings.empty:
        return census.copy()
    hard_ids = set(findings.loc[findings["severity"] == HARD, "participant_id"].dropna())
    keep = ~census["participant_id"].isin(hard_ids)
    return census.loc[keep].reset_index(drop=True)


def validation_summary(findings: pd.DataFrame, raw_rows: int, clean_rows: int) -> dict:
    if findings.empty:
        by_rule: dict[str, int] = {}
        hard_findings = 0
        soft_findings = 0
        hard_ids: list[str] = []
    else:
        by_rule = findings.groupby("rule_id").size().sort_values(ascending=False).to_dict()
        by_rule = {str(key): int(value) for key, value in by_rule.items()}
        hard_findings = int((findings["severity"] == HARD).sum())
        soft_findings = int((findings["severity"] == SOFT).sum())
        hard_ids = sorted(set(findings.loc[findings["severity"] == HARD, "participant_id"].dropna()))
    return {
        "raw_records": int(raw_rows),
        "clean_records": int(clean_rows),
        "records_excluded": int(raw_rows - clean_rows),
        "hard_findings": hard_findings,
        "soft_findings": soft_findings,
        "findings_by_rule": by_rule,
        "excluded_participant_ids": hard_ids,
    }


def write_sqlite(census: pd.DataFrame, path: Path) -> None:
    output = census.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        output.to_sql("census", connection, index=False, if_exists="replace")


def load_sql_checks(path: Path | None = None) -> dict[str, str]:
    text = (path or (SQL_DIR / "census_checks.sql")).read_text()
    checks: dict[str, str] = {}
    name = None
    chunk: list[str] = []
    for line in text.splitlines():
        if line.startswith("-- @@"):
            if name and chunk:
                checks[name] = "\n".join(chunk).strip()
            name = line.replace("-- @@", "", 1).strip()
            chunk = []
        elif not line.startswith("--"):
            chunk.append(line)
    if name and chunk:
        checks[name] = "\n".join(chunk).strip().rstrip(";")
    return checks


def run_sql_checks(database: Path, sql_path: Path | None = None) -> dict[str, pd.DataFrame]:
    checks = load_sql_checks(sql_path)
    results = {}
    with sqlite3.connect(database) as connection:
        for name, query in checks.items():
            results[name] = pd.read_sql_query(query, connection)
    return results
