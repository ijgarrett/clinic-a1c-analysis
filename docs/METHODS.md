# A1C outcome methods

This file gives the rules that the dashboard and `a1c_report.py` use. The code that applies each rule is named in brackets.

## 1. Input

- The input is the eClinicalWorks eBO report **5.02a, Lab Results Analysis Report**, exported as CSV.
- The file is UTF-16 and tab-separated. Each data row has one extra tab at the end. The reader removes that empty last field. If a row has a different number of fields, the reader stops with an error. Thus, columns cannot move out of line without notice. [`a1c/loader.py`]
- All values are read as text. Account numbers keep their leading zeros.
- The export has two `Patient Acct No` columns. The reader combines them into one ID. If the two columns disagree on a row, that row is removed.
- An A1C row is a row where `Lab Attribute` is an exact match to a name in `data.a1c_labels`. The match ignores upper and lower case and extra spaces. The default name, `Hemoglobin A1c`, also matches `Hemoglobin A1C`.
- These rows are never A1C. The settings check stops if you add them to `data.a1c_labels`:
  - `Hemoglobin` (CBC hemoglobin, a different test)
  - `Est. Average Glucose` (calculated from the A1C, not a separate measurement)
- A label table shows every attribute and order name that looks like A1C, and whether it was used.
- 5.02b (the numeric-range extract) held only A1C values of 10% or more. Use it only as a cross-check (`--compare-502b`). Do not use it as an input.

## 2. Units

- The export has no unit column. The analysis assumes **percent (NGSP)**. The setting `data.units_confirmed_by_clinic` stays `false` until the clinic confirms the unit. Reports show this as provisional.
- The software does not decide the unit from the range of values. It only gives a warning if kept values fall outside 2 to 25, which is rare on a percent scale.

## 3. Data-quality rules [`a1c/cleaning.py`]

| Rule | Action |
|---|---|
| Missing patient ID | Removed |
| `Patient Acct No` columns disagree | Removed |
| Missing or invalid collection date | Removed |
| Blank result | Removed |
| Comparator result, for example `>14.0` | Removed (the true value is not known) |
| Malformed number, for example `6.3.` | Removed |
| Text result, for example `Clotted sample` | Removed |
| Value 0 or less, or above 100 | Removed (not a possible percent) |
| Row on the approved exclusion list | Removed. A written reason is required. |
| Same patient, same date, same value | One copy kept, if `collapse_identical_same_day = true` |
| Same patient, same date, different values | All rows held for review. If the clinic approves one row (`approved_keep_rows`), that row is kept and the others are set aside. |
| Value below `review_low` or above `review_high` | **Kept**, and listed for review |

- The review log keeps the source text of every flagged row, for local review only. It contains account numbers and dates, so it is never part of a shared export.
- Row numbers in `approved_keep_rows` and `excluded_source_rows` refer to one export file. They change with each new export. Check them after each refresh.

## 4. Dates and the reporting window [`a1c/outcomes.py`]

- All dates are the **Order Collection / Performed Date**, as whole days.
- The window has a start date and an end date. **Both dates are included.**
- **Results after the end date are never used.**
- Baseline rule (setting `window.baseline`):
  - `first_in_window` (default): the baseline is the first valid A1C from the start date to the end date.
  - `pre_window`: the baseline is the latest valid A1C from (start date minus `lookback_days`) to the day before the start date.
- The follow-up is the latest valid A1C inside the window, on a later date than the baseline. Thus, the follow-up is always inside the reporting window. This rule also works for fixed funder periods, for example six months or one year.
- For the longitudinal view, use the whole export span with `first_in_window`.
- For a fixed funder period, `pre_window` is usually better. It compares the status before the period with the status at the end of the period.

## 5. Who is counted

- **No baseline:** the patient is not in the cohort. In `pre_window` mode, the report counts patients who had a result inside the window but no baseline in the lookback period.
- **Baseline but no follow-up:** the patient stays in the cohort but is not classified. This patient shows as "No follow-up" in the outcome table, with all cohort patients as its denominator.
- **Paired patient:** has a baseline and a follow-up on different dates.
- **Cohort** (setting `cohort.mode`):
  - `lab_subgroup` (default): patients whose baseline A1C is at or above `subgroup_min_baseline` (default 6.5%). This group is based on a lab value. **It is not a confirmed diabetes diagnosis.**
  - `all_tested`: every patient with a baseline A1C.
