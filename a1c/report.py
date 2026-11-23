"""Report tables, HTML report and export bundle.

build_report() makes every table that the dashboard, the HTML report and the
CSV export show. Thus all three always agree. With shareable=True, the small-
count rule in disclosure.py is applied and the patient-level charts are left out.
"""

from __future__ import annotations

import html
import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd

from . import __version__, charts
from .config import (LABELS, as_dict, attr_to_key, describe_operator, group_labels, settings_table,
                     to_toml)
from .disclosure import primary, suppress_chain, suppress_partition
from .pipeline import PipelineResult

NA = "n/a"


@dataclass
class Table:
    key: str
    title: str
    frame: pd.DataFrame
    note: str = ""


@dataclass
class Report:
    label: str
    shareable: bool
    k: int
    context: pd.DataFrame
    tables: dict[str, Table]
    charts: dict[str, object]
    warnings: list[str] = field(default_factory=list)
    headline: dict = field(default_factory=dict)

    def context_lines(self) -> list[str]:
        return [f"{r.item}: {r.value}" for r in self.context.itertuples()]


def _n(value, hide=False, k=11):
    if value is None or (isinstance(value, float) and np.isnan(value)) or pd.isna(value):
        return NA
    return f"<{k}" if hide else f"{int(value):,}"


def _pct(num, den, hide=False):
    if hide:
        return "suppressed"
    if den is None or pd.isna(den) or den == 0 or pd.isna(num):
        return NA
    return f"{100 * num / den:.1f}%"


def _num(value, digits=2, hide=False, signed=False):
    if hide:
        return "suppressed"
    if value is None or pd.isna(value):
        return NA
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"


def provisional_labels(result: PipelineResult) -> list[str]:
    s = result.settings
    out = []
    for key in s.provisional:
        attr = next((a for a in LABELS if attr_to_key(a) == key), key)
        out.append(LABELS.get(attr, key))
    return out


def build_context(result: PipelineResult, shareable: bool) -> tuple[str, pd.DataFrame]:
    s, o = result.settings, result.outcomes
    k = s.min_cell_size
    if result.synthetic:
        label = "SYNTHETIC DEMO DATA - not real patients"
    elif shareable:
        label = (f"CLINIC DATA - SMALL COUNTS SUPPRESSED (provisional rule: counts below {k} hidden). "
                 "The clinic must approve this output before it is shared.")
    else:
        label = "CLINIC DATA - INTERNAL REVIEW ONLY. Small counts are not suppressed. Do not share outside the approved environment."
    rows = [
        ("Report", label),
        ("Source file", f"{result.export.name} (SHA-256 {result.export.sha256[:16]})"),
        ("Reporting window", f"{o.window.start.date()} to {o.window.end.date()} (both dates included)"),
        ("Baseline rule", f"{s.baseline_mode}: {o.window.baseline_rule()}"),
        ("Cohort", o.cohort_label),
        ("Control target", f"A1C {describe_operator(s)}"),
        ("Stability tolerance", f"{s.stability_tolerance:g} percentage points "
                                f"(a change of exactly +/-{s.stability_tolerance:g} counts as stable)"),
        ("Baseline groups", "; ".join(group_labels(s.baseline_group_cutpoints))),
        ("Units", f"{s.assumed_units}; " + ("confirmed by the clinic" if s.units_confirmed_by_clinic
                                            else "assumed, not yet confirmed by the clinic")),
        ("PROVISIONAL settings", "; ".join(provisional_labels(result)) or "none"),
        ("Small-count rule", (f"Applied: counts from 1 to {k - 1} are hidden (provisional rule)" if shareable
                              else "Not applied (internal review)")),
        ("Generated", f"{result.generated_at} by a1c version {__version__}"),
    ]
    return label, pd.DataFrame(rows, columns=["item", "value"])


