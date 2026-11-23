# Staff runbook: A1C outcome report

Use this runbook to refresh the A1C report and to change its settings. Do these steps on the clinic-approved computer. For installation, see `README.md`.

## A. Refresh the report with a new export

1. In eBO, run **5.02a Lab Results Analysis Report**. Export it as CSV.
   - Do not open the file in Excel and save it again. Excel can change the format.
2. Copy the file into the `data/` folder of the project.
3. Open `config/a1c_settings.toml` in a text editor.
   - Make sure that `input_file` has the new file name.
   - Set `end` under `[window]` to the export date (for example `2027-02-28`), or to `"auto"`.
   - If `approved_keep_rows` or `excluded_source_rows` has numbers, remove them. Row numbers apply to one export only. Approve the rows again for the new file.
4. Open a terminal in the project folder and start the dashboard:
   ```bash
   source .venv-wsl/bin/activate
   streamlit run dashboard.py
   ```
5. In the sidebar, choose **Clinic export (path in settings file)**.
6. Do these checks before you use the numbers:
   - The banner says **CLINIC DATA - INTERNAL REVIEW ONLY**.
   - In **Methods and data quality**, look at **Data quality**. Compare the counts with the last refresh. A large change can mean a different report or a filter in eBO.
   - Look at the **A1C label check**. If eBO shows a new A1C name, add it to `a1c_labels` in the settings file.
   - Open **Warnings** under the PROVISIONAL settings box and read each warning.
7. To save the report, go to the **Export** tab and click **Download report bundle**. You can also run the command line:
   ```bash
   python a1c_report.py --config config/a1c_settings.toml --out outputs/report_$(date +%F)
   ```
8. Keep the report in the approved environment. To share it outside the clinic, see part D.

## B. Make a funder report for a fixed period

1. In the sidebar, under **Reporting period**, choose **Last 6 months of export**, **Last 12 months of export**, **One calendar year** or **Custom dates**.
2. Under **Baseline**, choose one of these:
   - **Latest A1C before the window.** Use this for most funder periods. It compares the status before the period with the status at the end of the period. Set the lookback (365 days is the default).
   - **First A1C inside the window.** Both tests must be inside the period. For a short period, few patients have two tests.
3. Read the patient flow. It shows how many patients had no baseline or no follow-up.
4. Export the bundle. The window and the baseline rule are printed on every file.

## C. Change a setting

- **To try a setting:** change it in the sidebar. All numbers, charts and exports change together. The change is temporary; **Reset to settings file** brings back the file values.
- **To keep a setting:** do one of these:
  - Go to the **Export** tab, click **Download these settings**, and save the file as `config/a1c_settings.toml`.
  - Edit `config/a1c_settings.toml` in a text editor. The comments in the file explain each setting.
- **When the clinic approves a setting:** remove its key from the `[provisional]` list at the end of the file. The PROVISIONAL warning then stops listing it.
- **To keep a row from a conflicting same-day group:**
  1. Find the row in **Rows for review**. This view needs **Show patient-level views**.
  2. Get clinic approval for the row.
  3. Add its `source_row` number to `approved_keep_rows`.
- **To exclude a row:**
  1. Get clinic approval.
  2. Add the `source_row` number to `excluded_source_rows`.
  3. Write the reason in `exclusion_reason`. The software stops if there is no reason.
- If a setting cannot work (for example, cutpoints that do not increase), the dashboard shows a red message and no numbers.

## D. Share results outside the approved environment

1. Turn on **Hide small counts (for sharing)** in the sidebar. You can also use `--shareable` on the command line.
2. Check the banner. It must say **SMALL COUNTS SUPPRESSED**.
3. Download the bundle from the **Export** tab.
4. Get clinic approval before you send it. The small-count rule is provisional until the clinic confirms its own rule.
5. Never share `PRIVATE_*` files, the review log, the scatter plot or the notebooks.

## E. Problems and fixes

| Problem | Fix |
|---|---|
| "Line N has X fields, but the header has Y" | The file was edited or saved by another program. Export it from eBO again. |
| "The export does not have these columns" | The file is not the 5.02a report, or eBO changed the column names. Check the report name. |
| "No rows matched the A1C labels" | Look at the label check table. Add the A1C name to `a1c_labels`. |
| The dashboard says no patients match | Use a longer window, choose **All tested patients**, or lower the subgroup value. |
| Charts in the HTML file do not show | The HTML report needs an internet connection to draw charts. The tables have the same numbers. |
| `streamlit: command not found` | Run `source .venv-wsl/bin/activate` first. |
| A test fails after you update a package | Go back to the versions in `requirements.txt`. |
