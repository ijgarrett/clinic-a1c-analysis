"""Hand-calculated expected results for the fixture in conftest.HAND_ROWS.

Settings: window 2024-01-01 to 2024-12-31, baseline = first in window, control < 7.0,
tolerance 0.5, groups [5.7, 6.5, 8.0, 10.0].

Kept results by patient (after cleaning):
  10001: 2023-12-15 9.9 | 2024-01-01 8.0 | 2024-04-01 6.9 | 2024-12-31 7.2 | 2025-01-05 6.0  (5 kept)
  10002: 7.0 -> 7.5        10003: 6.8 -> 6.3        10004: 9.0
  10005: 10.2 (copy removed) -> 10.8                 10006: (7.4/7.9 held) 7.1 -> 6.5
  10007: 5.5 -> 5.4 (comparator and text removed)   10008: 6.0 -> 6.6
Matched A1C rows 25; kept 18; removed 7 (1 copy, 2 held, 1 comparator, 1 text, 1 invalid date, 1 missing ID).

Baseline and follow-up (window 2024):
  10001 8.0 -> 7.2 = -0.8 improved | 10002 7.0 -> 7.5 = +0.5 stable | 10003 6.8 -> 6.3 = -0.5 stable
  10004 9.0 (no follow-up)         | 10005 10.2 -> 10.8 = +0.6 worse | 10006 7.1 -> 6.5 = -0.6 improved
  10007 5.5 -> 5.4 = -0.1 stable   | 10008 6.0 -> 6.6 = +0.6 worse
Paired 7: improved 2, stable 3, worsened 2.
Sorted changes: -0.8, -0.6, -0.5, -0.1, +0.5, +0.6, +0.6 -> median -0.1; Q1 -0.55; Q3 +0.55.
Improved decreases 0.8 and 0.6 -> median 0.7.

Control (< 7.0):
  Latest inside window at target: 10003 6.3, 10006 6.5, 10007 5.4, 10008 6.6 -> 4 of 8.
  Above-target baseline (>= 7.0): 10001, 10002 (7.0 is not < 7.0), 10004, 10005, 10006 -> 5.
  Reached target later: 10001 (6.9 on 2024-04-01), 10006 (6.5 on 2024-08-01) -> 2 of 5; 2 of 4 with a later result.
  No later result: 10004 -> 1. Baseline already at target: 10003, 10007, 10008 -> 3.
Time to control: 10001 Jan 1 -> Apr 1 = 91 days (2024 is a leap year); 10006 May 1 -> Aug 1 = 92 days.
  Median among achievers = 91.5. Censored: 10002 at 182 days, 10005 at 182 days.
  Kaplan-Meier: day 91: 4 at risk, 1 event -> 25%; day 92: 3 at risk, 1 event -> 50%.
"""

import datetime as dt

import pandas as pd
import pytest

from a1c.config import Settings
from a1c.pipeline import run_pipeline

WINDOW = dict(window_start=dt.date(2024, 1, 1), window_end=dt.date(2024, 12, 31), km_min_at_risk=1,
              min_denominator=1)


@pytest.fixture
def result(hand_export):
    return run_pipeline(hand_export, Settings(cohort_mode="all_tested", **WINDOW), source_name="hand")


def by_patient(result):
    return result.outcomes.patients


def test_cleaning_counts(result):
    c = result.clean
    assert c.rows_matched == 25
    assert c.rows_kept == 18
    counts = c.rule_counts.set_index("rule")["rows"]
    assert counts["identical_same_day_copy"] == 1
    assert counts["conflicting_same_day"] == 2
    assert counts["comparator_result"] == 1
    assert counts["text_result"] == 1
    assert counts["invalid_date"] == 1
    assert counts["missing_id"] == 1
    assert set(result.a1c.rows["attribute"].str.casefold()) == {"hemoglobin a1c"}


def test_baseline_followup_and_dates(result):
    p = by_patient(result)
    assert p.loc["10001", "baseline_a1c"] == 8.0           # 2024-01-01 is included (start boundary)
    assert p.loc["10001", "followup_a1c"] == 7.2           # 2024-12-31 is included (end boundary)
    assert p.loc["10001", "followup_date"] == pd.Timestamp("2024-12-31")  # 2025 result never used
    assert p.loc["10006", "baseline_a1c"] == 7.1           # held same-day rows are not used
    assert p.loc["10007", "baseline_a1c"] == 5.5
    assert p.loc["10008", "baseline_a1c"] == 6.0           # "6.0%" parsed
    assert not p.loc["10004", "paired"]
    assert "10009" not in p.index
    assert result.outcomes.results_after_end == 1


def test_categories_and_tolerance_boundaries(result):
    p = by_patient(result)
    assert p.loc["10002", "change"] == 0.5 and p.loc["10002", "category"] == "Stable"
    assert p.loc["10003", "change"] == -0.5 and p.loc["10003", "category"] == "Stable"
    assert p.loc["10005", "category"] == "Worsened"
    cats = result.outcomes.categories.set_index("category")
    assert cats.loc["Improved", "patients"] == 2
    assert cats.loc["Stable", "patients"] == 3
    assert cats.loc["Worsened", "patients"] == 2
    assert cats.loc["Improved", "denominator"] == 7
    assert cats.loc["Improved", "percent"] == 28.6
    assert cats.loc["No follow-up", "patients"] == 1
    assert cats.loc["No follow-up", "denominator"] == 8


