"""Altair charts. The dashboard and the HTML report use the same functions.

Colors: improved = blue, stable = neutral gray, worsened = orange.
The set was checked for color-vision deficiency and contrast. Category names
are always written next to the marks, so color is never the only cue.
Each function returns None when there is nothing to draw.
"""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd

BLUE = "#2a78d6"
GRAY = "#898781"
ORANGE = "#eb6834"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
BAND = "#f0efec"
CATEGORY_COLORS = {"Improved": BLUE, "Stable": GRAY, "Worsened": ORANGE}
CATEGORY_ORDER = list(CATEGORY_COLORS)
CATEGORY_SCALE = alt.Scale(domain=CATEGORY_ORDER, range=[CATEGORY_COLORS[c] for c in CATEGORY_ORDER])


def _style(chart):
    return (chart.configure_axis(gridColor=GRID, domainColor=AXIS, tickColor=AXIS, labelColor=INK_2,
                                 titleColor=INK_2, labelFontSize=12, titleFontSize=12, titleFontWeight="normal")
            .configure_view(stroke=None)
            .configure_title(anchor="start", color=INK, fontSize=14, subtitleColor=INK_2, subtitleFontSize=12)
            .configure_legend(labelColor=INK_2, titleColor=INK_2, orient="top")
            .properties(background="#fcfcfb"))


def outcome_bars(categories: pd.DataFrame, hide: set[str] | None = None):
    """Improved / stable / worsened as horizontal bars with count and percent labels."""
    data = categories[categories["category"].isin(CATEGORY_ORDER)].copy()
    hide = hide or set()
    data = data[~data["category"].isin(hide)]
    den = int(categories["denominator"].iloc[0]) if len(categories) else 0
    if den == 0 or data.empty:
        return None
    data["label"] = [f"{n:,} ({p:.1f}%)" for n, p in zip(data["patients"], data["percent"])]
    base = alt.Chart(data).encode(
        y=alt.Y("category:N", sort=CATEGORY_ORDER, title=None, axis=alt.Axis(labelFontSize=13)),
        x=alt.X("percent:Q", title="Percent of paired patients", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("category:N", title="Outcome"), alt.Tooltip("patients:Q", title="Patients", format=","),
                 alt.Tooltip("percent:Q", title="Percent", format=".1f"), alt.Tooltip("rule:N", title="Rule")])
    bars = base.mark_bar(cornerRadiusEnd=4, height=28).encode(
        color=alt.Color("category:N", scale=CATEGORY_SCALE, legend=None))
    text = base.mark_text(align="left", dx=6, color=INK_2, fontSize=12).encode(text="label:N")
    title = alt.Title(f"Change from baseline to follow-up (denominator: {den:,} paired patients)",
                      subtitle="Categories use the stability tolerance from the settings.")
    return _style((bars + text).properties(title=title, height=150, width="container"))


def change_histogram(paired: pd.DataFrame, tolerance: float, limit: float = 6.0):
    """Distribution of patient-level change, stacked by outcome category."""
    if paired.empty:
        return None
    change = paired["change"].clip(-limit, limit)
    width = 0.5
    start = np.floor((change + width / 2) / width) * width - width / 2
    data = pd.DataFrame({"start": start.round(2), "category": paired["category"].to_numpy()})
    data = data.groupby(["start", "category"]).size().rename("patients").reset_index()
    data["end"] = data["start"] + width
    data["range"] = [f"{a:+.2f} to {b:+.2f}" for a, b in zip(data["start"], data["end"])]
    clipped = int((paired["change"].abs() > limit).sum())
    subtitle = [f"Gray band = stable range (-{tolerance:g} to +{tolerance:g} points). Negative = A1C went down."]
    if clipped:
        subtitle.append(f"{clipped} patient(s) with a change beyond {limit:g} points are drawn in the end bars.")
    band = alt.Chart(pd.DataFrame({"a": [-tolerance], "b": [tolerance]})).mark_rect(color=BAND).encode(x="a:Q", x2="b:Q")
    bars = alt.Chart(data).mark_bar(stroke="#fcfcfb", strokeWidth=1).encode(
        x=alt.X("start:Q", title="Change in A1C (percentage points)", scale=alt.Scale(domain=[-limit, limit + width])),
        x2="end:Q",
        y=alt.Y("sum(patients):Q", title="Patients", stack="zero"),
        color=alt.Color("category:N", scale=CATEGORY_SCALE, title="Outcome"),
        order=alt.Order("category:N"),
        tooltip=[alt.Tooltip("range:N", title="Change"), alt.Tooltip("category:N", title="Outcome"),
                 alt.Tooltip("patients:Q", title="Patients")])
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=INK_2).encode(x="x:Q")
    title = alt.Title(f"Change for each paired patient (n = {len(paired):,})", subtitle=subtitle)
    return _style((band + bars + zero).properties(title=title, height=260, width="container"))


