"""Census scrub: planted defects are found, and the clean tape is what gets valued."""

from pension.assumptions import Assumptions
from pension.census import generate_census
from pension.validation import (
    clean_census,
    load_sql_checks,
    run_sql_checks,
    validate_census,
    write_sqlite,
)


def test_generator_is_reproducible():
    assumptions = Assumptions()
    first = generate_census(assumptions)
    second = generate_census(assumptions)
    assert first.equals(second)
    assert len(first) == 520 + 310 + 640 + 110


def test_hard_defects_are_removed_and_soft_flags_remain():
    assumptions = Assumptions()
    raw = generate_census(assumptions)
    findings = validate_census(raw, assumptions)
    clean = clean_census(raw, findings)
    assert len(raw) - len(clean) == 17
    hard_ids = set(findings.loc[findings["severity"] == "hard", "participant_id"])
    assert "R-0004" in hard_ids
    assert "A-0001" in hard_ids
    assert "A-0007" not in hard_ids
    assert "A-0007" in set(clean["participant_id"])
    assert findings.loc[findings["participant_id"] == "A-0007", "rule_id"].iloc[0] == "formula_mismatch"
    # A second pass on the clean tape has no hard findings.
    again = validate_census(clean, assumptions)
    assert again.loc[again["severity"] == "hard"].empty


def test_sql_checks_match_the_planted_defects(tmp_path):
    raw = generate_census(Assumptions())
    database = tmp_path / "census.sqlite"
    write_sqlite(raw, database)
    results = run_sql_checks(database)
    assert set(load_sql_checks()) == set(results)
    duplicates = set(results["duplicate_ids"]["participant_id"])
    assert duplicates == {"R-0001"}
    assert int(results["duplicate_ids"]["rows_with_this_id"].iloc[0]) == 2
    missing_spouse = set(results["joint_life_missing_spouse"]["participant_id"])
    assert "R-0004" in missing_spouse
    outliers = set(results["formula_outliers"]["participant_id"])
    assert "A-0007" in outliers