def test_magnitude(result):
    m = result.outcomes.magnitude.set_index("measure")
    row = m.iloc[0]
    assert (row["patients"], row["median_pp"], row["q1_pp"], row["q3_pp"]) == (7, -0.1, -0.55, 0.55)
    assert m.iloc[1]["patients"] == 2 and m.iloc[1]["median_pp"] == 0.7


def test_control_denominators(result):
    c = result.outcomes.control
    assert list(c["numerator"]) == [4, 4, 2, 2, 1, 3]
    assert list(c["denominator"]) == [8, 7, 5, 4, 5, 8]
    assert list(c["percent"][:4]) == [50.0, 57.1, 40.0, 50.0]


def test_threshold_equality_and_operator(hand_export):
    lt = run_pipeline(hand_export, Settings(cohort_mode="all_tested", control_operator="<", **WINDOW))
    le = run_pipeline(hand_export, Settings(cohort_mode="all_tested", control_operator="<=", **WINDOW))
    assert not lt.outcomes.patients.loc["10002", "baseline_at_target"]   # 7.0 is not < 7.0
    assert le.outcomes.patients.loc["10002", "baseline_at_target"]       # 7.0 is <= 7.0
    assert le.outcomes.control.iloc[2]["denominator"] == 4


def test_first_documented_control(result):
    p = by_patient(result)
    assert p.loc["10001", "days_to_control"] == 91
    assert p.loc["10006", "days_to_control"] == 92
    assert pd.isna(p.loc["10002", "days_to_control"])
    ttc = result.outcomes.time_to_control.set_index("measure")
    assert ttc.loc["Median days to first documented control", "value"] == 91.5
    assert ttc.loc["With at least one later result (follow-up coverage)", "value"] == 4
    assert ttc.loc["Median follow-up of those patients (days)", "value"] == 182
    km = result.outcomes.km_curve.set_index("days")
    assert km.loc[91.0, "pct_reached"] == 25.0
    assert km.loc[92.0, "pct_reached"] == 50.0
    cp = result.outcomes.km_checkpoints.set_index("day")
    assert cp.loc[180, "pct_reached"] == 50.0 and cp.loc[180, "still_followed"] == 2


def test_groups_are_nonoverlapping(result):
    g = result.outcomes.by_group.set_index("baseline_group")
    assert list(g["baseline_patients"]) == [1, 1, 3, 2, 1]
    assert g.loc["8 to below 10", "baseline_patients"] == 2       # 8.0 is in [8, 10)
    assert g.loc["6.5 to below 8", "median_change_pp"] == -0.5
    assert g["baseline_patients"].sum() == result.outcomes.n_cohort


def test_lab_subgroup(hand_export):
    r = run_pipeline(hand_export, Settings(cohort_mode="lab_subgroup", subgroup_min_baseline=6.5, **WINDOW))
    assert r.outcomes.n_cohort == 6 and r.outcomes.n_paired == 5
    cats = r.outcomes.categories.set_index("category")["patients"]
    assert (cats["Improved"], cats["Stable"], cats["Worsened"]) == (2, 2, 1)


def test_pre_window_baseline(hand_export):
    s = Settings(cohort_mode="all_tested", baseline_mode="pre_window", lookback_days=365,
                 window_start=dt.date(2024, 7, 1), window_end=dt.date(2024, 12, 31), km_min_at_risk=1)
    p = run_pipeline(hand_export, s).outcomes.patients
    # 10001: latest before 2024-07-01 is 6.9 (Apr 1); follow-up inside window is 7.2 (Dec 31).
    assert p.loc["10001", "baseline_a1c"] == 6.9 and p.loc["10001", "followup_a1c"] == 7.2
    assert p.loc["10001", "change"] == 0.3 and p.loc["10001", "category"] == "Stable"
    # 10005: 10.2 (Jan 10) -> 10.8 (Jul 10)
    assert p.loc["10005", "change"] == 0.6
    # 10004 has a baseline but nothing inside the window
    assert not p.loc["10004", "paired"]
    # follow-up dates are always inside the window
    assert p["followup_date"].dropna().between(pd.Timestamp("2024-07-01"), pd.Timestamp("2024-12-31")).all()


def test_fixed_window_never_uses_later_results(hand_export):
    s = Settings(cohort_mode="all_tested", window_start=dt.date(2024, 7, 1), window_end=dt.date(2024, 12, 31))
    p = run_pipeline(hand_export, s).outcomes.patients
    # 10001 has one result inside the window (Dec 31). The 2025 result must not become a follow-up.
    assert p.loc["10001", "baseline_a1c"] == 7.2 and not p.loc["10001", "paired"]


def test_empty_cohort(hand_export):
    r = run_pipeline(hand_export, Settings(cohort_mode="lab_subgroup", subgroup_min_baseline=14.0, **WINDOW))
    assert r.outcomes.n_cohort == 0
    assert r.outcomes.categories["patients"].sum() == 0
    assert r.outcomes.km_curve.empty
    from a1c.report import build_report, render_html
    rep = build_report(r)
    assert rep.charts["outcomes"] is None
    assert "A1C outcome report" in render_html(rep)


def test_window_with_no_results(hand_export):
    s = Settings(cohort_mode="all_tested", window_start=dt.date(2022, 1, 1), window_end=dt.date(2022, 6, 30))
    r = run_pipeline(hand_export, s)
    assert r.outcomes.n_cohort == 0 and r.outcomes.tests_per_year.empty
