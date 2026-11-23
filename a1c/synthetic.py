"""Make a SYNTHETIC eBO 5.02a export for the demo and the tests.

All patients, names, account numbers and results are invented. The file copies
the layout of the real export: UTF-16 with a byte order mark, tab-separated,
an extra tab at the end of each data row, repeated "Patient Acct No" and "None"
columns, and many lab tests besides A1C. It also contains the data problems the
cleaning rules must catch (comparator, malformed and text results, same-day
duplicates, an ID conflict, a missing ID and an invalid date).

Command line:
    python -m a1c.synthetic --out demo_data/synthetic_5.02a_DEMO.csv
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np

HEADER = [
    "Patient Acct No", "None", "None", "None", "Practice Name", "Encounter Date",
    "Order Collection / Performed Date", "Appointment Facility Name", "Appointment Facility POS",
    "Patient Acct No", "Patient Name", "Actual Fasting", "Order Priority", "Order Name", "Order Status",
    "Approval Required", "InHouse Lab", "Lab Attribute", "Lab Attribute Value", "Order Result",
    "AOE Question", "AOE Answer", "AOE Lab Company ID", "AOE Lab Company Name",
    "Count Distinct(Patient Acct No)", "Count Distinct(Patient Acct No)",
    "Count Distinct(Patient Acct No)", "Count Distinct(Patient Acct No)",
]
START = dt.date(2023, 1, 3)
END = dt.date(2026, 11, 13)

OTHER_TESTS = [
    ("CBC", [("Hemoglobin", 11.5, 16.5, 1), ("WBC", 4.0, 10.5, 1), ("Hematocrit", 35, 49, 1)]),
    ("CMP", [("GLUCOSE", 75, 180, 0), ("BUN", 7, 25, 0), ("Creatinine", 0.6, 1.3, 2)]),
    ("Lipid Panel", [("Triglycerides", 60, 300, 0)]),
]


def _row(acct, name, date, order, attribute, value, status="Reviewed", second_acct=None, encounter=None):
    enc = encounter or date
    return {
        "acct": acct, "acct2": acct if second_acct is None else second_acct, "name": name,
        "encounter": enc, "date": date, "order": order, "attribute": attribute, "value": value, "status": status,
    }


def _to_fields(r) -> list[str]:
    date = r["date"] if isinstance(r["date"], str) else r["date"].isoformat()
    enc = r["encounter"] if isinstance(r["encounter"], str) else r["encounter"].isoformat()
    return [
        r["acct"], "", "", "", "Demo Free Clinic", enc, date, "Demo Clinic Site", "11",
        r["acct2"], r["name"], "N", "Routine", r["order"], r["status"], "N", "No",
        r["attribute"], r["value"], "Nml", "", "", "", "Demo Reference Lab", "1", "1", "1", "1",
    ]


def _trajectory(rng, n_tests):
    """Return baseline and later values for one patient."""
    kind = rng.choice(["normal", "pre", "high"], p=[0.58, 0.24, 0.18])
    if kind == "normal":
        b = rng.normal(5.3, 0.25)
    elif kind == "pre":
        b = rng.uniform(5.7, 6.45)
    else:
        b = 6.5 + rng.gamma(2.0, 1.4)
    values = [b]
    v = b
    responder = rng.random() < 0.65
    for _ in range(n_tests - 1):
        if kind == "high":
            pull = -0.5 * (v - 6.6) if responder else 0.15
            v = v + pull + rng.normal(0, 0.45)
        else:
            v = v + 0.03 + rng.normal(0, 0.18)
        values.append(v)
    return [float(np.clip(round(x, 1), 3.9, 17.5)) for x in values]


def generate_rows(seed: int = 2026, n_patients: int = 420) -> list[dict]:
    rng = np.random.default_rng(seed)
    accounts = rng.choice(np.arange(1, 99999), size=n_patients, replace=False)
    accounts[:5] = [123, 4567, 89, 2048, 777]  # IDs that need leading zeros
    span = (END - START).days
    rows = []
    for i, acct_num in enumerate(accounts):
        acct = f"{int(acct_num):05d}"
        name = f"DEMO, Patient {i + 1:04d}"
        n_tests = int(min(rng.geometric(0.45) + (rng.random() < 0.5), 9))
        first = START + dt.timedelta(days=int(rng.integers(0, span - 20)))
        dates = [first]
        for _ in range(n_tests - 1):
            nxt = dates[-1] + dt.timedelta(days=int(rng.integers(75, 330)))
            if nxt > END:
                break
            dates.append(nxt)
        values = _trajectory(rng, len(dates))
        for d, v in zip(dates, values):
            style = rng.choice(["eag", "lower", "upper"], p=[0.72, 0.23, 0.05])
            if style == "eag":
                rows.append(_row(acct, name, d, "Hemoglobin A1C with EAG", "Hemoglobin A1C", f"{v:.1f}"))
                rows.append(_row(acct, name, d, "Hemoglobin A1C with EAG", "Est. Average Glucose",
                                 f"{28.7 * v - 46.7:.0f}"))
            elif style == "lower":
                rows.append(_row(acct, name, d, "Hemoglobin A1c", "Hemoglobin A1c", f"{v:.1f}"))
            else:
                rows.append(_row(acct, name, d, "Hemoglobin A1C", "Hemoglobin A1C", f"{v:.1f}"))
            for order, tests in OTHER_TESTS:
                if rng.random() < 0.55:
                    for attr, lo, hi, digits in tests:
                        rows.append(_row(acct, name, d, order, attr, f"{rng.uniform(lo, hi):.{digits}f}"))
        # Some patients have other labs on dates without an A1C.
        if rng.random() < 0.3:
            d = START + dt.timedelta(days=int(rng.integers(0, span)))
            rows.append(_row(acct, name, d, "CBC", "Hemoglobin", f"{rng.uniform(11, 16):.1f}"))

    a1c_idx = [i for i, r in enumerate(rows) if r["attribute"].lower() == "hemoglobin a1c"]
    pick = rng.choice(a1c_idx, size=12, replace=False)
    # Data problems the cleaning rules must catch.
    rows[pick[0]]["value"] = ">14.0"
    rows[pick[1]]["value"] = "6.3."
    rows[pick[2]]["value"] = "Clotted sample"
    rows[pick[3]]["value"] = "sample clotted"
    rows[pick[4]]["value"] = ""
    rows[pick[5]]["value"] = "16.4"            # high value: kept, flagged for review
    rows[pick[6]]["acct2"] = "99999"           # ID columns disagree
    rows[pick[7]]["acct"] = ""                 # missing ID in both columns
    rows[pick[7]]["acct2"] = ""
    rows[pick[8]]["date"] = "2024-02-30"       # invalid date
    rows[pick[9]]["status"] = "Open"
    extra = []
    for j in (10, 11):                         # identical same-day copies
        extra.append(dict(rows[pick[j]]))
    conflict = dict(rows[a1c_idx[3]])          # same day, different value
    conflict["value"] = f"{float(conflict['value']) + 0.6:.1f}" if conflict["value"][0].isdigit() else "7.0"
    extra.append(conflict)
    extra.append(_row("01999", "DEMO, Patient 9999", dt.date(2024, 5, 2), "Beta-2-Glycoprotein Abs",
                      "B-2-Glycoprotein IgG", "4"))
    extra.append(_row("01999", "DEMO, Patient 9999", dt.date(2024, 5, 2), "Beta-2-Glycoprotein Abs",
                      "B-2-Glycoprotein IgM", "3"))
    rows.extend(extra)
    order = rng.permutation(len(rows))
    return [rows[i] for i in order]


def export_text(rows: list[dict]) -> str:
    lines = ["\t".join(HEADER)]
    lines += ["\t".join(_to_fields(r)) + "\t" for r in rows]   # trailing tab, as in the real export
    return "\r\n".join(lines) + "\r\n"


def generate_export(seed: int = 2026, n_patients: int = 420) -> bytes:
    """Synthetic 5.02a export as bytes (UTF-16 with BOM)."""
    return export_text(generate_rows(seed, n_patients)).encode("utf-16")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write a SYNTHETIC 5.02a export (no real patients).")
    parser.add_argument("--out", default="demo_data/synthetic_5.02a_DEMO.csv")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--patients", type=int, default=420)
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(generate_export(args.seed, args.patients))
    print(f"Wrote synthetic export: {out} (seed {args.seed}, {args.patients} patients)")


if __name__ == "__main__":
    main()
