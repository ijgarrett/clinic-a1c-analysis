"""A1C outcome dashboard for clinic staff.

Run:  streamlit run dashboard.py
Opens with SYNTHETIC demo data. To use clinic data, choose a data source in the sidebar.
All numbers come from the same functions as a1c_report.py.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

from a1c import charts, config, synthetic
from a1c.cleaning import clean_a1c
from a1c.config import BASELINE_MODES, COHORT_MODES, describe_operator, to_toml
from a1c.loader import read_export, select_a1c
from a1c.pipeline import load_roster, run_pipeline
from a1c.report import build_report, bundle_zip, render_html

st.set_page_config(page_title="A1C outcomes", layout="wide")

SOURCES = ["Synthetic demo data", "Clinic export (path in settings file)", "Upload a 5.02a export"]
PERIODS = ["Window in settings file", "Whole export", "Last 6 months of export", "Last 12 months of export",
           "One calendar year", "Custom dates"]
METHODS_FILE = config.PROJECT_DIR / "docs" / "METHODS.md"


# ------------------------------------------------------------------ data loading

@st.cache_data(show_spinner="Reading the export...", max_entries=4)
def load_export(kind: str, key: str, data: bytes | None = None):
    if kind == "demo":
        return read_export(synthetic.generate_export(), name="SYNTHETIC demo export (seed 2026)")
    if kind == "file":
        return read_export(Path(key.split("|")[0]))
    return read_export(data, name=key)


@st.cache_data(show_spinner=False, max_entries=8)
def a1c_date_range(_export, sha: str, labels: tuple):
    s = config.Settings(a1c_labels=list(labels))
    m = clean_a1c(select_a1c(_export, s).rows, s).measurements
    if m.empty:
        today = dt.date.today()
        return today, today
    return m["date"].min().date(), m["date"].max().date()


@st.cache_data(show_spinner=False)
def base_settings(path: str, mtime: float) -> config.Settings:
    return config.load_settings(path)


cfg_path = config.default_config_path()
try:
    base = base_settings(str(cfg_path), cfg_path.stat().st_mtime)
except Exception as exc:  # show the problem instead of a stack trace
    st.error(f"The settings file {cfg_path.name} has a problem: {exc}")
    st.stop()

DEFAULTS = {
    "period": PERIODS[0],
    "baseline_mode": base.baseline_mode,
    "lookback_days": int(base.lookback_days),
    "cohort_mode": base.cohort_mode,
    "subgroup_min": float(base.subgroup_min_baseline),
    "control_threshold": float(base.control_threshold),
    "control_operator": base.control_operator,
    "tolerance": float(base.stability_tolerance),
    "cutpoints": ", ".join(f"{c:g}" for c in base.baseline_group_cutpoints),
    "min_denominator": int(base.min_denominator),
    "km_min_at_risk": int(base.km_min_at_risk),
    "share_mode": False,
    "min_cell_size": int(base.min_cell_size),
    "local_view": False,
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)


def reset_settings():
    for key, value in DEFAULTS.items():
        st.session_state[key] = value
    for key in ("custom_start", "custom_end", "year"):
        st.session_state.pop(key, None)


# ------------------------------------------------------------------ sidebar

sb = st.sidebar
sb.header("Data")
source = sb.radio("Data source", SOURCES, key="source")
try:
    if source == SOURCES[0]:
        export, synthetic_data = load_export("demo", "demo"), True
    elif source == SOURCES[1]:
        path = Path(base.input_file)
        path = path if path.is_absolute() else config.PROJECT_DIR / path
        if not path.exists():
            st.info(f"No clinic export at {base.input_file}. Put the 5.02a export there, change data.input_file in "
                    "the settings file, or upload the file.")
            st.stop()
        export, synthetic_data = load_export("file", f"{path}|{path.stat().st_mtime}"), False
    else:
        upload = sb.file_uploader("5.02a export (CSV)", type=["csv", "txt", "tsv"], key="upload")
        if upload is None:
            st.info("Upload the eBO 5.02a Lab Results Analysis Report export to start. "
                    "The file stays on this computer's dashboard session.")
            st.stop()
        export, synthetic_data = load_export("upload", upload.name, upload.getvalue()), False
except (ValueError, FileNotFoundError) as exc:
    st.error(f"Cannot read the export: {exc}")
    st.stop()

first_date, last_date = a1c_date_range(export, export.sha256, tuple(base.a1c_labels))

sb.header("Reporting period")
period = sb.selectbox("Period", PERIODS, key="period")
if period == PERIODS[0]:
    start, end = base.window_start or first_date, base.window_end or last_date
elif period == PERIODS[1]:
    start, end = first_date, last_date
elif period in (PERIODS[2], PERIODS[3]):
    months = 6 if period == PERIODS[2] else 12
    end = last_date
    start = (pd.Timestamp(end) - pd.DateOffset(months=months) + pd.Timedelta(days=1)).date()
elif period == PERIODS[4]:
    years = list(range(last_date.year, first_date.year - 1, -1))
    year = sb.selectbox("Year", years, key="year")
    start, end = dt.date(year, 1, 1), dt.date(year, 12, 31)
else:
    st.session_state.setdefault("custom_start", base.window_start or first_date)
    st.session_state.setdefault("custom_end", base.window_end or last_date)
    start = sb.date_input("Start (included)", key="custom_start")
    end = sb.date_input("End (included)", key="custom_end")
sb.caption(f"A1C results in this export: {first_date} to {last_date}.")

sb.header("Analysis settings")
baseline_mode = sb.radio("Baseline", list(BASELINE_MODES), key="baseline_mode",
                         format_func=lambda m: {"first_in_window": "First A1C inside the window",
                                                "pre_window": "Latest A1C before the window"}[m])
if baseline_mode == "pre_window":
    sb.number_input("Lookback before the window (days)", min_value=1, max_value=3650, step=30, key="lookback_days")
cohort_mode = sb.radio("Cohort", list(COHORT_MODES), key="cohort_mode",
                       format_func=lambda m: {"lab_subgroup": "Lab-based subgroup (by baseline A1C)",
                                              "all_tested": "All tested patients"}[m])
if cohort_mode == "lab_subgroup":
    sb.number_input("Subgroup: baseline A1C at or above (%)", min_value=4.0, max_value=20.0, step=0.1,
                    format="%.1f", key="subgroup_min")
roster_file = sb.file_uploader("Eligible-patient roster (optional CSV)", type=["csv", "txt"], key="roster",
                               help=f"One column named '{base.roster_id_column}' with account numbers.")
sb.number_input("Control threshold (%)", min_value=4.0, max_value=12.0, step=0.1, format="%.1f",
                key="control_threshold")
sb.selectbox("Control rule", list(config.CONTROL_OPERATORS), key="control_operator",
             format_func=lambda op: {"<": "Below the threshold", "<=": "At or below the threshold"}[op])
sb.number_input("Stability tolerance (percentage points)", min_value=0.0, max_value=3.0, step=0.1,
                format="%.1f", key="tolerance")
sb.text_input("Baseline group cutpoints (%)", key="cutpoints", help="Increasing values, separated by commas.")
with sb.expander("More settings"):
    st.number_input("Smallest denominator for a percentage", min_value=1, max_value=100, step=1,
                    key="min_denominator")
    st.number_input("Stop the time-to-event curve below this many patients", min_value=1, max_value=100,
                    step=1, key="km_min_at_risk")
sb.header("Privacy")
share_mode = sb.checkbox("Hide small counts (for sharing)", key="share_mode",
                         help="Applies the small-count rule to every table, chart and export on this page.")
sb.number_input("Small-count limit", min_value=2, max_value=50, step=1, key="min_cell_size",
                disabled=not share_mode)
local_view = sb.checkbox("Show patient-level views (approved local environment only)", key="local_view",
                         disabled=share_mode)
sb.button("Reset to settings file", on_click=reset_settings)
sb.caption(f"Settings file: config/{cfg_path.name}")

# ------------------------------------------------------------------ run the analysis

try:
    cuts = [float(x) for x in str(st.session_state["cutpoints"]).replace(";", ",").split(",") if x.strip()]
except ValueError:
    st.error("Baseline group cutpoints must be numbers separated by commas, for example 5.7, 6.5, 8.0, 10.0.")
    st.stop()

settings = base.with_changes(
    window_start=start, window_end=end,
    baseline_mode=baseline_mode, lookback_days=int(st.session_state["lookback_days"]),
    cohort_mode=cohort_mode, subgroup_min_baseline=round(float(st.session_state["subgroup_min"]), 2),
    control_threshold=round(float(st.session_state["control_threshold"]), 2),
    control_operator=st.session_state["control_operator"],
    stability_tolerance=round(float(st.session_state["tolerance"]), 2),
    baseline_group_cutpoints=cuts,
    min_denominator=int(st.session_state["min_denominator"]),
    km_min_at_risk=int(st.session_state["km_min_at_risk"]),
    min_cell_size=int(st.session_state["min_cell_size"]),
)
# Settings changed on this page are marked provisional until the clinic approves them.
changed = [config.attr_to_key(a) for a in ("window_start", "window_end", "baseline_mode", "cohort_mode",
                                           "subgroup_min_baseline", "control_threshold", "control_operator",
                                           "stability_tolerance", "baseline_group_cutpoints")
           if getattr(settings, a) != getattr(base, a)]
settings.provisional = list(dict.fromkeys(base.provisional + changed))

try:
    roster_ids = load_roster(roster_file.getvalue(), settings, roster_file.name) if roster_file else None
    result = run_pipeline(None, settings, synthetic=synthetic_data, roster_ids=roster_ids, export=export)
except ValueError as exc:
    st.error(f"These settings cannot be used: {exc}")
    st.stop()
report = build_report(result, shareable=share_mode)
T = report.tables
o = result.outcomes
show_patient_level = (local_view or synthetic_data) and not share_mode


def table(key: str):
    t = T.get(key)
    if t is None:
        return
    st.markdown(f"**{t.title}**")
    st.dataframe(t.frame, hide_index=True, width="stretch")
    if t.note:
        st.caption(t.note)


def chart(key_or_chart, empty: str):
    c = report.charts.get(key_or_chart) if isinstance(key_or_chart, str) else key_or_chart
    if c is None:
        st.info(empty)
    else:
        st.altair_chart(c, width="stretch", theme=None)


# ------------------------------------------------------------------ header

st.title("A1C outcomes")
if synthetic_data:
    st.info(f"**{report.label}.** Use this view for demos and training.")
elif share_mode:
    st.success(f"**{report.label}**")
else:
    st.warning(f"**{report.label}**")

ctx = dict(zip(report.context["item"], report.context["value"]))
c1, c2 = st.columns(2)
c1.markdown(f"**Reporting window:** {ctx['Reporting window']}  \n**Baseline rule:** {ctx['Baseline rule']}")
c2.markdown(f"**Cohort:** {ctx['Cohort']}  \n**Control target:** {ctx['Control target']}  \n"
            f"**Stability tolerance:** {ctx['Stability tolerance']}")
st.warning(f"**PROVISIONAL settings (need clinic approval):** {ctx['PROVISIONAL settings']}")
if report.warnings:
    with st.expander(f"Warnings ({len(report.warnings)})"):
        for w in report.warnings:
            st.write("- " + w)

tabs = st.tabs(["Overview", "Outcomes", "By starting A1C", "Time to control", "Methods and data quality", "Export"])

# ------------------------------------------------------------------ overview
with tabs[0]:
    if o.n_cohort == 0:
        st.info("No patients match these settings. Try a longer window, the 'All tested patients' cohort, "
                "or a lower subgroup value.")
    cat = T["outcome_categories"].frame.set_index("Outcome")
    ctl = T["control"].frame
    flow = T["patient_flow"].frame
    m = st.columns(5)
    m[0].metric("Cohort patients", flow["Patients"].iloc[-2], help=o.cohort_label)
    m[1].metric("Paired patients", flow["Patients"].iloc[-1],
                help="Baseline and a follow-up result on a later date.")
    m[2].metric("Improved", cat.loc["Improved", "Percent"],
                help=cat.loc["Improved", "Rule"])
    m[2].caption(f"{cat.loc['Improved', 'Patients']} of {cat.loc['Improved', 'Denominator']} paired patients")
    m[3].metric("Latest result at target", ctl["Percent"].iloc[0])
    m[3].caption(f"{ctl['Patients'].iloc[0]} of {ctl['Denominator'].iloc[0]} patients")
    m[4].metric("Reached target later", ctl["Percent"].iloc[2], help="Patients whose baseline was above target.")
    m[4].caption(f"{ctl['Patients'].iloc[2]} of {ctl['Denominator'].iloc[2]} above-target patients")
    left, right = st.columns([1, 1])
    with left:
        table("patient_flow")
        table("tests_per_patient")
    with right:
        chart("tests_per_year", "No A1C results inside the window.")
        table("tests_per_year")

# ------------------------------------------------------------------ outcomes
with tabs[1]:
    st.subheader("1. Improved, stable and worsened")
    chart("outcomes", "No paired patients for these settings, so no outcomes can be shown.")
    table("outcome_categories")
    st.subheader("2. Control")
    table("control")
    st.subheader("3. Size of the change")
    if share_mode:
        st.caption("The change distribution chart is hidden when small counts are hidden.")
    else:
        chart("change_histogram", "No paired patients.")
    table("magnitude")
    if show_patient_level:
        st.subheader("Baseline and follow-up for each patient (local view)")
        chart(charts.first_vs_latest_scatter(o.paired, settings.control_threshold), "No paired patients.")

# ------------------------------------------------------------------ by group
with tabs[2]:
    st.subheader("5. Outcomes by starting A1C")
    st.caption("Groups use the baseline A1C. Each group includes its lower value and excludes its upper value.")
    a, b = st.columns(2)
    with a:
        chart("group_change", "No group has enough paired patients to show.")
    with b:
        chart("group_outcomes", "No group has enough paired patients for percentages.")
    table("by_baseline_group")
    st.markdown(
        "**Read with care.** Groups have different follow-up lengths and different numbers of tests. "
        "Patients who start high usually come down on the next test even without a change in care "
        "(regression to the mean). Thus a larger decrease in a high group does not show that care worked better "
        "for that group.")

# ------------------------------------------------------------------ time to control
with tabs[3]:
    st.subheader("4. Time to first documented control")
    st.caption(f"Patients whose baseline was not {describe_operator(settings)}. The event is the first later "
               "test at target. Control is seen only on test dates, so the true date can be earlier.")
    table("time_to_control")
    table("time_to_control_checkpoints")
    if share_mode:
        st.caption("The time-to-event curves are hidden when small counts are hidden.")
    else:
        chart("time_to_control", "Too few patients are followed to draw the time-to-event curve.")
        st.caption(f"Censoring: a patient without control leaves the curve at the last result inside the window. "
                   f"Patients with no later result are not in the curve. The curve stops when fewer than "
                   f"{settings.km_min_at_risk} patients are still followed.")
        chart("days_to_control", "No patient reached control inside the window.")

# ------------------------------------------------------------------ methods and data quality
with tabs[4]:
    st.subheader("How the numbers are made")
    st.markdown(f"""
