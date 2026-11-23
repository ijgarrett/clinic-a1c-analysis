"""Duplicate handling, approvals, exclusions and value classification."""

import pytest

from a1c.cleaning import classify_value
from a1c.config import Settings
from a1c.pipeline import run_pipeline

from conftest import HAND_ROWS, export_bytes


@pytest.mark.parametrize("text,kind", [
    ("7.2", "number"), ("7.2%", "number"), (" 7 ", "number"), (".9", "number"),
    (">14.0", "comparator"), ("<4.0", "comparator"), (">=15", "comparator"),
    ("6.3.", "malformed"), ("7,2", "malformed"), ("Clotted sample", "text"), ("", "blank"), (None, "blank"),
])
def test_classify_value(text, kind):
    assert classify_value(text) == kind


def _source_row(result, patient, value):
    rows = result.a1c.rows
    return int(rows[(rows["patient_id"] == patient) & (rows["value_text"] == value)]["source_row"].iloc[0])


def test_approved_conflict_row_is_kept(hand_export):
    first = run_pipeline(hand_export, Settings(cohort_mode="all_tested"))
    keep = _source_row(first, "10006", "7.9")
    second = run_pipeline(hand_export, Settings(cohort_mode="all_tested", approved_keep_rows=[keep]))
    m = second.clean.measurements
    day = m[(m["patient_id"] == "10006") & (m["date"] == "2024-02-01")]
    assert list(day["a1c"]) == [7.9]
    assert second.clean.rule_counts.set_index("rule").loc["conflicting_same_day", "rows"] == 1


def test_identical_copies_held_when_collapse_is_off(hand_export):
    r = run_pipeline(hand_export, Settings(cohort_mode="all_tested", collapse_identical_same_day=False))
    counts = r.clean.rule_counts.set_index("rule")["rows"]
    assert counts["identical_same_day_copy"] == 0
    assert counts["conflicting_same_day"] == 4          # 2 identical + 2 conflicting rows held


def test_exclusion_needs_reason(hand_export):
    with pytest.raises(ValueError, match="reason"):
        run_pipeline(hand_export, Settings(excluded_source_rows=[3]))
    r = run_pipeline(hand_export, Settings(cohort_mode="all_tested", excluded_source_rows=[3],
                                           exclusion_reason="Lab entry error confirmed by clinic"))
    assert r.clean.rule_counts.set_index("rule").loc["approved_exclusion", "rows"] == 1


def test_unusual_values_kept_and_flagged():
    data = export_bytes([("1", "2024-01-01", "Hemoglobin A1c", "21.8"), ("1", "2024-06-01", "Hemoglobin A1c", "3.8"),
                         ("2", "2024-01-01", "Hemoglobin A1c", "150")])
    r = run_pipeline(data, Settings(cohort_mode="all_tested"))
    counts = r.clean.rule_counts.set_index("rule")["rows"]
    assert counts["unusual_high"] == 1 and counts["unusual_low"] == 1
    assert counts["not_a_possible_percent"] == 1
    assert sorted(r.clean.measurements["a1c"]) == [3.8, 21.8]
    assert r.clean.unusual_values == [3.8, 21.8]


def test_review_log_keeps_source_text(hand_export):
    r = run_pipeline(hand_export, Settings(cohort_mode="all_tested"))
    log = r.clean.review_log
    assert {">14.0", "Clotted sample", "7.4", "7.9"} <= set(log["value_text"].dropna())
    assert "2024-02-30" in set(log["date_text"])
