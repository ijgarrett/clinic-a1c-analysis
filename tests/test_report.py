"""Settings changes reach the metrics, the charts and the exported settings together."""

import datetime as dt
import io
import json
import tomllib
import zipfile

import pytest

from a1c import synthetic
from a1c.config import EXAMPLE_CONFIG, Settings, load_settings, to_toml
from a1c.pipeline import run_pipeline
from a1c.report import build_report, bundle_files, bundle_zip, render_html

import a1c_report


@pytest.fixture(scope="module")
def demo_bytes():
    return synthetic.generate_export()


def _run(data, **changes):
    s = Settings(**changes)
    return run_pipeline(data, s, synthetic=True, source_name="demo")


def test_threshold_change_updates_everything(demo_bytes):
    a, b = _run(demo_bytes, control_threshold=7.0), _run(demo_bytes, control_threshold=8.0)
    ra, rb = build_report(a), build_report(b)
    assert ra.headline["latest_at_target"] < rb.headline["latest_at_target"]
    assert ra.tables["control"].frame.equals(rb.tables["control"].frame) is False
    ca = ra.charts["time_to_control"].to_dict()
    cb = rb.charts["time_to_control"].to_dict()
    assert "below 7%" in json.dumps(ca) and "below 8%" in json.dumps(cb)
    fb = bundle_files(rb, b)
    assert tomllib.loads(fb["settings_used.toml"].decode())["outcomes"]["control_threshold"] == 8.0
    assert "A1C below 8%" in fb["tables/control.csv"].decode("utf-8-sig")
    assert json.loads(fb["run_info.json"])["settings"]["control_threshold"] == 8.0
    assert "below 8%" in render_html(rb)


def test_window_change_updates_everything(demo_bytes):
    full = _run(demo_bytes)
    half = _run(demo_bytes, window_start=dt.date(2025, 7, 1), window_end=dt.date(2025, 12, 31),
                baseline_mode="pre_window")
    rf, rh = build_report(full), build_report(half)
    assert rh.headline["cohort"] != rf.headline["cohort"]
    p = half.outcomes.patients
    assert p["followup_date"].dropna().between("2025-07-01", "2025-12-31").all()
    assert p["baseline_date"].lt("2025-07-01").all()
    files = bundle_files(rh, half)
    assert "2025-07-01 to 2025-12-31" in files["tables/outcome_categories.csv"].decode("utf-8-sig")
    saved = tomllib.loads(files["settings_used.toml"].decode())
    assert str(saved["window"]["start"]) == "2025-07-01" and saved["window"]["baseline"] == "pre_window"
    assert set(half.outcomes.tests_per_year["year"]) == {2025}
    assert "2025 (6 months)" in json.dumps(rh.charts["tests_per_year"].to_dict())


def test_settings_round_trip(tmp_path):
    s = load_settings(EXAMPLE_CONFIG).with_changes(control_threshold=7.5, window_end=None)
    path = tmp_path / "s.toml"
    path.write_text(to_toml(s))
    back = load_settings(path)
    assert back.control_threshold == 7.5 and back.window_end is None
    assert back.provisional == s.provisional


def test_zip_bundle_has_no_row_level_files(demo_bytes):
    r = _run(demo_bytes)
    names = zipfile.ZipFile(io.BytesIO(bundle_zip(build_report(r), r))).namelist()
    assert "report.html" in names and "settings_used.toml" in names
    assert not any("PRIVATE" in n for n in names)


def test_cli_demo(tmp_path, capsys):
    code = a1c_report.main(["--demo", "--out", str(tmp_path / "demo"), "--control-threshold", "7.5"])
    assert code == 0
    html = (tmp_path / "demo" / "report.html").read_text(encoding="utf-8")
    assert "SYNTHETIC DEMO DATA" in html and "below 7.5%" in html
    assert (tmp_path / "demo" / "tables" / "by_baseline_group.csv").exists()
    out = capsys.readouterr().out
    assert "Cohort:" in out


def test_cli_refuses_row_level_shareable(tmp_path):
    assert a1c_report.main(["--demo", "--out", str(tmp_path), "--shareable", "--row-level"]) == 2