- **Roster (optional):** if the clinic gives a list of eligible patients (`cohort.roster_file`), only those patients are used. The report shows how many roster patients have no usable A1C and how many never appear in the export.

## 6. The five outcomes

1. **Improved, stable, worsened.**
   - Change = follow-up minus baseline, in percentage points. The change is rounded to 0.01 to remove floating-point error.
   - With tolerance T, the outcome is:
     - improved: change below -T
     - worsened: change above +T
     - stable: anything else
   - **A change of exactly +T or -T counts as stable.**
   - The denominator is the paired patients.
2. **Control.** The target is A1C below the threshold (`<`) or at or below it (`<=`). The report shows these rows:
   - Latest result at target. Denominator: cohort patients with a result inside the window.
   - The same measure for paired patients only.
   - Reached target after an above-target baseline. The numerator is patients with any later documented result at target. The denominator is cohort patients whose baseline was not at target. **Patients whose baseline was already at target are not in this denominator.**
   - The same numerator over the above-target patients with at least one later result.
   - The number of above-target patients with no later result.
3. **Size of the change.** The change is first calculated for each patient. Then the report gives:
   - the median and the 25th to 75th percentiles for all paired patients
   - the median decrease among improved patients, with their count
   - the median increase among worsened patients, with their count
4. **Time to first documented control.**
   - The population is patients whose baseline was not at target.
   - The time is the number of days from the baseline date to the first later test at target.
   - The median is given **only for patients who reached control**, and is labelled that way.
   - Follow-up coverage is the share of these patients with any later result.
   - The Kaplan-Meier curve is **exploratory**. A patient without control is censored at the last result inside the window. Patients with no later result are not in the curve.
   - The curve stops when fewer than `km_min_at_risk` patients are still followed. The checkpoint table shows how many patients are still followed.
   - Control is seen only on test dates. The true date can be earlier, and tests are not at regular intervals. Thus, the times are upper limits.
5. **Outcomes by starting A1C.**
   - The groups come from `baseline_group_cutpoints`. Each group includes its lower value and excludes its upper value, so the groups do not overlap.
   - For each group, the report gives:
     - the patient count
     - follow-up coverage
     - median follow-up
     - median change and the middle half
     - outcome counts
   - Percentages are shown only when the group has at least `min_denominator` paired patients.

## 7. How to read the comparisons

- **Regression to the mean:** a patient with a very high value on one test is likely to have a lower value on the next test, even with no change in care. Thus, part of the large decrease in high starting groups is expected.
- **Unequal follow-up:** groups have different follow-up lengths and different numbers of tests. A group with longer follow-up has more chances to show control.
- **No causal claim:** these numbers describe what the lab results show. They do not show that clinic care caused the changes. There is no comparison group, and the export has no information about diagnoses, medicines or visits.

## 8. Small-count rule for shared outputs [`a1c/disclosure.py`]

The clinic has not given its disclosure rule yet. Until it does, shareable outputs (`--shareable`, or "Hide small counts" in the dashboard) use a **provisional** rule with the limit k = `min_cell_size` (default 11):

- A patient count from 1 to k-1 is hidden.
- In a set of counts that add up to a shown total, a second count is also hidden. Thus, the hidden value cannot be found by subtraction.
- In the patient flow, a step is hidden when it differs from the step above it by 1 to k-1.
- A percentage, median or quartile is hidden when its numerator is hidden or its denominator or sample is below k.
- Patient-level charts (change distribution, time-to-event curve, scatter plot) are left out.

This rule reduces risk. It does not prove that an output is safe. The clinic must approve every output before it leaves the approved environment.

## 9. Outputs

| Output | Contents | Where it can go |
|---|---|---|
| Dashboard with synthetic data | Invented patients | Anywhere |
| Report bundle, synthetic (`--demo`) | Invented patients | Anywhere |
| Report bundle, clinic data (internal) | Aggregate counts, small counts not hidden | Approved environment only |
| Report bundle, clinic data (`--shareable`) | Aggregate counts, small counts hidden | Only after clinic approval |
| `PRIVATE_*` files (`--row-level`), review log, scatter plot | Account numbers, dates, single patients | Approved environment only; never shared |
