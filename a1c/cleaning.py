"""Data-quality rules for the A1C rows.

Rules, in order:
 1. Missing patient ID                      -> removed
 2. Patient Acct No columns disagree        -> removed
 3. Missing or invalid collection date      -> removed
 4. Result is not a plain number            -> removed (blank, comparator such as ">14.0",
                                               malformed number such as "6.3.", or text)
 5. Number is not a possible percent (<=0 or >100) -> removed
 6. Row is on the approved exclusion list    -> removed (reason required)
 7. Same patient, same date, same value      -> one copy kept (if collapse_identical_same_day)
 8. Same patient, same date, different values-> all held for review, unless one row is approved
 9. Value below review_low or above review_high -> kept, flagged for review

The source text of every flagged row stays in the review log for local review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .config import Settings

PLAIN_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*%?")
COMPARATOR = re.compile(r"(?:<=|>=|<|>|=<|=>)\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*%?")

REMOVE_RULES = [
    ("missing_id", "Missing patient ID", "Removed"),
    ("conflicting_id", "Patient Acct No columns disagree", "Removed"),
    ("invalid_date", "Missing or invalid collection date", "Removed"),
    ("blank_result", "Blank result", "Removed"),
    ("comparator_result", "Comparator result (for example >14.0)", "Removed"),
    ("malformed_number", "Malformed number (for example 6.3.)", "Removed"),
    ("text_result", "Text result (for example Clotted sample)", "Removed"),
    ("not_a_possible_percent", "Value 0 or less, or above 100", "Removed"),
    ("approved_exclusion", "On the approved exclusion list", "Removed"),
    ("identical_same_day_copy", "Identical same-day copy", "Removed (one copy kept)"),
    ("conflicting_same_day", "Different values on the same day", "Held for review"),
]
REVIEW_RULES = [
    ("unusual_low", "Value below the review range", "Kept, flagged for review"),
    ("unusual_high", "Value above the review range", "Kept, flagged for review"),
]


@dataclass
class CleanResult:
    measurements: pd.DataFrame   # kept results: patient_id, date, a1c, source_row
    review_log: pd.DataFrame     # PRIVATE: every flagged row with its source text
    rule_counts: pd.DataFrame    # rule, description, rows, action
    nonnumeric_text: pd.DataFrame
    unusual_values: list[float]
    rows_matched: int
    patients_matched: int
    warnings: list[str] = field(default_factory=list)

    @property
    def rows_kept(self) -> int:
        return len(self.measurements)

    @property
    def patients_kept(self) -> int:
        return int(self.measurements["patient_id"].nunique())


def classify_value(text) -> str:
    if text is None or pd.isna(text) or str(text).strip() == "":
        return "blank"
    text = str(text).strip()
    if PLAIN_NUMBER.fullmatch(text):
        return "number"
    if COMPARATOR.fullmatch(text):
        return "comparator"
    if re.search(r"\d", text):
        return "malformed"
    return "text"


def clean_a1c(rows: pd.DataFrame, settings: Settings) -> CleanResult:
    work = rows.copy()
    work["date"] = pd.to_datetime(work["date_text"], format="mixed", errors="coerce").dt.normalize()
    kind = work["value_text"].map(classify_value)
    number_text = work["value_text"].where(kind.eq("number")).astype("string")
    work["a1c"] = pd.to_numeric(number_text.str.replace("%", "", regex=False).str.strip(),
                                errors="coerce").astype("float64")

    flags = pd.DataFrame(index=work.index)
    flags["missing_id"] = work["patient_id"].isna()
    flags["conflicting_id"] = work["id_conflict"].astype(bool)
    flags["invalid_date"] = work["date"].isna()
    flags["blank_result"] = kind.eq("blank")
    flags["comparator_result"] = kind.eq("comparator")
    flags["malformed_number"] = kind.eq("malformed")
    flags["text_result"] = kind.eq("text")
    flags["not_a_possible_percent"] = (work["a1c"].le(0) | work["a1c"].gt(100)).fillna(False)
    flags["approved_exclusion"] = work["source_row"].isin(settings.excluded_source_rows)

    # Same-day groups are checked only among rows that passed rules 1-6.
    flags["identical_same_day_copy"] = False
    flags["conflicting_same_day"] = False
    passed = ~flags.any(axis=1)
    valid = work.loc[passed].sort_values(["patient_id", "date", "source_row"])
    warnings = []
    if not valid.empty:
        grp = valid.groupby(["patient_id", "date"])["a1c"]
        size, distinct = grp.transform("size"), grp.transform("nunique")
        later_copy = valid.duplicated(["patient_id", "date"], keep="first")
        identical = size.gt(1) & distinct.eq(1)
        conflicting = size.gt(1) & distinct.gt(1)
        if settings.collapse_identical_same_day:
            flags.loc[valid.index[identical & later_copy], "identical_same_day_copy"] = True
        else:
            conflicting = conflicting | identical
        approved = valid["source_row"].isin(settings.approved_keep_rows)
        group_key = valid["patient_id"].astype(str) + "|" + valid["date"].astype(str)
        # Without an approved row, all rows in the group are held.
        # With an approved row, that row is kept and the other rows are set aside.
        held = conflicting & ~approved
        flags.loc[valid.index[held], "conflicting_same_day"] = True
        too_many = (approved & conflicting).groupby(group_key).sum().gt(1)
        if too_many.any():
            raise ValueError("quality.approved_keep_rows lists more than one row for the same patient and date.")
        unused = set(settings.approved_keep_rows) - set(valid.loc[approved & conflicting, "source_row"])
        if unused:
            warnings.append(f"Approved rows {sorted(unused)} are not in a conflicting same-day group in this export. "
                            "Row numbers change with each export; check the approvals.")
    unknown_exclusions = set(settings.excluded_source_rows) - set(work["source_row"])
    if unknown_exclusions:
        warnings.append(f"Excluded rows {sorted(unknown_exclusions)} are not A1C rows in this export.")

    removed = flags.any(axis=1)
    flags["unusual_low"] = ~removed & work["a1c"].lt(settings.review_low)
    flags["unusual_high"] = ~removed & work["a1c"].gt(settings.review_high)

    kept = work.loc[~removed, ["patient_id", "date", "a1c", "source_row"]]
    kept = kept.sort_values(["patient_id", "date", "source_row"]).reset_index(drop=True)
    if kept.duplicated(["patient_id", "date"]).any():  # pragma: no cover - guarded above
        raise ValueError("A patient has more than one kept result on the same date.")

    review_log = work[["source_row", "patient_id", "date_text", "attribute", "order_name",
                       "order_status", "value_text"]].join(flags)
    review_log = review_log.loc[flags.any(axis=1)].reset_index(drop=True)

    rule_counts = pd.DataFrame(
        [{"rule": key, "description": desc, "rows": int(flags[key].sum()), "action": action}
         for key, desc, action in REMOVE_RULES + REVIEW_RULES])

    nonnumeric = (work.loc[kind.ne("number"), "value_text"].fillna("(blank)")
                  .value_counts().rename_axis("result_text").rename("rows").reset_index())
    unusual = sorted(work.loc[flags["unusual_low"] | flags["unusual_high"], "a1c"].tolist())

    numeric = kept["a1c"]
    if len(numeric) and not numeric.between(2, 25).all():
        warnings.append("Some kept values are outside 2 to 25. On a percent scale this is rare. "
                        "Check the units with the clinic.")
    if not settings.units_confirmed_by_clinic:
        warnings.append("The export has no unit column. The analysis assumes percent (NGSP); "
                        "the clinic has not confirmed this yet.")

    return CleanResult(
        measurements=kept,
        review_log=review_log,
        rule_counts=rule_counts,
        nonnumeric_text=nonnumeric,
        unusual_values=unusual,
        rows_matched=len(work),
        patients_matched=int(work["patient_id"].nunique()),
        warnings=warnings,
    )
