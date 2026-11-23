# Clinic A1C outcomes

A reusable A1C outcome report and dashboard for the Free Clinic of Powhatan (BioKind A1C team). It reads the eClinicalWorks eBO **5.02a Lab Results Analysis Report** and calculates five outcomes:

1. Patients whose A1C improved, stayed stable or worsened
2. Control: latest result at target, and patients who reached target after an above-target start
3. Size of the change
4. Time to first documented control
5. Outcomes by starting A1C group

The same settings work for the whole history (about four years) and for fixed funder periods, for example six months or one year. Blood pressure, cancer screening and attendance are separate projects.

**The dashboard opens with SYNTHETIC demo data.** You do not need clinic data to install it, run the tests or show the demo.

## Data safety

- Clinic exports go in `data/`. Reports from clinic data go in `outputs/`. Git ignores both folders (and all `*.csv`). Do not commit clinic data or outputs.
- Reports from clinic data are labelled **CLINIC DATA - INTERNAL REVIEW ONLY**. Keep them in the clinic-approved environment.
- The clinic has not given its small-count rule yet. The `--shareable` option (and "Hide small counts" in the dashboard) applies a **provisional** rule that hides counts below 11. The clinic must approve any output before it is shared.
- Row-level files (`PRIVATE_*`), the review log and the scatter plot show single patients. They stay in the approved environment.
- `.streamlit/config.toml` turns off Streamlit usage statistics and lets only this computer connect to the dashboard.
- The notebooks (`a1c_preliminary_analysis*.ipynb`) contain saved outputs from clinic data. Treat them as internal.

## Project layout

| Path | What it is |
|---|---|
| `dashboard.py` | Streamlit dashboard |
| `a1c_report.py` | Command-line report (HTML, CSV tables, settings) |
| `a1c/` | Shared analysis modules (loader, cleaning, outcomes, disclosure, charts, report, synthetic data) |
| `config/a1c_settings.example.toml` | Example settings with comments. Copy to `config/a1c_settings.toml` to change them. |
| `tests/` | Tests, including a hand-calculated fixture |
| `docs/METHODS.md` | Every rule: dates, baseline, follow-up, outcomes, small counts |
| `docs/RUNBOOK.md` | Staff steps: refresh the report, change settings |
| `docs/review_brief_*.md` | Internal review briefs. They contain clinic aggregates, so they stay local (git ignores them). |
| `a1c_preliminary_analysis_502a.ipynb` | The November 16 notebook (kept as is) |

## Install (WSL Ubuntu)

Run these in an Ubuntu (WSL) terminal. Change the first line to the folder of your clone.

```bash
cd /mnt/c/Users/<you>/workspace/biokind/free_clinic_of_powhatan/clinic_a1c
sudo apt install -y python3-venv          # only if the next line says venv is missing
python3 -m venv .venv-wsl
source .venv-wsl/bin/activate
pip install -r requirements.txt
```

The folder `.venv-wsl` keeps the WSL install apart from a Windows `.venv`. Each time you open a new terminal, run `source .venv-wsl/bin/activate` again.

## Run the tests

```bash
source .venv-wsl/bin/activate
python -m pytest
```

The tests use only synthetic data. They check:
- the parser
- date boundaries
- duplicates
- threshold equality and tolerance boundaries
- missing follow-up and empty cohorts
- control denominators and first documented control
- small-count suppression
- that a settings change reaches the metrics, the charts and the exported settings
- the dashboard itself

## Launch the demo dashboard

```bash
source .venv-wsl/bin/activate
streamlit run dashboard.py
```

Open <http://localhost:8501> in a browser on the same computer. The page opens with synthetic data. Stop it with `Ctrl+C`.

## Open a new clinic export

1. In eBO, run **5.02a Lab Results Analysis Report** and export it as CSV. Do not open and re-save it in Excel.
2. Save it in `data/`, for example `data/5.02a - Lab Results Analysis Report.csv`.
3. Make your settings file (one time only), then edit it:
   ```bash
   cp config/a1c_settings.example.toml config/a1c_settings.toml
   ```
   Set `data.input_file` to the file name and `window.end` to the export date.
4. Dashboard: `streamlit run dashboard.py`, then choose **Clinic export (path in settings file)** in the sidebar. You can also choose **Upload a 5.02a export**.
5. Command-line report:
   ```bash
   python a1c_report.py --config config/a1c_settings.toml --out outputs/report_$(date +%F)
   ```
   Open `outputs/report_<date>/report.html`.

More command-line examples:

```bash
# Synthetic demo report (safe to share)
python a1c_report.py --demo --out outputs/demo_report

# Funder period: calendar year 2025, baseline = latest A1C in the year before
python a1c_report.py --config config/a1c_settings.toml --start 2025-01-01 --end 2025-12-31 \
    --baseline pre_window --lookback-days 365 --out outputs/funder_2025

# All tested patients instead of the lab-based subgroup
python a1c_report.py --config config/a1c_settings.toml --cohort all_tested --out outputs/all_tested

# Version with small counts hidden (needs clinic approval before sharing)
python a1c_report.py --config config/a1c_settings.toml --shareable --out outputs/shareable

# Cross-check against the old 5.02b extract (internal only)
python a1c_report.py --config config/a1c_settings.toml \
    --compare-502b "data/5.02b - Lab Results Analysis Report for Numeric Lab Values (1).csv" --out outputs/check_502b
```

`python a1c_report.py --help` lists every option.

## Windows PowerShell (no WSL)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest
streamlit run dashboard.py
```

## Share the work with the team lead

- **Screen share (simplest):** run `streamlit run dashboard.py` and share the browser window. The demo shows synthetic data only. Show clinic data on a screen share only if the clinic allows it.
- **Private repository:** the team lead clones the repository and follows "Install" and "Launch the demo dashboard". No clinic data is in the repository, so the dashboard opens with synthetic data.
- **One file:** send `outputs/demo_report/report.html` (made with `--demo`). It is synthetic. The charts need an internet connection to draw; the tables do not.
