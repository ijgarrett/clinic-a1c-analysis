"""Analysis settings: load from a TOML file, validate, and write back out.

The settings file has sections ([data], [window], [cohort], [outcomes],
[quality], [disclosure]) and a list of PROVISIONAL settings that the clinic
has not approved yet. Every report shows that list.
"""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PROJECT_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = PROJECT_DIR / "config" / "a1c_settings.example.toml"
LOCAL_CONFIG = PROJECT_DIR / "config" / "a1c_settings.toml"

BASELINE_MODES = {
    "first_in_window": "First valid A1C inside the reporting window",
    "pre_window": "Latest valid A1C in the lookback period before the window starts",
}
COHORT_MODES = {
    "lab_subgroup": "Patients whose baseline A1C is at or above the subgroup value (lab-based, not a diagnosis)",
    "all_tested": "All patients with a baseline A1C",
}
CONTROL_OPERATORS = ("<", "<=")

# Attribute names that must never count as A1C.
NOT_A1C_LABELS = {"hemoglobin", "hgb", "est. average glucose", "estimated average glucose", "eag"}

# Settings file layout: section -> field names (same order as in the file).
SECTIONS = {
    "data": ["input_file", "a1c_labels", "id_column", "date_column", "attribute_column",
             "value_column", "order_name_column", "order_status_column",
             "assumed_units", "units_confirmed_by_clinic"],
    "window": ["start", "end", "baseline", "lookback_days"],
    "cohort": ["mode", "subgroup_min_baseline", "roster_file", "roster_id_column"],
    "outcomes": ["control_threshold", "control_operator", "stability_tolerance",
                 "baseline_group_cutpoints", "min_denominator", "km_min_at_risk", "km_checkpoints"],
    "quality": ["collapse_identical_same_day", "review_low", "review_high",
                "approved_keep_rows", "excluded_source_rows", "exclusion_reason"],
    "disclosure": ["min_cell_size", "rule_confirmed_by_clinic"],
}
# Field names in the file -> attribute names on Settings (when they differ).
FILE_TO_ATTR = {
    ("window", "start"): "window_start",
    ("window", "end"): "window_end",
    ("window", "baseline"): "baseline_mode",
    ("cohort", "mode"): "cohort_mode",
    ("disclosure", "rule_confirmed_by_clinic"): "disclosure_rule_confirmed",
}

DEFAULT_PROVISIONAL = [
    "data.units_confirmed_by_clinic",
    "window.start", "window.end", "window.baseline",
    "cohort.subgroup_min_baseline",
    "outcomes.control_threshold", "outcomes.control_operator", "outcomes.stability_tolerance",
    "outcomes.baseline_group_cutpoints",
    "quality.review_low", "quality.review_high",
    "disclosure.min_cell_size",
]

LABELS = {
    "input_file": "Export file",
    "a1c_labels": "A1C attribute names",
    "assumed_units": "Assumed units",
    "units_confirmed_by_clinic": "Units confirmed by clinic",
    "window_start": "Reporting window start",
    "window_end": "Reporting window end",
    "baseline_mode": "Baseline rule",
    "lookback_days": "Lookback before window (days)",
    "cohort_mode": "Cohort",
    "subgroup_min_baseline": "Subgroup: baseline A1C at or above (%)",
    "roster_file": "Eligible-patient roster",
    "control_threshold": "Control threshold (%)",
    "control_operator": "Control rule",
    "stability_tolerance": "Stability tolerance (percentage points)",
    "baseline_group_cutpoints": "Baseline group cutpoints (%)",
    "min_denominator": "Smallest denominator for a percentage",
    "km_min_at_risk": "Time-to-event curve stops below this many patients",
    "km_checkpoints": "Time-to-event checkpoints (days)",
    "collapse_identical_same_day": "Keep one copy of identical same-day results",
    "review_low": "Flag values below (%)",
    "review_high": "Flag values above (%)",
    "approved_keep_rows": "Approved rows to keep (conflicting same-day results)",
    "excluded_source_rows": "Approved excluded rows",
    "exclusion_reason": "Reason for excluded rows",
    "min_cell_size": "Small-count limit for shared outputs",
    "disclosure_rule_confirmed": "Disclosure rule confirmed by clinic",
}