def group_change_chart(by_group: pd.DataFrame, tolerance: float, min_patients: int = 1):
    """Median change (dot) and interquartile range (line) by starting A1C group."""
    data = by_group[by_group["paired_patients"].ge(max(min_patients, 1))].copy()
    if data.empty:
        return None
    data["group"] = [f"{g} (n = {n})" for g, n in zip(data["baseline_group"], data["paired_patients"])]
    order = list(data["group"])
    band = alt.Chart(pd.DataFrame({"a": [-tolerance], "b": [tolerance]})).mark_rect(color=BAND).encode(x="a:Q", x2="b:Q")
    tips = [alt.Tooltip("group:N", title="Baseline group"),
            alt.Tooltip("median_change_pp:Q", title="Median change"),
            alt.Tooltip("q1_pp:Q", title="25th percentile"), alt.Tooltip("q3_pp:Q", title="75th percentile")]
    rule = alt.Chart(data).mark_rule(color=BLUE, strokeWidth=2).encode(
        y=alt.Y("group:N", sort=order, title="Baseline A1C group (%)"), x=alt.X("q1_pp:Q"), x2="q3_pp:Q", tooltip=tips)
    dot = alt.Chart(data).mark_point(filled=True, size=110, color=BLUE, stroke="#fcfcfb", strokeWidth=2).encode(
        y=alt.Y("group:N", sort=order), x=alt.X("median_change_pp:Q", title="Change in A1C (percentage points)"),
        tooltip=tips)
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=INK_2).encode(x="x:Q")
    title = alt.Title("Median change by starting A1C",
                      subtitle="Dot = median. Line = middle half of patients (25th to 75th percentile).")
    return _style((band + rule + zero + dot).properties(title=title, height=max(120, 46 * len(data)), width="container"))


def group_outcome_chart(by_group: pd.DataFrame, min_denominator: int):
    """Share improved / stable / worsened in each starting group with enough patients."""
    rows = []
    for _, r in by_group[by_group["paired_patients"].ge(max(min_denominator, 1))].iterrows():
        for cat, col in (("Improved", "improved"), ("Stable", "stable"), ("Worsened", "worsened")):
            rows.append({"group": f"{r['baseline_group']} (n = {r['paired_patients']})", "category": cat,
                         "patients": int(r[col]), "percent": 100 * r[col] / r["paired_patients"]})
    if not rows:
        return None
    data = pd.DataFrame(rows)
    order = list(dict.fromkeys(data["group"]))
    data["rank"] = data["category"].map({c: i for i, c in enumerate(CATEGORY_ORDER)})
    bars = alt.Chart(data).mark_bar(stroke="#fcfcfb", strokeWidth=2, height=24).encode(
        y=alt.Y("group:N", sort=order, title="Baseline A1C group (%)"),
        x=alt.X("percent:Q", stack="normalize", title="Share of paired patients", axis=alt.Axis(format="%")),
        color=alt.Color("category:N", scale=CATEGORY_SCALE, title="Outcome"),
        order=alt.Order("rank:Q"),
        tooltip=[alt.Tooltip("group:N", title="Group"), alt.Tooltip("category:N", title="Outcome"),
                 alt.Tooltip("patients:Q", title="Patients"), alt.Tooltip("percent:Q", title="Percent", format=".1f")])
    title = alt.Title("Outcome by starting A1C",
                      subtitle=f"Only groups with {min_denominator} or more paired patients are shown.")
    return _style(bars.properties(title=title, height=max(100, 40 * len(order)), width="container"))


def time_to_control_curve(km_curve: pd.DataFrame, checkpoints: pd.DataFrame, target_text: str, min_at_risk: int):
    """Cumulative percent with first documented control (Kaplan-Meier, exploratory)."""
    if km_curve.empty:
        return None
    data = km_curve.copy()
    line = alt.Chart(data).mark_line(interpolate="step-after", color=BLUE, strokeWidth=2).encode(
        x=alt.X("days:Q", title="Days since baseline"),
        y=alt.Y("pct_reached:Q", title="Percent with documented control", scale=alt.Scale(domain=[0, 100])),
        tooltip=[alt.Tooltip("days:Q", title="Day"), alt.Tooltip("pct_reached:Q", title="Percent", format=".1f"),
                 alt.Tooltip("at_risk:Q", title="Still followed")])
    layers = [line]
    shown = checkpoints[checkpoints["shown"]] if len(checkpoints) else checkpoints
    if len(shown):
        pts = shown.assign(label=[f"{p:.0f}% by day {d} ({n} still followed)"
                                  for d, p, n in zip(shown["day"], shown["pct_reached"], shown["still_followed"])])
        layers.append(alt.Chart(pts).mark_point(filled=True, size=90, color=BLUE, stroke="#fcfcfb", strokeWidth=2)
                      .encode(x="day:Q", y="pct_reached:Q", tooltip=["label:N"]))
        # Labels go up and to the left: the curve never rises to the left of a point.
        layers.append(alt.Chart(pts).mark_text(align="right", dx=-8, dy=-14, color=INK_2, fontSize=12)
                      .encode(x="day:Q", y="pct_reached:Q", text="label:N"))
    title = alt.Title(f"Time to first documented A1C {target_text} (exploratory)",
                      subtitle=[f"Patients with an above-target baseline and a later result. "
                                f"The curve stops when fewer than {min_at_risk} patients are still followed.",
                                "Control is seen only on test dates, so the true date can be earlier."])
    return _style(alt.layer(*layers).properties(title=title, height=280, width="container"))