def build_report(result: PipelineResult, shareable: bool = False) -> Report:
    s, o, c = result.settings, result.outcomes, result.clean
    k = s.min_cell_size
    sh = shareable
    label, context = build_context(result, shareable)
    tables: dict[str, Table] = {}

    def add(key, title, frame, note=""):
        tables[key] = Table(key, title, frame.reset_index(drop=True), note)

    # Patient flow
    f = o.funnel
    fmask = suppress_chain(list(f["patients"]), k) if sh else [False] * len(f)
    add("patient_flow", "Patient flow", pd.DataFrame({
        "Step": f["step"], "Patients": [_n(v, h, k) for v, h in zip(f["patients"], fmask)]}),
        "Each step is a subset of the step above it.")
    cohort_n = int(f["patients"].iloc[-2])
    paired_n = int(f["patients"].iloc[-1])
    cohort_hidden, paired_hidden = fmask[-2], fmask[-1]

    # 1. Improved / stable / worsened
    cat = o.categories
    cmask = suppress_partition(list(cat["patients"]), k, total=cohort_n) if sh else [False] * len(cat)
    cat_hidden = dict(zip(cat["category"], cmask))
    rows = []
    for r, hide in zip(cat.itertuples(), cmask):
        den_hidden = sh and ((paired_hidden if r.category != "No follow-up" else cohort_hidden) or primary(r.denominator, k))
        rows.append({"Outcome": r.category, "Patients": _n(r.patients, hide, k),
                     "Percent": _pct(r.patients, r.denominator, hide or den_hidden),
                     "Denominator": "suppressed" if den_hidden else _n(r.denominator),
                     "Rule": r.rule})
    add("outcome_categories", "1. Improved, stable and worsened", pd.DataFrame(rows),
        "Improved, stable and worsened use paired patients as the denominator. "
        "'No follow-up' uses all cohort patients and is not part of the three outcome percentages.")

    # 2. Control
    p = o.patients
    paired = p[p["paired"]]
    above = p[~p["baseline_at_target"]]
    win = p[p["latest_a1c"].notna()]
    reached = int(above["reached_target_later"].sum())
    no_later = int(above["later_results"].eq(0).sum())
    later_not = len(above) - reached - no_later
    if sh:
        p1 = suppress_partition([int(win["latest_at_target"].sum()), int((~win["latest_at_target"]).sum())], k)
        p2 = suppress_partition([int(paired["latest_at_target"].sum()), int((~paired["latest_at_target"]).sum())], k)
        p3 = suppress_partition([reached, later_not, no_later], k)
        p4 = suppress_partition([int(p["baseline_at_target"].sum()), len(above)], k, total=cohort_n)
    else:
        p1 = p2 = [False, False]
        p3 = [False, False, False]
        p4 = [False, False]
    den_hidden = {
        0: sh and (primary(len(win), k) or (len(win) == cohort_n and cohort_hidden)),
        1: sh and paired_hidden,
        2: p4[1],
        3: sh and (p3[0] or p3[1]),
        4: p4[1],
        5: sh and cohort_hidden,
    }
    num_hidden = {0: p1[0], 1: p2[0], 2: p3[0], 3: p3[0], 4: p3[2], 5: p4[0]}
    rows = []
    for i, r in enumerate(o.control.itertuples()):
        rows.append({"Measure": r.measure, "Patients": _n(r.numerator, num_hidden[i], k),
                     "Denominator": "suppressed" if den_hidden[i] else _n(r.denominator),
                     "Percent": _pct(r.numerator, r.denominator, num_hidden[i] or den_hidden[i]),
                     "Note": r.note})
    add("control", "2. Control", pd.DataFrame(rows),
        "The 'reached target' rows describe first documented control. "
        "Patients whose baseline was already at target are not in those denominators.")

    # 3. Magnitude
    hide_n = [paired_hidden, cat_hidden.get("Improved", False), cat_hidden.get("Worsened", False)]
    rows = []
    for r, hn in zip(o.magnitude.itertuples(), hide_n):
        hide_stats = sh and (hn or r.patients < k)
        rows.append({"Measure": r.measure, "Patients": _n(r.patients, sh and hn, k),
                     "Median (points)": _num(r.median_pp, 2, hide_stats),
                     "25th percentile": _num(r.q1_pp, 2, hide_stats),
                     "75th percentile": _num(r.q3_pp, 2, hide_stats), "Note": r.note})
    add("magnitude", "3. Size of the change", pd.DataFrame(rows),
        "Each patient's change is calculated first (follow-up minus baseline). The summaries use those values.")

    # 4. Time to first documented control
    days = above.loc[above["reached_target_later"], "days_to_control"]
    with_later = len(above) - no_later
    med_days = days.median() if len(days) else np.nan
    q1d, q3d = (days.quantile(0.25), days.quantile(0.75)) if len(days) else (np.nan, np.nan)
    fu = above.loc[above["later_results"].gt(0), "followup_days"]
    hide_with_later = sh and (p3[2] or primary(with_later, k))
    hide_days = sh and (p3[0] or len(days) < k)
    rows = [
        {"Measure": "Patients with an above-target baseline", "Value": _n(len(above), p4[1], k),
         "Denominator": "", "Percent": "", "Note": "Starting population."},
        {"Measure": "With at least one later result (follow-up coverage)", "Value": _n(with_later, hide_with_later, k),
         "Denominator": _n(len(above), p4[1], k), "Percent": _pct(with_later, len(above), hide_with_later or p4[1]),
         "Note": "Only these patients can show control."},
        {"Measure": "Median follow-up of those patients (days)",
         "Value": _num(fu.median() if len(fu) else np.nan, 0, sh and len(fu) < k), "Denominator": "", "Percent": "",
         "Note": "Days from baseline to the last result inside the window."},
        {"Measure": "Reached first documented control", "Value": _n(reached, p3[0], k),
         "Denominator": _n(len(above), p4[1], k), "Percent": _pct(reached, len(above), p3[0] or p4[1]),
         "Note": "First later result at target."},
        {"Measure": "Median days to first documented control (only patients who reached it)",
         "Value": _num(med_days, 0, hide_days), "Denominator": "", "Percent": "",
         "Note": ("Not shown: too few patients." if hide_days else
                  f"Describes only the {len(days)} patients who reached control "
                  f"(middle half: {_num(q1d, 0)} to {_num(q3d, 0)} days). It is not a median for all patients.")},
    ]
    add("time_to_control", "4. Time to first documented control", pd.DataFrame(rows),
        "Control is seen only on test dates. The true date can be earlier than the test that shows it.")
    min_followed = max(s.km_min_at_risk, k if sh else 1)
    rows = []
    for r in o.km_checkpoints.itertuples():
        show = r.still_followed >= min_followed
        rows.append({"Day": r.day, "Estimated percent with documented control":
                     _num(r.pct_reached, 1) + "%" if show and pd.notna(r.pct_reached) else "Not shown: too few still followed",
                     "Patients still followed": _n(r.still_followed, sh and primary(r.still_followed, k), k)})
    add("time_to_control_checkpoints", "4b. Time-to-event estimate at checkpoints (exploratory)",
        pd.DataFrame(rows, columns=["Day", "Estimated percent with documented control", "Patients still followed"]),
        "Kaplan-Meier estimate. Patients without control are censored at their last result inside the window. "
        f"Estimates are not shown when fewer than {min_followed} patients are still followed.")

    # 5. By starting A1C group
    g = o.by_group
    if sh:
        base_mask = suppress_partition(list(g["baseline_patients"]), k, total=cohort_n)
        pair_mask = suppress_partition(list(g["paired_patients"]), k, total=paired_n)
    else:
        base_mask = pair_mask = [False] * len(g)
    rows, chart_ok = [], []
    for i, r in enumerate(g.itertuples()):
        cats = [r.improved, r.stable, r.worsened]
        cm = suppress_partition(cats, k, total=r.paired_patients) if sh else [False] * 3
        enough = r.paired_patients >= max(s.min_denominator, k if sh else 1)
        hide_stats = sh and (pair_mask[i] or r.paired_patients < k)
        chart_ok.append(enough and not any(cm) and not pair_mask[i])

        def cat_text(n, hide):
            if hide:
                return f"<{k}"
            return f"{n} ({100 * n / r.paired_patients:.1f}%)" if enough else (f"{n}" if not sh else "not shown")
        rows.append({
            "Baseline group (%)": r.baseline_group,
            "Baseline patients": _n(r.baseline_patients, base_mask[i], k),
            "Paired patients": _n(r.paired_patients, pair_mask[i], k),
            "Follow-up coverage": _pct(r.paired_patients, r.baseline_patients, base_mask[i] or pair_mask[i]),
            "Median follow-up (days)": _num(r.median_followup_days, 0, hide_stats),
            "Median change (points)": _num(r.median_change_pp, 2, hide_stats, signed=True),
            "Middle half (points)": NA if hide_stats or pd.isna(r.q1_pp) else f"{r.q1_pp:+.2f} to {r.q3_pp:+.2f}",
            "Improved": cat_text(r.improved, cm[0]),
            "Stable": cat_text(r.stable, cm[1]),
            "Worsened": cat_text(r.worsened, cm[2]),
            "Latest at target": (_n(r.latest_at_target, sh and primary(r.latest_at_target, k), k)
                                 + (f" ({r.latest_at_target_pct:.1f}%)" if pd.notna(r.latest_at_target_pct)
                                    and not (sh and primary(r.latest_at_target, k)) else "")),
            "Note": r.note,
        })
    add("by_baseline_group", "5. Outcomes by starting A1C", pd.DataFrame(rows),
        f"Percentages are shown only for groups with {max(s.min_denominator, k if sh else 1)} or more paired patients. "
        "Groups differ in follow-up length. Patients who start high tend to come down on the next test "
        "(regression to the mean), so part of their decrease is expected without any change in care.")

    # Testing volume
    t = o.tests_per_year
    add("tests_per_year", "A1C testing inside the window", pd.DataFrame({
        "Year": t["year"].astype(str),
        "A1C results": [_n(v, sh and primary(v, k), k) for v in t["a1c_results"]],
        "Patients tested": [_n(v, sh and primary(v, k), k) for v in t["patients_tested"]],
        "Months of the year inside the window": t["months_in_window"]}),
        "All tested patients, not only the cohort.")
    tp = o.tests_per_patient
    tmask = suppress_partition(list(tp["patients"]), k) if sh and len(tp) else [False] * len(tp)
    add("tests_per_patient", "Results per patient inside the window", pd.DataFrame({
        "Results in window": tp["results_in_window"].astype(str),
        "Patients": [_n(v, h, k) for v, h in zip(tp["patients"], tmask)],
        "Percent": [_pct(v, tp["patients"].sum(), h) for v, h in zip(tp["patients"], tmask)]}))

    # Data quality
    rc = c.rule_counts
    summary = pd.DataFrame([
        {"Rule": "Rows in the export (all lab tests)", "Rows": _n(result.a1c.total_rows), "Action": ""},
        {"Rule": "Rows that match the A1C labels", "Rows": _n(c.rows_matched), "Action": ""},
        {"Rule": "A1C results kept for analysis", "Rows": _n(c.rows_kept), "Action": "Kept"},
        {"Rule": "A1C results not used", "Rows": _n(c.rows_matched - c.rows_kept), "Action": ""},
        {"Rule": "Kept results after the report end", "Rows": _n(o.results_after_end),
         "Action": "Not used in this report"},
    ])
    rules = pd.DataFrame({"Rule": rc["description"],
                          "Rows": [_n(v, sh and primary(v, k), k) for v in rc["rows"]],
                          "Action": rc["action"]})
    add("data_quality", "Data quality", pd.concat([summary, rules], ignore_index=True),
        "A row can have more than one problem, so the rule counts can overlap.")
    la = result.a1c.label_audit
    add("label_audit", "A1C label check", pd.DataFrame({
        "Lab attribute": la["lab_attribute"], "Order name": la["order_name"],
        "Rows": [_n(v, sh and primary(v, k), k) for v in la["rows"]],
        "Used as A1C": np.where(la["kept_as_a1c"], "Yes", "No")}),
        "Exact, case-insensitive match on Lab Attribute. Est. Average Glucose is calculated from the A1C and "
        "is not used. CBC hemoglobin is a different test.")
    if not sh:
        add("nonnumeric_results", "Results that are not plain numbers (internal)", c.nonnumeric_text.rename(
            columns={"result_text": "Result text", "rows": "Rows"}))
        add("unusual_values", "Kept values outside the review range (internal)", pd.DataFrame({
            "Value (%)": c.unusual_values}),
            f"Kept in the analysis. Check them in the source record. Review range: {s.review_low:g} to {s.review_high:g}.")
        if result.comparison_502b is not None:
            add("comparison_502b", "Comparison with the 5.02b numeric-range extract (internal)", result.comparison_502b.rename(
                columns={"check": "Check", "result": "Result"}))
        if o.roster is not None:
            add("roster", "Eligible-patient roster", pd.DataFrame(
                [(kk.replace("_", " ").capitalize(), vv) for kk, vv in o.roster.items()], columns=["Item", "Patients"]))
    elif o.roster is not None:
        add("roster", "Eligible-patient roster", pd.DataFrame(
            [(kk.replace("_", " ").capitalize(), _n(vv, primary(vv, k), k)) for kk, vv in o.roster.items()],
            columns=["Item", "Patients"]))
    add("settings", "Active settings", pd.DataFrame(settings_table(s)))

    # Charts
    chart_set = {
        "tests_per_year": charts.tests_per_year_chart(t) if not (sh and any(primary(v, k) for v in t["a1c_results"])) else None,
        "outcomes": charts.outcome_bars(o.categories, hide={kk for kk, vv in cat_hidden.items() if vv}) if not paired_hidden else None,
        "group_change": charts.group_change_chart(g if not sh else g[[not m and n >= k for m, n in zip(pair_mask, g["paired_patients"])]],
                                                  s.stability_tolerance),
        "group_outcomes": charts.group_outcome_chart(g[chart_ok], max(s.min_denominator, k if sh else 1)),
    }
    if not sh:
        chart_set["change_histogram"] = charts.change_histogram(o.paired, s.stability_tolerance)
        chart_set["time_to_control"] = charts.time_to_control_curve(o.km_curve, o.km_checkpoints, describe_operator(s),
                                                                    s.km_min_at_risk)
        chart_set["days_to_control"] = charts.days_to_control_chart(days)

    cats = o.categories.set_index("category")
    ctl = o.control.set_index("measure")
    headline = {
        "cohort": cohort_n, "paired": paired_n,
        "improved": int(cats.loc["Improved", "patients"]),
        "latest_at_target": int(ctl.iloc[0]["numerator"]), "latest_den": int(ctl.iloc[0]["denominator"]),
        "reached": int(ctl.iloc[2]["numerator"]), "above": int(ctl.iloc[2]["denominator"]),
        "median_change": o.magnitude.iloc[0]["median_pp"],
        "hidden": {"cohort": cohort_hidden, "paired": paired_hidden, "improved": cat_hidden.get("Improved", False),
                   "latest": p1[0], "reached": p3[0], "above": p4[1]},
    }
    return Report(label, shareable, k, context, tables, chart_set, list(result.warnings), headline)


