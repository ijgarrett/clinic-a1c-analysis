"""A1C outcome reporting for the Free Clinic of Powhatan.

The modules are shared by the dashboard (dashboard.py) and the
command-line report (a1c_report.py):

    config    -> settings file, validation, provisional markers
    loader    -> read the eBO 5.02a export and select the A1C rows
    cleaning  -> data-quality rules (IDs, dates, non-numeric results, duplicates)
    outcomes  -> baseline, follow-up and the five client outcomes
    disclosure-> small-count suppression for shareable outputs
    charts    -> Altair charts
    report    -> report tables, HTML report and export bundle
    synthetic -> synthetic 5.02a export for the demo and the tests
"""

from .pipeline import run_pipeline  # noqa: F401

__version__ = "1.0.0"
