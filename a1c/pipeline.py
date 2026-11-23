"""Run the whole analysis: read -> select A1C rows -> clean -> outcomes."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .cleaning import CleanResult, clean_a1c
from .config import Settings, check_settings
from .loader import A1CRows, Export, normalized_name, read_export, select_a1c
from .outcomes import Outcomes, analyze

SYNTHETIC_LABEL = "SYNTHETIC DEMO DATA - not real patients"
CLINIC_LABEL = "CLINIC DATA - INTERNAL REVIEW ONLY"


@dataclass
class PipelineResult:
    settings: Settings
    export: Export
    a1c: A1CRows
    clean: CleanResult
    outcomes: Outcomes
    synthetic: bool
    data_label: str
    generated_at: str
    warnings: list[str] = field(default_factory=list)
    comparison_502b: pd.DataFrame | None = None


def load_roster(source: str | Path | bytes, settings: Settings, name: str | None = None) -> set[str]:
    """Read an eligible-patient roster (CSV with one ID column)."""
    roster = read_export(source, name=name or "roster")
    column = normalized_name(settings.roster_id_column)
    if column not in roster.frame.columns:
        raise ValueError(f"The roster has no '{settings.roster_id_column}' column. "
                         f"Columns found: {list(roster.frame.columns)}")
    ids = roster.frame[column].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    return set(ids.dropna()) - {""}


def run_pipeline(source: str | Path | bytes, settings: Settings, *, synthetic: bool = False,
                 source_name: str | None = None, roster_ids: set[str] | None = None,
                 export: Export | None = None) -> PipelineResult:
    warnings = check_settings(settings)
    export = export or read_export(source, name=source_name)
    a1c = select_a1c(export, settings)
    clean = clean_a1c(a1c.rows, settings)
    outcomes = analyze(clean.measurements, settings, roster_ids=roster_ids)
    warnings = list(dict.fromkeys(warnings + a1c.warnings + clean.warnings + outcomes.notes))
    return PipelineResult(
        settings=settings,
        export=export,
        a1c=a1c,
        clean=clean,
        outcomes=outcomes,
        synthetic=synthetic,
        data_label=SYNTHETIC_LABEL if synthetic else CLINIC_LABEL,
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        warnings=warnings,
    )


def compare_with_502b(result: PipelineResult, export_b: Export) -> pd.DataFrame:
    """Check that the 5.02b numeric-range extract is a subset of 5.02a.

    5.02b was run with a numeric range (it held only A1C values of 10 or more),
    so it is a comparison source only. Keys are (patient, date, value text).
    """
    s = result.settings
    b = select_a1c(export_b, s).rows
    a = result.a1c.rows

    def keys(frame):
        return set(zip(frame["patient_id"], frame["date_text"], frame["value_text"]))

    a_keys, b_keys = keys(a), keys(b)
    a_value = pd.to_numeric(a["value_text"], errors="coerce")
    a_date = pd.to_datetime(a["date_text"], errors="coerce")
    b_date = pd.to_datetime(b["date_text"], errors="coerce")
    b_value = pd.to_numeric(b["value_text"], errors="coerce")
    low = b_value.min() if len(b) else float("nan")
    last_b = b_date.max() if len(b) else pd.NaT
    a_high = keys(a[a_value.ge(low) & a_date.le(last_b)]) if len(b) else set()
    missing = sorted(float(k[2]) for k in a_high - b_keys)
    rows = [
        ("5.02b A1C rows", len(b)),
        ("5.02b distinct results (patient, date, value)", len(b_keys)),
        ("...of these, also in 5.02a", len(b_keys & a_keys)),
        ("5.02b lowest and highest value", f"{low:g} to {b_value.max():g}" if len(b) else "n/a"),
        ("5.02b first and last date", f"{b_date.min().date()} to {last_b.date()}" if len(b) else "n/a"),
        ("5.02a distinct results in that value range up to the 5.02b last date", len(a_high)),
        ("...of these, missing from 5.02b", len(missing)),
        ("Values missing from 5.02b", ", ".join(f"{v:g}" for v in missing) or "none"),
    ]
    return pd.DataFrame(rows, columns=["check", "result"])