# ---------------------------------------------------------------- output files

def _csv_with_context(report: Report, table: Table) -> str:
    lines = [f"# A1C outcome report - {table.title}"] + [f"# {line}" for line in report.context_lines()]
    if table.note:
        lines.append(f"# Note: {table.note}")
    return "\n".join(lines) + "\n" + table.frame.to_csv(index=False)


SECTIONS_HTML = [
    ("Patient flow", ["patient_flow"], []),
    ("1. Improved, stable and worsened", ["outcome_categories"], ["outcomes", "change_histogram"]),
    ("2. Control", ["control"], []),
    ("3. Size of the change", ["magnitude"], []),
    ("4. Time to first documented control", ["time_to_control", "time_to_control_checkpoints"],
     ["time_to_control", "days_to_control"]),
    ("5. Outcomes by starting A1C", ["by_baseline_group"], ["group_change", "group_outcomes"]),
    ("A1C testing", ["tests_per_year", "tests_per_patient"], ["tests_per_year"]),
    ("Data quality", ["data_quality", "label_audit", "nonnumeric_results", "unusual_values", "comparison_502b", "roster"], []),
    ("Settings", ["settings"], []),
]


def render_html(report: Report) -> str:
    esc = html.escape
    specs, parts = [], []
    banner_class = "synthetic" if report.label.startswith("SYNTHETIC") else ("shareable" if report.shareable else "internal")
    parts.append(f'<div class="banner {banner_class}">{esc(report.label)}</div>')
    parts.append("<h1>A1C outcome report</h1>")
    parts.append(report.context.rename(columns={"item": "Item", "value": "Value"})
                 .to_html(index=False, classes="context", escape=True, border=0))
    if report.warnings:
        parts.append("<h2>Warnings</h2><ul>" + "".join(f"<li>{esc(w)}</li>" for w in report.warnings) + "</ul>")
    for heading, table_keys, chart_keys in SECTIONS_HTML:
        body = []
        for ck in chart_keys:
            chart = report.charts.get(ck)
            if chart is not None:
                specs.append(chart.to_dict())
                body.append(f'<div class="chart" id="chart{len(specs) - 1}"></div>')
        for tk in table_keys:
            t = report.tables.get(tk)
            if t is None:
                continue
            body.append(f"<h3>{esc(t.title)}</h3>")
            body.append(t.frame.to_html(index=False, escape=True, border=0, na_rep=NA))
            if t.note:
                body.append(f'<p class="note">{esc(t.note)}</p>')
        if body:
            parts.append(f"<section><h2>{esc(heading)}</h2>{''.join(body)}</section>")
    parts.append('<p class="note">Methods: see docs/METHODS.md in the project. Observed changes do not show '
                 "that clinic care caused them.</p>")
    vega = f"https://cdn.jsdelivr.net/npm/vega@{alt.VEGA_VERSION}"
    vegalite = f"https://cdn.jsdelivr.net/npm/vega-lite@{alt.VEGALITE_VERSION}"
    embed = f"https://cdn.jsdelivr.net/npm/vega-embed@{alt.VEGAEMBED_VERSION}"
    script = (f'<script src="{vega}"></script><script src="{vegalite}"></script><script src="{embed}"></script>'
              f"<script>const specs = {json.dumps(specs)};"
              "specs.forEach((s, i) => vegaEmbed('#chart' + i, s, {actions: false}).catch(() => {"
              "document.getElementById('chart' + i).textContent = 'Chart needs an internet connection to draw. The table has the same numbers.';}));"
              "</script>")
    style = """
    body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#0b0b0b;background:#f9f9f7;margin:0;padding:24px;max-width:1100px;margin:auto}
    h1{font-size:26px;margin:16px 0}h2{font-size:20px;margin-top:32px;border-top:1px solid #e1e0d9;padding-top:16px}h3{font-size:15px;margin:20px 0 6px}
    table{border-collapse:collapse;width:100%;font-size:13px;background:#fcfcfb;margin-bottom:6px}
    th,td{border-bottom:1px solid #e1e0d9;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f0efec}
    td{font-variant-numeric:tabular-nums}.note{color:#52514e;font-size:13px}
    .banner{padding:10px 14px;font-weight:600;border-radius:6px}
    .synthetic{background:#e8f1fc;color:#104281}.internal{background:#fdebe3;color:#8a2c07}.shareable{background:#eef6ee;color:#1f5f1f}
    .chart{width:100%;margin:12px 0;background:#fcfcfb}
    """
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            f"content=\"width=device-width, initial-scale=1\"><title>A1C outcome report</title><style>{style}</style>"
            f"</head><body>{''.join(parts)}{script}</body></html>")


