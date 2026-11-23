"""Shared test helpers. All data here is invented."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from a1c.synthetic import HEADER  # noqa: E402


def export_bytes(rows, trailing_tab=True, encoding="utf-16") -> bytes:
    """Build a 5.02a-style export from short row tuples.

    Each row is (acct, date, attribute, value) or (acct, date, attribute, value, acct2).
    """
    lines = ["\t".join(HEADER)]
    for row in rows:
        acct, date, attribute, value = row[:4]
        acct2 = row[4] if len(row) > 4 else acct
        order = "Hemoglobin A1C with EAG" if attribute.lower() in ("hemoglobin a1c", "est. average glucose") else "CBC"
        fields = [acct, "", "", "", "Test Clinic", date, date, "Site", "11", acct2, "TEST, Person",
                  "N", "Routine", order, "Reviewed", "N", "No", attribute, value, "Nml", "", "", "", "Lab",
                  "1", "1", "1", "1"]
        lines.append("\t".join(fields) + ("\t" if trailing_tab else ""))
    return ("\r\n".join(lines) + "\r\n").encode(encoding)


A1C = "Hemoglobin A1c"

# Hand-calculated fixture. Window 2024-01-01 to 2024-12-31. Expected results are in
# tests/test_hand_calculated.py with the arithmetic written out.
HAND_ROWS = [
    # 10001: before window (ignored for first_in_window), start-day baseline, control on Apr 1,
    #        end-day follow-up, and a result after the end (never used).
    ("10001", "2023-12-15", A1C, "9.9"),
    ("10001", "2024-01-01", "Hemoglobin A1C", "8.0"),
    ("10001", "2024-04-01", A1C, "6.9"),
    ("10001", "2024-12-31", A1C, "7.2"),
    ("10001", "2025-01-05", A1C, "6.0"),
    ("10001", "2024-01-01", "Hemoglobin", "13.5"),             # CBC hemoglobin: not A1C
    ("10001", "2024-01-01", "Est. Average Glucose", "183"),     # calculated value: not A1C
    # 10002: baseline equal to the threshold; change exactly +0.5 (stable)
    ("10002", "2024-02-01", A1C, "7.0"),
    ("10002", "2024-08-01", A1C, "7.5"),
    # 10003: baseline at target; change exactly -0.5 (stable)
    ("10003", "2024-03-01", A1C, "6.8"),
    ("10003", "2024-09-01", A1C, "6.3"),
    # 10004: one result only (no follow-up)
    ("10004", "2024-05-01", A1C, "9.0"),
    # 10005: identical same-day copy, then +0.6 (worsened)
    ("10005", "2024-01-10", A1C, "10.2"),
    ("10005", "2024-01-10", A1C, "10.2"),
    ("10005", "2024-07-10", A1C, "10.8"),
    # 10006: conflicting same-day results (held), then 7.1 -> 6.5 (improved, control on Aug 1)
    ("10006", "2024-02-01", A1C, "7.4"),
    ("10006", "2024-02-01", A1C, "7.9"),
    ("10006", "2024-05-01", A1C, "7.1"),
    ("10006", "2024-08-01", A1C, "6.5"),
    # 10007: comparator and text results (removed), upper-case label, then 5.5 -> 5.4
    ("10007", "2024-06-01", "HEMOGLOBIN A1C", ">14.0"),
    ("10007", "2024-06-15", A1C, "Clotted sample"),
    ("10007", "2024-09-01", "HEMOGLOBIN A1C", "5.5"),
    ("10007", "2024-11-01", A1C, "5.4"),
    # 10008: value with a percent sign; +0.6 (worsened); baseline at target
    ("10008", "2024-04-01", A1C, "6.0%"),
    ("10008", "2024-10-01", A1C, "6.6"),
    # 10009: invalid date only
    ("10009", "2024-02-30", A1C, "7.7"),
    # missing ID
    ("", "2024-03-03", A1C, "6.1"),
]


@pytest.fixture
def hand_export():
    return export_bytes(HAND_ROWS)
