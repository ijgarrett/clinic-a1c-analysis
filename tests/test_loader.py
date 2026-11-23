"""Parser tests with a realistic synthetic 5.02a export."""

import pytest

from a1c import synthetic
from a1c.config import Settings
from a1c.loader import read_export, select_a1c

from conftest import export_bytes


@pytest.fixture(scope="module")
def demo():
    return read_export(synthetic.generate_export(), name="demo")


def test_utf16_trailing_tab_alignment(demo):
    raw = demo.frame
    assert demo.encoding == "utf-16" and demo.separator == "\t"
    assert demo.rows_with_trailing_separator == len(raw)        # every data row had the extra tab
    assert len(raw.columns) == len(synthetic.HEADER)
    # Repeated header names get suffixes, as in the notebook.
    assert {"patient_acct_no", "patient_acct_no_1", "none", "none_1", "none_2"} <= set(raw.columns)
    # Column alignment: these columns hold the expected kinds of values on every row.
    assert raw["practice_name"].eq("Demo Free Clinic").all()
    assert raw["inhouse_lab"].eq("No").all()
    assert raw["aoe_lab_company_name"].eq("Demo Reference Lab").all()
    assert raw["order_collection_performed_date"].dropna().str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()


def test_ids_keep_leading_zeros(demo):
    ids = set(demo.frame["patient_acct_no"].dropna())
    assert {"00123", "00089", "00777"} <= ids


def test_id_columns_coalesced_and_conflicts_flagged(demo):
    rows = select_a1c(demo, Settings()).rows
    assert rows["id_conflict"].sum() == 1                      # one injected conflict
    assert rows["patient_id"].isna().sum() == 1                # one injected missing ID


def test_only_a1c_attributes_selected(demo):
    a1c = select_a1c(demo, Settings())
    assert set(a1c.rows["attribute"].str.casefold()) == {"hemoglobin a1c"}
    audit = a1c.label_audit.set_index("lab_attribute")
    assert not audit.loc["Est. Average Glucose", "kept_as_a1c"].any()
    assert "Hemoglobin" not in set(a1c.rows["attribute"])
    assert not audit.loc[audit.index.str.startswith("B-2-Glycoprotein"), "kept_as_a1c"].any()


def test_misaligned_row_is_an_error():
    data = export_bytes([("10001", "2024-01-01", "Hemoglobin A1c", "7.0")]).decode("utf-16")
    data = data.replace("Hemoglobin A1c\t7.0", "Hemoglobin A1c\textra\t7.0")
    with pytest.raises(ValueError, match="not aligned"):
        read_export(data.encode("utf-16"))


def test_utf8_without_trailing_tab_also_reads():
    data = export_bytes([("10001", "2024-01-01", "Hemoglobin A1c", "7.0")], trailing_tab=False, encoding="utf-8")
    e = read_export(data)
    assert e.encoding == "utf-8-sig" and e.rows_with_trailing_separator == 0
    assert e.frame.loc[0, "lab_attribute_value"] == "7.0"


def test_missing_columns_message():
    e = read_export("a\tb\n1\t2\n".encode("utf-8"))
    with pytest.raises(ValueError, match="Is this the 5.02a report"):
        select_a1c(e, Settings())


def test_not_a1c_labels_rejected():
    from a1c.config import check_settings
    with pytest.raises(ValueError, match="not A1C"):
        check_settings(Settings(a1c_labels=["Hemoglobin A1c", "Est. Average Glucose"]))