def run_info(report: Report, result: PipelineResult) -> dict:
    o = result.outcomes
    return {
        "label": report.label,
        "shareable": report.shareable,
        "small_count_limit": report.k if report.shareable else None,
        "generated_at": result.generated_at,
        "a1c_version": __version__,
        "source_file": result.export.name,
        "source_sha256": result.export.sha256,
        "window_start": str(o.window.start.date()),
        "window_end": str(o.window.end.date()),
        "baseline_rule": o.window.baseline_rule(),
        "cohort": o.cohort_label,
        "provisional_settings": result.settings.provisional,
        "settings": as_dict(result.settings),
        "warnings": report.warnings,
    }


def bundle_files(report: Report, result: PipelineResult, row_level: bool = False) -> dict[str, bytes]:
    """All export files as {relative path: bytes}. Row-level files only with row_level=True."""
    files = {
        "report.html": render_html(report).encode("utf-8"),
        "settings_used.toml": to_toml(result.settings, header="\n".join(report.context_lines())).encode("utf-8"),
        "run_info.json": json.dumps(run_info(report, result), indent=2, default=str).encode("utf-8"),
    }
    for key, table in report.tables.items():
        files[f"tables/{key}.csv"] = _csv_with_context(report, table).encode("utf-8-sig")
    if row_level:
        if report.shareable:
            raise ValueError("Row-level files cannot be part of a shareable export.")
        o, c = result.outcomes, result.clean
        files["PRIVATE_patient_outcomes.csv"] = o.patients.reset_index().to_csv(index=False).encode("utf-8-sig")
        files["PRIVATE_rows_for_review.csv"] = c.review_log.to_csv(index=False).encode("utf-8-sig")
    return files


def write_bundle(report: Report, result: PipelineResult, out_dir: str | Path, row_level: bool = False) -> list[Path]:
    out = Path(out_dir)
    written = []
    for rel, data in bundle_files(report, result, row_level).items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        written.append(path)
    return written


def bundle_zip(report: Report, result: PipelineResult) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, data in bundle_files(report, result).items():
            zf.writestr(rel, data)
    return buffer.getvalue()
