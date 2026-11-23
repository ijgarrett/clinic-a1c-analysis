"""Small-count suppression."""

from a1c.config import Settings
from a1c.disclosure import suppress_chain, suppress_partition
from a1c.pipeline import run_pipeline
from a1c.report import build_report


def test_primary_and_complementary():
    # 3 is below 11; it would be found from the total by subtraction, so 20 is hidden too.
    assert suppress_partition([40, 20, 3], 11) == [False, True, True]
    assert suppress_partition([40, 20, 30], 11) == [False, False, False]
    # Two small counts protect each other.
    assert suppress_partition([40, 5, 3], 11) == [False, True, True]
    # Zero is not a small count.
    assert suppress_partition([40, 0, 30], 11) == [False, False, False]


def test_total_below_limit_hides_everything():
    assert suppress_partition([4, 3, 0], 11) == [True, True, False]


def test_chain_differences():
    # 67 -> 54 is a difference of 13 (fine); 54 -> 50 is 4 (hidden).
    assert suppress_chain([519, 519, 67, 54, 50], 11) == [False, False, False, False, True]
    assert suppress_chain([100, 95], 11) == [False, True]


def test_shareable_report_has_no_small_counts(hand_export):
    r = run_pipeline(hand_export, Settings(cohort_mode="all_tested", min_cell_size=11))
    rep = build_report(r, shareable=True)
    for table in rep.tables.values():
        for col in table.frame.columns:
            for value in table.frame[col].astype(str):
                if value.replace(",", "").isdigit():
                    n = int(value.replace(",", ""))
                    if table.key in {"patient_flow", "outcome_categories", "control", "by_baseline_group",
                                     "tests_per_patient", "time_to_control"} and col in {"Patients", "Value",
                                                                                         "Baseline patients",
                                                                                         "Paired patients"}:
                        assert n == 0 or n >= 11, (table.key, col, value)
    assert "nonnumeric_results" not in rep.tables
    assert "change_histogram" not in rep.charts
    assert "SMALL COUNTS SUPPRESSED" in rep.label