@dataclass
class Settings:
    # [data]
    input_file: str = "data/5.02a - Lab Results Analysis Report.csv"
    a1c_labels: list[str] = field(default_factory=lambda: ["Hemoglobin A1c"])
    id_column: str = "patient_acct_no"
    date_column: str = "order_collection_performed_date"
    attribute_column: str = "lab_attribute"
    value_column: str = "lab_attribute_value"
    order_name_column: str = "order_name"
    order_status_column: str = "order_status"
    assumed_units: str = "percent (NGSP)"
    units_confirmed_by_clinic: bool = False
    # [window]
    window_start: dt.date | None = None   # None = earliest A1C date in the export
    window_end: dt.date | None = None     # None = latest A1C date in the export
    baseline_mode: str = "first_in_window"
    lookback_days: int = 365
    # [cohort]
    cohort_mode: str = "lab_subgroup"
    subgroup_min_baseline: float = 6.5
    roster_file: str = ""
    roster_id_column: str = "patient_id"
    # [outcomes]
    control_threshold: float = 7.0
    control_operator: str = "<"
    stability_tolerance: float = 0.5
    baseline_group_cutpoints: list[float] = field(default_factory=lambda: [5.7, 6.5, 8.0, 10.0])
    min_denominator: int = 10
    km_min_at_risk: int = 10
    km_checkpoints: list[int] = field(default_factory=lambda: [180, 365])
    # [quality]
    collapse_identical_same_day: bool = True
    review_low: float = 4.0
    review_high: float = 15.0
    approved_keep_rows: list[int] = field(default_factory=list)
    excluded_source_rows: list[int] = field(default_factory=list)
    exclusion_reason: str = ""
    # [disclosure]
    min_cell_size: int = 11
    disclosure_rule_confirmed: bool = False
    # list of "section.name" keys that still need clinic approval
    provisional: list[str] = field(default_factory=lambda: list(DEFAULT_PROVISIONAL))

    def with_changes(self, **changes) -> "Settings":
        return replace(self, **changes)

    def is_provisional(self, attr: str) -> bool:
        return attr_to_key(attr) in self.provisional


def attr_to_key(attr: str) -> str:
    for (section, name), mapped in FILE_TO_ATTR.items():
        if mapped == attr:
            return f"{section}.{name}"
    for section, names in SECTIONS.items():
        if attr in names:
            return f"{section}.{attr}"
    return attr


def _parse_date(value, name):
    if value in (None, "", "auto"):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must be a date like 2025-01-31 or \"auto\".") from exc


def default_config_path() -> Path:
    return LOCAL_CONFIG if LOCAL_CONFIG.exists() else EXAMPLE_CONFIG


def load_settings(path: str | Path | None = None) -> Settings:
    """Read a settings file. Missing keys keep their defaults."""
    path = Path(path) if path else default_config_path()
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    values = {}
    known = {f.name for f in fields(Settings)}
    for section, names in SECTIONS.items():
        block = data.get(section, {})
        unknown = set(block) - set(names)
        if unknown:
            raise ValueError(f"Unknown setting(s) in [{section}]: {sorted(unknown)}")
        for name in names:
            if name in block:
                values[FILE_TO_ATTR.get((section, name), name)] = block[name]
    if "provisional" in data:
        values["provisional"] = list(data["provisional"].get("settings", []))
    settings = Settings(**{k: v for k, v in values.items() if k in known})
    settings.window_start = _parse_date(settings.window_start, "window.start")
    settings.window_end = _parse_date(settings.window_end, "window.end")
    check_settings(settings)
    return settings


