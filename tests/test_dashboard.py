"""Smoke tests that run the real dashboard script with Streamlit's test runner."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "dashboard.py")


def _metric(at, label):
    return next(m.value for m in at.metric if m.label == label)


@pytest.fixture
def app():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    return at


def test_demo_loads(app):
    assert app.title[0].value == "A1C outcomes"
    assert any("SYNTHETIC DEMO DATA" in i.value for i in app.info)
    assert any("PROVISIONAL" in w.value for w in app.warning)
    assert len(app.tabs) == 6
    assert _metric(app, "Cohort patients") not in ("", "0")


def test_threshold_change_updates_metrics(app):
    before = _metric(app, "Latest result at target")
    app.number_input(key="control_threshold").set_value(8.0).run()
    assert not app.exception
    after = _metric(app, "Latest result at target")
    assert before != after
    assert any("below 8%" in md.value for md in app.markdown)


def test_window_and_cohort_change(app):
    cohort_before = _metric(app, "Cohort patients")
    app.selectbox(key="period").set_value("Last 12 months of export").run()
    assert not app.exception
    app.radio(key="cohort_mode").set_value("all_tested").run()
    assert not app.exception
    assert _metric(app, "Cohort patients") != cohort_before
    assert any("All patients with a baseline A1C" in md.value for md in app.markdown)


def test_share_mode_and_empty_cohort(app):
    app.checkbox(key="share_mode").check().run()
    assert not app.exception
    assert any("SMALL COUNTS SUPPRESSED" in s.value for s in app.success) or \
        any("SYNTHETIC" in i.value for i in app.info)
    app.number_input(key="subgroup_min").set_value(19.5).run()
    assert not app.exception
    assert any("No patients match these settings" in i.value for i in app.info)


def test_bad_cutpoints_show_message(app):
    app.text_input(key="cutpoints").set_value("6.5, abc").run()
    assert any("cutpoints must be numbers" in e.value for e in app.error)
    app.text_input(key="cutpoints").set_value("8, 6.5").run()
    assert any("must increase" in e.value for e in app.error)
