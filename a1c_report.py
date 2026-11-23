"""Make an A1C outcome report from a 5.02a export (or from synthetic demo data).

Examples:
    python a1c_report.py --demo --out outputs/demo_report
    python a1c_report.py --config config/a1c_settings.toml --out outputs/report_2026-11
    python a1c_report.py --input "data/5.02a - Lab Results Analysis Report.csv" \
        --start 2025-07-01 --end 2025-12-31 --baseline pre_window --out outputs/funder_2025H2
    python a1c_report.py --config config/a1c_settings.toml --shareable --out outputs/shareable

The report folder has report.html, tables/*.csv, settings_used.toml and run_info.json.
Row-level files (account numbers and dates) are written only with --row-level.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from a1c import config, synthetic
from a1c.loader import read_export
from a1c.pipeline import compare_with_502b, load_roster, run_pipeline
from a1c.report import build_report, write_bundle


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="A1C outcome report (eBO 5.02a export).")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--input", help="5.02a export file. Default: data.input_file in the settings file.")
    src.add_argument("--demo", action="store_true", help="Use SYNTHETIC demo data (no clinic data needed).")
    p.add_argument("--config", help="Settings file. Default: config/a1c_settings.toml, else the example file.")
    p.add_argument("--out", required=True, help="Output folder. Keep clinic outputs in the approved environment.")
    p.add_argument("--start", help="Window start, YYYY-MM-DD or 'auto'.")
    p.add_argument("--end", help="Window end, YYYY-MM-DD or 'auto'.")
    p.add_argument("--baseline", choices=sorted(config.BASELINE_MODES))
    p.add_argument("--lookback-days", type=int)
    p.add_argument("--cohort", choices=sorted(config.COHORT_MODES))
    p.add_argument("--subgroup-min", type=float, help="Lab subgroup: baseline A1C at or above this value.")
    p.add_argument("--control-threshold", type=float)
    p.add_argument("--control-operator", choices=list(config.CONTROL_OPERATORS))
    p.add_argument("--tolerance", type=float, help="Stability tolerance in percentage points.")
    p.add_argument("--roster", help="Eligible-patient roster CSV (column set by cohort.roster_id_column).")
    p.add_argument("--compare-502b", help="Optional 5.02b numeric-range extract to cross-check (internal only).")
    p.add_argument("--shareable", action="store_true", help="Apply the small-count rule and leave out patient-level charts.")
    p.add_argument("--row-level", action="store_true",
                   help="Also write PRIVATE row-level files. Not allowed with --shareable.")
    return p.parse_args(argv)


def _date(text):
    return None if text in (None, "auto") else dt.date.fromisoformat(text)


def main(argv=None) -> int:
    args = parse_args(argv)
    settings = config.load_settings(args.config) if args.config else config.load_settings()
    changes = {}
    if args.start is not None:
        changes["window_start"] = _date(args.start)
    if args.end is not None:
        changes["window_end"] = _date(args.end)
    for arg, attr in [("baseline", "baseline_mode"), ("lookback_days", "lookback_days"), ("cohort", "cohort_mode"),
                      ("subgroup_min", "subgroup_min_baseline"), ("control_threshold", "control_threshold"),
                      ("control_operator", "control_operator"), ("tolerance", "stability_tolerance")]:
        if getattr(args, arg) is not None:
            changes[attr] = getattr(args, arg)
    settings = settings.with_changes(**changes)
    config.check_settings(settings)
    if args.shareable and args.row_level:
        print("ERROR: --row-level cannot be used with --shareable.", file=sys.stderr)
        return 2

    if args.demo:
        source, name, synthetic_data = synthetic.generate_export(), "SYNTHETIC demo export (seed 2026)", True
    else:
        path = Path(args.input or settings.input_file)
        if not path.is_absolute() and not path.exists():
            path = config.PROJECT_DIR / path
        source, name, synthetic_data = path, path.name, False

    roster_path = args.roster or settings.roster_file
    roster = load_roster(Path(roster_path), settings) if roster_path else None
    result = run_pipeline(source, settings, synthetic=synthetic_data, source_name=name, roster_ids=roster)
    if args.compare_502b:
        result.comparison_502b = compare_with_502b(result, read_export(args.compare_502b))

    report = build_report(result, shareable=args.shareable)
    files = write_bundle(report, result, args.out, row_level=args.row_level)

    h, o = report.headline, result.outcomes
    print(report.label)
    for line in report.context_lines()[1:6]:
        print("  " + line)
    print(f"  A1C rows matched: {result.clean.rows_matched:,}; kept: {result.clean.rows_kept:,} "
          f"from {result.clean.patients_kept:,} patients")
    print(f"  Cohort: {h['cohort']:,} patients; paired: {h['paired']:,}")
    if not args.shareable:
        cat = o.categories.set_index("category")["patients"]
        print(f"  Improved / stable / worsened: {cat['Improved']} / {cat['Stable']} / {cat['Worsened']} "
              f"(of {h['paired']} paired)")
        print(f"  Latest result at target: {h['latest_at_target']} of {h['latest_den']}; "
              f"reached target after an above-target baseline: {h['reached']} of {h['above']}")
    for w in report.warnings:
        print(f"  WARNING: {w}")
    print(f"Wrote {len(files)} files to {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