def check_settings(s: Settings) -> list[str]:
    """Raise ValueError for settings that cannot work. Return warnings."""
    errors, warnings = [], []
    if s.baseline_mode not in BASELINE_MODES:
        errors.append(f"window.baseline must be one of {list(BASELINE_MODES)}.")
    if s.cohort_mode not in COHORT_MODES:
        errors.append(f"cohort.mode must be one of {list(COHORT_MODES)}.")
    if s.control_operator not in CONTROL_OPERATORS:
        errors.append("outcomes.control_operator must be \"<\" or \"<=\".")
    if s.stability_tolerance < 0:
        errors.append("outcomes.stability_tolerance must be 0 or more.")
    cuts = list(s.baseline_group_cutpoints)
    if any(b <= a for a, b in zip(cuts, cuts[1:])):
        errors.append("outcomes.baseline_group_cutpoints must increase (for example 5.7, 6.5, 8.0, 10.0).")
    if s.lookback_days <= 0:
        errors.append("window.lookback_days must be more than 0.")
    if s.window_start and s.window_end and s.window_start > s.window_end:
        errors.append("window.start must be on or before window.end.")
    if s.min_denominator < 1 or s.km_min_at_risk < 1 or s.min_cell_size < 1:
        errors.append("min_denominator, km_min_at_risk and min_cell_size must be 1 or more.")
    if s.review_low >= s.review_high:
        errors.append("quality.review_low must be less than quality.review_high.")
    if s.excluded_source_rows and not s.exclusion_reason.strip():
        errors.append("Write the reason for excluded rows in quality.exclusion_reason.")
    if not s.a1c_labels:
        errors.append("data.a1c_labels must list at least one A1C attribute name.")
    bad = [x for x in s.a1c_labels if x.strip().casefold() in NOT_A1C_LABELS]
    if bad:
        errors.append(f"These names are not A1C tests and cannot be A1C labels: {bad}")
    if "percent" not in s.assumed_units.lower():
        errors.append("This version supports A1C in percent (NGSP) only. Set data.assumed_units to \"percent (NGSP)\".")
    if errors:
        raise ValueError(" ".join(errors))
    if s.approved_keep_rows or s.excluded_source_rows:
        warnings.append("Approved row numbers apply to one export file only. Check them after each new export.")
    return warnings


def describe_operator(s: Settings) -> str:
    return f"below {s.control_threshold:g}%" if s.control_operator == "<" else f"at or below {s.control_threshold:g}%"


def meets_target(values, s: Settings):
    """Element-wise control test for a pandas Series or a number."""
    return values < s.control_threshold if s.control_operator == "<" else values <= s.control_threshold


def group_labels(cutpoints) -> list[str]:
    cuts = [float(c) for c in cutpoints]
    if not cuts:
        return ["All values"]
    labels = [f"Below {cuts[0]:g}"]
    labels += [f"{a:g} to below {b:g}" for a, b in zip(cuts, cuts[1:])]
    labels.append(f"{cuts[-1]:g} or higher")
    return labels


def settings_table(s: Settings) -> list[dict]:
    """Rows for display: setting, value, status."""
    rows = []
    for section, names in SECTIONS.items():
        for name in names:
            attr = FILE_TO_ATTR.get((section, name), name)
            if attr in {"id_column", "date_column", "attribute_column", "value_column",
                        "order_name_column", "order_status_column", "roster_id_column"}:
                continue
            value = getattr(s, attr)
            if attr == "window_start" and value is None:
                value = "auto (earliest A1C in export)"
            elif attr == "window_end" and value is None:
                value = "auto (latest A1C in export)"
            elif attr == "baseline_mode":
                value = f"{value}: {BASELINE_MODES[value]}"
            elif attr == "cohort_mode":
                value = f"{value}: {COHORT_MODES[value]}"
            elif isinstance(value, list):
                value = ", ".join(str(v) for v in value) or "(none)"
            elif value == "":
                value = "(none)"
            key = f"{section}.{name}"
            rows.append({
                "Setting": LABELS.get(attr, attr),
                "Key": key,
                "Value": str(value),
                "Status": "PROVISIONAL" if key in s.provisional else "Approved / fixed",
            })
    return rows


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    if value is None:
        return '"auto"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def to_toml(s: Settings, header: str = "") -> str:
    """Write settings as a TOML file that load_settings() can read."""
    lines = ["# A1C outcome settings"]
    if header:
        lines += [f"# {line}" for line in header.splitlines()]
    lines.append("# Keys listed under [provisional] still need clinic approval.")
    for section, names in SECTIONS.items():
        lines += ["", f"[{section}]"]
        for name in names:
            attr = FILE_TO_ATTR.get((section, name), name)
            lines.append(f"{name} = {_toml_value(getattr(s, attr))}")
    lines += ["", "[provisional]", f"settings = {_toml_value(s.provisional)}", ""]
    return "\n".join(lines)


def as_dict(s: Settings) -> dict:
    out = asdict(s)
    for key in ("window_start", "window_end"):
        out[key] = out[key].isoformat() if out[key] else "auto"
    return out