- **Input:** {result.export.name}. Only rows whose Lab Attribute matches {", ".join(settings.a1c_labels)} (any case) are used.
- **Dates:** collection date. Window {ctx['Reporting window']}. Results after the end date are never used.
- **{o.window.baseline_rule()}**
- **Paired patient:** baseline and follow-up on different dates. Change = follow-up minus baseline, in percentage points.
- **Categories:** improved below -{settings.stability_tolerance:g}, worsened above +{settings.stability_tolerance:g}, stable otherwise (a change of exactly {settings.stability_tolerance:g} is stable).
- **Control:** A1C {describe_operator(settings)}.
- **Units:** {ctx['Units']}.
""")
    table("data_quality")
    table("label_audit")
    table("nonnumeric_results")
    table("unusual_values")
    table("roster")
    if show_patient_level:
        with st.expander("Rows for review (PRIVATE: account numbers and dates)"):
            st.dataframe(result.clean.review_log, hide_index=True, width="stretch")
    table("settings")
    if METHODS_FILE.exists():
        with st.expander("Full method notes (docs/METHODS.md)"):
            st.markdown(METHODS_FILE.read_text(encoding="utf-8"))

# ------------------------------------------------------------------ export
with tabs[5]:
    st.subheader("Export the aggregate report")
    st.write(f"Label on every file: **{report.label}**")
    st.write("The export has the same tables and charts as this page, the active settings and the provisional "
             "list. It has no account numbers, names or dates of individual patients.")
    if not synthetic_data and not share_mode:
        st.warning("This export is for internal review in the approved environment. Turn on "
                   "'Hide small counts' before you make a version to share, and get clinic approval first.")
    stamp = f"{o.window.start.date()}_to_{o.window.end.date()}"
    kind = "demo" if synthetic_data else ("shareable" if share_mode else "internal")
    st.download_button("Download report bundle (ZIP: HTML, CSV tables, settings)", bundle_zip(report, result),
                       file_name=f"a1c_report_{kind}_{stamp}.zip", mime="application/zip", on_click="ignore")
    st.download_button("Download report (HTML only)", render_html(report).encode("utf-8"),
                       file_name=f"a1c_report_{kind}_{stamp}.html", mime="text/html", on_click="ignore")
    st.download_button("Download these settings (TOML)",
                       to_toml(settings, header="\n".join(report.context_lines())).encode("utf-8"),
                       file_name="a1c_settings.toml", mime="text/plain", on_click="ignore",
                       help="Save as config/a1c_settings.toml to make these the default settings.")