def days_to_control_chart(days: pd.Series, bin_days: int = 60):
    """Days from baseline to first documented control, only for patients who reached it."""
    days = days.dropna()
    if days.empty:
        return None
    data = pd.DataFrame({"start": (days // bin_days * bin_days).astype(int)})
    data = data.groupby("start").size().rename("patients").reset_index()
    data["end"] = data["start"] + bin_days
    data["range"] = [f"{a} to {b - 1} days" for a, b in zip(data["start"], data["end"])]
    bars = alt.Chart(data).mark_bar(color=BLUE, stroke="#fcfcfb", strokeWidth=1, cornerRadiusEnd=2).encode(
        x=alt.X("start:Q", title="Days from baseline to first documented control"), x2="end:Q",
        y=alt.Y("sum(patients):Q", title="Patients", stack="zero", axis=alt.Axis(tickMinStep=1)),
        tooltip=[alt.Tooltip("range:N", title="Days"), alt.Tooltip("patients:Q", title="Patients")])
    title = alt.Title(f"Time among the {len(days)} patients who reached control",
                      subtitle="This describes only patients who reached control. It is not a figure for all patients.")
    return _style(bars.properties(title=title, height=220, width="container"))


def tests_per_year_chart(tests_per_year: pd.DataFrame):
    if tests_per_year.empty:
        return None
    data = tests_per_year.copy()
    data["year_label"] = [f"{y}" if m >= 11.5 else f"{y} ({m:g} months)"
                          for y, m in zip(data["year"], data["months_in_window"])]
    base = alt.Chart(data).encode(
        x=alt.X("year_label:N", title=None, sort=list(data["year_label"]), axis=alt.Axis(labelAngle=0)),
        y=alt.Y("a1c_results:Q", title="A1C results"),
        tooltip=[alt.Tooltip("year_label:N", title="Year"), alt.Tooltip("a1c_results:Q", title="A1C results"),
                 alt.Tooltip("patients_tested:Q", title="Patients tested")])
    bars = base.mark_bar(color=BLUE, cornerRadiusEnd=4, width=alt.RelativeBandSize(0.55))
    text = base.mark_text(dy=-8, color=INK_2, fontSize=12).encode(text=alt.Text("a1c_results:Q", format=","))
    title = alt.Title("A1C results inside the reporting window, by year",
                      subtitle="All tested patients, not only the cohort. Partial years show their months.")
    return _style((bars + text).properties(title=title, height=240, width="container"))


def first_vs_latest_scatter(paired: pd.DataFrame, target: float, limit: float = 16.0):
    """APPROVED LOCAL VIEW ONLY: one dot for each patient."""
    if paired.empty:
        return None
    data = paired[["baseline_a1c", "followup_a1c", "category"]].copy()
    lo = min(4.0, float(data[["baseline_a1c", "followup_a1c"]].min().min()))
    off = int((data[["baseline_a1c", "followup_a1c"]] > limit).any(axis=1).sum())
    data = data[(data[["baseline_a1c", "followup_a1c"]] <= limit).all(axis=1)]
    scale = alt.Scale(domain=[lo, limit])
    dots = alt.Chart(data).mark_point(filled=True, size=50, opacity=0.75, stroke="#fcfcfb", strokeWidth=1).encode(
        x=alt.X("baseline_a1c:Q", title="Baseline A1C (%)", scale=scale),
        y=alt.Y("followup_a1c:Q", title="Follow-up A1C (%)", scale=scale),
        color=alt.Color("category:N", scale=CATEGORY_SCALE, title="Outcome"),
        tooltip=[alt.Tooltip("baseline_a1c:Q", title="Baseline"), alt.Tooltip("followup_a1c:Q", title="Follow-up"),
                 alt.Tooltip("category:N", title="Outcome")])
    diag = alt.Chart(pd.DataFrame({"x": [lo, limit], "y": [lo, limit]})).mark_line(color=INK_2, strokeWidth=1).encode(
        x="x:Q", y="y:Q")
    tline = alt.Chart(pd.DataFrame({"y": [target]})).mark_rule(color=ORANGE, strokeWidth=1).encode(y="y:Q")
    sub = ["Diagonal line = no change. Orange line = control threshold.",
           "Local view only: each dot is one patient."]
    if off:
        sub.append(f"{off} patient(s) with a value above {limit:g}% are not drawn.")
    title = alt.Title(f"Baseline and follow-up A1C ({len(paired):,} paired patients)", subtitle=sub)
    return _style((diag + tline + dots).properties(title=title, height=420, width="container"))
