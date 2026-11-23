"""Baseline, follow-up and the five client outcomes.

Date rules (all dates are collection dates, whole days, both ends inclusive):
- Results after the report end are never used.
- Baseline "first_in_window": the first kept result from window start to window end.
- Baseline "pre_window": the latest kept result from (start - lookback_days) to the day
  before the window start.
- Follow-up: the latest kept result inside the window on a later date than the baseline.
  Thus the follow-up always falls inside the reporting window.
- Paired patient: has a baseline and a follow-up.
- A patient with no baseline is not in the cohort. A patient with a baseline but no
  follow-up stays in the cohort but is not classified (shown as "No follow-up").
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import Settings, describe_operator, group_labels, meets_target

CATEGORIES = ["Improved", "Stable", "Worsened"]
NO_FOLLOW_UP = "No follow-up"


@dataclass
class Window:
    start: pd.Timestamp
    end: pd.Timestamp
    baseline_mode: str
    lookback_start: pd.Timestamp | None

    def describe(self) -> str:
        text = f"{self.start.date()} to {self.end.date()}"
        if self.baseline_mode == "pre_window":
            text += f" (baseline from {self.lookback_start.date()} to {(self.start - pd.Timedelta(days=1)).date()})"
        return text

    def baseline_rule(self) -> str:
        if self.baseline_mode == "pre_window":
            return (f"Baseline = latest valid A1C from {self.lookback_start.date()} to "
                    f"{(self.start - pd.Timedelta(days=1)).date()} (before the window). "
                    "Follow-up = latest valid A1C inside the window.")
        return ("Baseline = first valid A1C inside the window. "
                "Follow-up = latest valid A1C inside the window on a later date.")


@dataclass
class Outcomes:
    window: Window
    cohort_label: str
    patients: pd.DataFrame            # PRIVATE: one row for each cohort patient
    all_patients: pd.DataFrame        # PRIVATE: every patient with a baseline, before cohort rules
    funnel: pd.DataFrame
    categories: pd.DataFrame
    control: pd.DataFrame
    magnitude: pd.DataFrame
    time_to_control: pd.DataFrame
    km_curve: pd.DataFrame
    km_checkpoints: pd.DataFrame
    by_group: pd.DataFrame
    tests_per_year: pd.DataFrame
    tests_per_patient: pd.DataFrame
    results_after_end: int
    roster: dict | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def n_cohort(self) -> int:
        return len(self.patients)

    @property
    def paired(self) -> pd.DataFrame:
        return self.patients[self.patients["paired"]]

    @property
    def n_paired(self) -> int:
        return int(self.patients["paired"].sum()) if len(self.patients) else 0


def resolve_window(measurements: pd.DataFrame, s: Settings) -> Window:
    dates = measurements["date"]
    if s.window_start:
        start = pd.Timestamp(s.window_start)
    elif len(dates):
        start = dates.min()
    else:
        start = pd.Timestamp.today().normalize()
    if s.window_end:
        end = pd.Timestamp(s.window_end)
    elif len(dates):
        end = dates.max()
    else:
        end = start
    if start > end:
        raise ValueError("The reporting window starts after it ends.")
    lookback = start - pd.Timedelta(days=int(s.lookback_days)) if s.baseline_mode == "pre_window" else None
    return Window(start, end, s.baseline_mode, lookback)


def _pct(num, den):
    return round(100.0 * num / den, 1) if den else np.nan


def _quantiles(series: pd.Series):
    if len(series) == 0:
        return np.nan, np.nan, np.nan
    return (round(float(series.median()), 2), round(float(series.quantile(0.25)), 2),
            round(float(series.quantile(0.75)), 2))


def cohort_description(s: Settings, roster_used: bool) -> str:
    if s.cohort_mode == "lab_subgroup":
        text = (f"Patients whose baseline A1C was {s.subgroup_min_baseline:g}% or higher "
                "(lab-based subgroup by starting value; not a confirmed diagnosis)")
    else:
        text = "All patients with a baseline A1C"
    if roster_used:
        text = "Clinic roster patients only. " + text
    return text


def build_patient_table(measurements: pd.DataFrame, s: Settings, window: Window) -> pd.DataFrame:
    """One row for each patient with a baseline. Uses no result after the report end."""
    tol = round(float(s.stability_tolerance), 6)
    usable = measurements[measurements["date"].le(window.end)]
    in_window = usable[usable["date"].ge(window.start)]
    if window.baseline_mode == "pre_window":
        pre = usable[usable["date"].ge(window.lookback_start) & usable["date"].lt(window.start)]
        base = pre.groupby("patient_id").tail(1)
    else:
        base = in_window.groupby("patient_id").head(1)
    base = base.set_index("patient_id")[["date", "a1c"]].rename(
        columns={"date": "baseline_date", "a1c": "baseline_a1c"})

    later = in_window.merge(base[["baseline_date"]].reset_index(), on="patient_id", how="inner")
    later = later[later["date"].gt(later["baseline_date"])]
    follow = later.groupby("patient_id").tail(1).set_index("patient_id")[["date", "a1c"]].rename(
        columns={"date": "followup_date", "a1c": "followup_a1c"})
    at_target = later[meets_target(later["a1c"], s)]
    first_control = at_target.groupby("patient_id")["date"].min().rename("first_control_date")
    latest = in_window.groupby("patient_id").tail(1).set_index("patient_id")[["date", "a1c"]].rename(
        columns={"date": "latest_date", "a1c": "latest_a1c"})
    n_window = in_window.groupby("patient_id").size().rename("results_in_window")

    p = base.join(follow).join(first_control).join(latest).join(n_window)
    p["results_in_window"] = p["results_in_window"].fillna(0).astype(int)
    p["later_results"] = later.groupby("patient_id").size().reindex(p.index).fillna(0).astype(int)
    p["paired"] = p["followup_a1c"].notna()
    p["change"] = (p["followup_a1c"] - p["baseline_a1c"]).round(2)
    p["followup_days"] = (p["followup_date"] - p["baseline_date"]).dt.days
    p["category"] = np.select(
        [~p["paired"], p["change"].lt(-tol), p["change"].gt(tol)],
        [NO_FOLLOW_UP, "Improved", "Worsened"], default="Stable")
    p["baseline_at_target"] = meets_target(p["baseline_a1c"], s)
    p["latest_at_target"] = meets_target(p["latest_a1c"], s) & p["latest_a1c"].notna()
    p["reached_target_later"] = ~p["baseline_at_target"] & p["first_control_date"].notna()
    p["days_to_control"] = np.where(p["reached_target_later"],
                                    (p["first_control_date"] - p["baseline_date"]).dt.days, np.nan)
    cuts = [float(c) for c in s.baseline_group_cutpoints]
    p["baseline_group"] = pd.cut(p["baseline_a1c"], bins=[-np.inf, *cuts, np.inf],
                                 labels=group_labels(cuts), right=False)
    return p


def kaplan_meier(time_days: pd.Series, event: pd.Series) -> pd.DataFrame:
    """Cumulative percent with the event. Patients without the event are censored at time_days."""
    df = pd.DataFrame({"t": time_days.astype(float), "e": event.astype(bool)})
    rows = [(0.0, 0.0, len(df))]
    surv = 1.0
    for u in np.sort(df.loc[df["e"], "t"].unique()):
        at_risk = int(df["t"].ge(u).sum())
        d = int((df["t"].eq(u) & df["e"]).sum())
        surv *= 1 - d / at_risk
        rows.append((float(u), round(100 * (1 - surv), 2), at_risk))
    return pd.DataFrame(rows, columns=["days", "pct_reached", "at_risk"])


def analyze(measurements: pd.DataFrame, s: Settings, roster_ids: set[str] | None = None) -> Outcomes:
    window = resolve_window(measurements, s)
    usable = measurements[measurements["date"].le(window.end)]
    in_window = usable[usable["date"].ge(window.start)]
    everyone = build_patient_table(measurements, s, window)

    funnel = [
        ("Patients with at least one kept A1C result (any date)", measurements["patient_id"].nunique()),
        (f"With a kept result on or before the report end ({window.end.date()})", usable["patient_id"].nunique()),
    ]
    if window.baseline_mode == "pre_window":
        funnel.append(("With a baseline result in the lookback period", len(everyone)))
    else:
        funnel.append(("With a baseline (a kept result inside the window)", len(everyone)))

    p = everyone
    roster = None
    if roster_ids is not None:
        roster_ids = {str(x).strip() for x in roster_ids if str(x).strip()}
        in_export = set(measurements["patient_id"])
        roster = {
            "roster_patients": len(roster_ids),
            "roster_with_baseline": len(roster_ids & set(everyone.index)),
            "roster_without_usable_a1c": len(roster_ids - set(everyone.index)),
            "roster_never_in_export": len(roster_ids - in_export),
        }
        p = p[p.index.isin(roster_ids)]
        funnel.append(("On the eligible-patient roster", len(p)))
    if s.cohort_mode == "lab_subgroup":
        p = p[p["baseline_a1c"].ge(s.subgroup_min_baseline)]
        funnel.append((f"In the cohort (baseline A1C {s.subgroup_min_baseline:g}% or higher)", len(p)))
    else:
        funnel.append(("In the cohort (all patients with a baseline)", len(p)))
    funnel.append(("With a follow-up result on a later date (paired)", int(p["paired"].sum())))
    funnel_df = pd.DataFrame(funnel, columns=["step", "patients"])
    funnel_df["patients"] = funnel_df["patients"].astype(int)

    paired = p[p["paired"]]
    n_paired = len(paired)
    tol = float(s.stability_tolerance)

    # 1. Improved / stable / worsened
    rules = {
        "Improved": f"Change below -{tol:g} percentage points",
        "Stable": f"Change from -{tol:g} to +{tol:g} percentage points (both ends count as stable)",
        "Worsened": f"Change above +{tol:g} percentage points",
    }
    counts = paired["category"].value_counts().reindex(CATEGORIES, fill_value=0)
    categories = pd.DataFrame({
        "category": CATEGORIES,
        "patients": [int(counts[c]) for c in CATEGORIES],
        "denominator": n_paired,
        "percent": [_pct(counts[c], n_paired) for c in CATEGORIES],
        "rule": [rules[c] for c in CATEGORIES],
    })
    no_follow = int((~p["paired"]).sum())
    categories = pd.concat([categories, pd.DataFrame([{
        "category": NO_FOLLOW_UP, "patients": no_follow, "denominator": len(p),
        "percent": _pct(no_follow, len(p)),
        "rule": "Baseline only; not classified. Percent is of all cohort patients.",
    }])], ignore_index=True)

    # 2. Control
    target = describe_operator(s)
    with_window_result = p[p["latest_a1c"].notna()]
    above = p[~p["baseline_at_target"]]
    above_with_later = above[above["later_results"].gt(0)]
    control_rows = [
        ("Latest result at target", int(with_window_result["latest_at_target"].sum()), len(with_window_result),
         f"Latest result inside the window is {target}. Denominator: cohort patients with a result inside the window."),
        ("Latest result at target (paired patients only)", int(paired["latest_at_target"].sum()), n_paired,
         "Same rule. Denominator: patients with a baseline and a follow-up."),
        ("Reached target after an above-target baseline", int(above["reached_target_later"].sum()), len(above),
         f"Any later result inside the window is {target}. Denominator: cohort patients whose baseline was not at target."),
        ("Reached target, among those with a later result", int(above["reached_target_later"].sum()), len(above_with_later),
         "Same numerator. Denominator: above-target patients with at least one later result."),
        ("Above-target baseline with no later result", int(above["later_results"].eq(0).sum()), len(above),
         "No later result inside the window, so control cannot be seen."),
        ("Baseline already at target (left out of the two rows above)", int(p["baseline_at_target"].sum()), len(p),
         "These patients are not in the 'reached target' denominators."),
    ]
    control = pd.DataFrame(control_rows, columns=["measure", "numerator", "denominator", "note"])
    control["percent"] = [_pct(n, d) for n, d in zip(control["numerator"], control["denominator"])]
    control = control[["measure", "numerator", "denominator", "percent", "note"]]

    # 3. Magnitude (patient-level changes first, then summaries)
    improved = paired[paired["category"].eq("Improved")]
    worsened = paired[paired["category"].eq("Worsened")]
    mag_rows = []
    for label, values, note in [
        ("Change, all paired patients (follow-up minus baseline)", paired["change"],
         "Negative = A1C went down."),
        ("Decrease, improved patients only", -improved["change"],
         "Shown as a positive number of percentage points."),
        ("Increase, worsened patients only", worsened["change"], ""),
    ]:
        med, q1, q3 = _quantiles(values)
        mag_rows.append({"measure": label, "patients": len(values), "median_pp": med,
                         "q1_pp": q1, "q3_pp": q3, "note": note})
    magnitude = pd.DataFrame(mag_rows)

    # 4. Time to first documented control
    days = above.loc[above["reached_target_later"], "days_to_control"]
    med, q1, q3 = _quantiles(days)
    fu_med = above_with_later["followup_days"].median() if len(above_with_later) else np.nan
    ttc_rows = [
        {"measure": "Patients with an above-target baseline", "value": len(above),
         "denominator": np.nan, "note": "Starting population for time to control."},
        {"measure": "With at least one later result (follow-up coverage)", "value": len(above_with_later),
         "denominator": len(above), "note": "Only these patients can show control."},
        {"measure": "Median follow-up of those patients (days)", "value": fu_med,
         "denominator": np.nan, "note": "Days from baseline to the last result inside the window."},
        {"measure": "Reached first documented control", "value": int(above["reached_target_later"].sum()),
         "denominator": len(above), "note": "First later result at target."},
        {"measure": "Median days to first documented control", "value": med, "denominator": np.nan,
         "note": f"ONLY the {len(days)} patients who reached control (IQR {q1} to {q3} days). "
                 "Not a median for all patients."},
    ]
    time_to_control = pd.DataFrame(ttc_rows)
    time_to_control["percent"] = [
        _pct(v, d) if pd.notna(d) else np.nan for v, d in zip(time_to_control["value"], time_to_control["denominator"])]

    km_input = above_with_later
    km_time = np.where(km_input["reached_target_later"], km_input["days_to_control"], km_input["followup_days"])
    km_full = kaplan_meier(pd.Series(km_time, index=km_input.index), km_input["reached_target_later"]) \
        if len(km_input) else pd.DataFrame(columns=["days", "pct_reached", "at_risk"])
    times = pd.Series(km_time, dtype=float)

    def at_risk(day):
        return int(times.ge(day).sum())

    def km_at(day):
        if km_full.empty:
            return np.nan
        return float(km_full.loc[km_full["days"].le(day), "pct_reached"].iloc[-1])

    if len(times) and at_risk(1) >= s.km_min_at_risk:
        cutoff = max(d for d in range(0, int(times.max()) + 1) if at_risk(d) >= s.km_min_at_risk)
        km_curve = km_full[km_full["days"].le(cutoff)].copy()
        km_curve = pd.concat([km_curve, pd.DataFrame(
            {"days": [float(cutoff)], "pct_reached": [km_at(cutoff)], "at_risk": [at_risk(cutoff)]})],
            ignore_index=True)
    else:
        km_curve = pd.DataFrame(columns=["days", "pct_reached", "at_risk"])
    km_checkpoints = pd.DataFrame([{
        "day": int(d), "pct_reached": km_at(d), "still_followed": at_risk(d),
        "shown": at_risk(d) >= s.km_min_at_risk,
    } for d in s.km_checkpoints])
    if len(km_checkpoints):
        km_checkpoints.loc[~km_checkpoints["shown"], "pct_reached"] = np.nan

    # 5. By starting A1C group
    group_rows = []
    for g in group_labels(s.baseline_group_cutpoints):
        gp = p[p["baseline_group"].astype("string").eq(g)]
        gpaired = gp[gp["paired"]]
        gabove = gp[~gp["baseline_at_target"]]
        gwin = gp[gp["latest_a1c"].notna()]
        cat = gpaired["category"].value_counts().reindex(CATEGORIES, fill_value=0)
        enough = len(gpaired) >= s.min_denominator
        med, q1, q3 = _quantiles(gpaired["change"])
        group_rows.append({
            "baseline_group": g,
            "baseline_patients": len(gp),
            "paired_patients": len(gpaired),
            "follow_up_coverage_pct": _pct(len(gpaired), len(gp)),
            "median_followup_days": gpaired["followup_days"].median() if len(gpaired) else np.nan,
            "median_change_pp": med, "q1_pp": q1, "q3_pp": q3,
            "improved": int(cat["Improved"]), "stable": int(cat["Stable"]), "worsened": int(cat["Worsened"]),
            "improved_pct": _pct(cat["Improved"], len(gpaired)) if enough else np.nan,
            "stable_pct": _pct(cat["Stable"], len(gpaired)) if enough else np.nan,
            "worsened_pct": _pct(cat["Worsened"], len(gpaired)) if enough else np.nan,
            "latest_at_target": int(gwin["latest_at_target"].sum()),
            "latest_at_target_pct": _pct(gwin["latest_at_target"].sum(), len(gwin))
            if len(gwin) >= s.min_denominator else np.nan,
            "above_target_baseline": len(gabove),
            "reached_target_later": int(gabove["reached_target_later"].sum()),
            "note": "" if enough else (f"Fewer than {s.min_denominator} paired patients: percentages not shown"
                                       if len(gp) else "No patients in this group for the active cohort"),
        })
    by_group = pd.DataFrame(group_rows)

    # Testing volume inside the window (all tested patients, not only the cohort)
    if len(in_window):
        tw = in_window.assign(year=in_window["date"].dt.year)
        tpy = tw.groupby("year").agg(a1c_results=("a1c", "size"), patients_tested=("patient_id", "nunique"))
        tpy["months_in_window"] = [
            round(((min(window.end, pd.Timestamp(f"{y}-12-31")) - max(window.start, pd.Timestamp(f"{y}-01-01"))).days + 1)
                  / 30.44, 1) for y in tpy.index]
        tests_per_year = tpy.reset_index()
        per_patient = in_window.groupby("patient_id").size()
        bands = pd.cut(per_patient, [0, 1, 2, 3, 5, np.inf], labels=["1", "2", "3", "4 to 5", "6 or more"])
        tests_per_patient = bands.value_counts().sort_index().rename_axis("results_in_window").rename("patients").reset_index()
        tests_per_patient["percent"] = [_pct(n, len(per_patient)) for n in tests_per_patient["patients"]]
    else:
        tests_per_year = pd.DataFrame(columns=["year", "a1c_results", "patients_tested", "months_in_window"])
        tests_per_patient = pd.DataFrame(columns=["results_in_window", "patients", "percent"])

    notes = []
    if window.baseline_mode == "pre_window":
        no_base = len(set(in_window["patient_id"]) - set(everyone.index))
        notes.append(f"{no_base} patients had a result inside the window but no baseline in the lookback period. "
                     "They are not in the cohort.")
    return Outcomes(
        window=window,
        cohort_label=cohort_description(s, roster_ids is not None),
        patients=p,
        all_patients=everyone,
        funnel=funnel_df,
        categories=categories,
        control=control,
        magnitude=magnitude,
        time_to_control=time_to_control,
        km_curve=km_curve,
        km_checkpoints=km_checkpoints,
        by_group=by_group,
        tests_per_year=tests_per_year,
        tests_per_patient=tests_per_patient,
        results_after_end=int(measurements["date"].gt(window.end).sum()),
        roster=roster,
        notes=notes,
    )
