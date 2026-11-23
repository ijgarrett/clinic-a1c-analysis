"""Read an eClinicalWorks eBO 5.02a export and select the A1C rows.

The 5.02a CSV export is UTF-16 (with a byte order mark) and tab-separated.
Each data row ends with one extra tab, so data rows have one more field than
the header row. This reader removes that empty last field and stops with an
error if any row has a different number of fields. Thus the columns cannot
move out of line without notice. All values are read as text, so account
numbers keep any leading zeros.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import Settings

A1C_SEARCH_PATTERN = r"a1c|hba1|glycated|glycosylated|glyco|average glucose"


@dataclass
class Export:
    frame: pd.DataFrame
    name: str
    sha256: str
    encoding: str
    separator: str
    rows_with_trailing_separator: int


@dataclass
class A1CRows:
    rows: pd.DataFrame            # one row for each A1C result row in the export
    label_audit: pd.DataFrame     # candidate attribute/order names and whether they were kept
    id_columns: list[str]
    total_rows: int
    total_attributes: int
    total_patients_any_lab: int
    warnings: list[str] = field(default_factory=list)


def normalized_name(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _unique_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        base = normalized_name(name) or "column"
        if base in seen:
            seen[base] += 1
            out.append(f"{base}_{seen[base]}")
        else:
            seen[base] = 0
            out.append(base)
    return out


def read_export(source: str | Path | bytes, name: str | None = None,
                encoding: str | None = None, separator: str | None = None) -> Export:
    """Read a 5.02a export from a file path or from bytes (for example an upload)."""
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Export not found: {path}. Check data.input_file in the settings file.")
        data = path.read_bytes()
        name = name or path.name
    else:
        data = bytes(source)
        name = name or "uploaded export"
    if not data:
        raise ValueError(f"{name} is empty.")
    sha = hashlib.sha256(data).hexdigest()

    if encoding is None:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            encoding = "utf-16"
        else:
            encoding = "utf-8-sig"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(f"Cannot read {name} as {encoding}. Export the report again as CSV.") from exc

    lines = text.splitlines()
    if not lines:
        raise ValueError(f"{name} has no header row.")
    header_line = lines[0]
    if separator is None:
        counts = {d: header_line.count(d) for d in ("\t", ",", ";", "|")}
        separator = max(counts, key=counts.get)
        if counts[separator] == 0:
            raise ValueError(f"Cannot find the column separator in {name}.")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=separator)
    try:
        header = next(reader)
    except StopIteration as exc:  # pragma: no cover
        raise ValueError(f"{name} has no header row.") from exc
    width = len(header)
    records, trailing = [], 0
    for line_no, row in enumerate(reader, start=2):
        if not row or all(cell.strip() == "" for cell in row):
            continue  # blank line
        if len(row) == width + 1 and row[-1] == "":
            row = row[:-1]
            trailing += 1
        elif len(row) != width:
            raise ValueError(
                f"Line {line_no} of {name} has {len(row)} fields, but the header has {width}. "
                "The columns are not aligned. Do not edit the export by hand; export it again.")
        records.append(row)

    frame = pd.DataFrame(records, columns=_unique_names(header), dtype="string")
    frame = frame.replace("", pd.NA)
    return Export(frame, name, sha, encoding, separator, trailing)


def _clean_id(series: pd.Series) -> pd.Series:
    return (series.astype("string").str.strip()
            .str.replace(r"\.0$", "", regex=True).replace("", pd.NA))


def select_a1c(export: Export, settings: Settings) -> A1CRows:
    """Keep only rows whose Lab Attribute exactly matches an A1C label (case-insensitive)."""
    raw = export.frame
    needed = [settings.id_column, settings.date_column, settings.attribute_column,
              settings.value_column, settings.order_name_column]
    missing = [c for c in needed if c not in raw.columns]
    if missing:
        raise ValueError(f"The export does not have these columns: {missing}. "
                         f"Columns found: {list(raw.columns)}. Is this the 5.02a report?")

    attribute = raw[settings.attribute_column].astype("string").str.strip()
    order_name = raw[settings.order_name_column].astype("string").str.strip()
    status_col = settings.order_status_column
    order_status = (raw[status_col].astype("string").str.strip() if status_col in raw.columns
                    else pd.Series(pd.NA, index=raw.index, dtype="string"))

    labels = {x.strip().casefold() for x in settings.a1c_labels}
    selected = attribute.str.casefold().isin(labels).fillna(False).astype(bool)

    candidate = (attribute.str.contains(A1C_SEARCH_PATTERN, case=False, regex=True).fillna(False)
                 | order_name.str.contains(A1C_SEARCH_PATTERN, case=False, regex=True).fillna(False)
                 | selected).astype(bool)
    audit = (pd.DataFrame({"lab_attribute": attribute[candidate].fillna("(blank)"),
                           "order_name": order_name[candidate].fillna("(blank)")})
             .value_counts().rename("rows").reset_index())
    audit["kept_as_a1c"] = audit["lab_attribute"].str.casefold().isin(labels)
    audit = audit.sort_values(["kept_as_a1c", "rows"], ascending=[False, False]).reset_index(drop=True)

    pattern = re.compile(re.escape(settings.id_column) + r"(_\d+)?")
    id_columns = [c for c in raw.columns if pattern.fullmatch(c)]
    ids = pd.concat([_clean_id(raw[c]).rename(c) for c in id_columns], axis=1)
    patient_id = ids.bfill(axis=1).iloc[:, 0]
    id_conflict = ids.nunique(axis=1, dropna=True).gt(1)

    rows = pd.DataFrame({
        "source_row": range(1, len(raw) + 1),  # data row number in the export (header not counted)
        "patient_id": patient_id,
        "id_conflict": id_conflict,
        "date_text": raw[settings.date_column].astype("string").str.strip(),
        "attribute": attribute,
        "order_name": order_name,
        "order_status": order_status,
        "value_text": raw[settings.value_column].astype("string").str.strip(),
    })[selected.to_numpy()].reset_index(drop=True)

    warnings = []
    if rows.empty:
        warnings.append("No rows matched the A1C labels. Check data.a1c_labels against the label table.")
    return A1CRows(
        rows=rows,
        label_audit=audit,
        id_columns=id_columns,
        total_rows=len(raw),
        total_attributes=int(attribute.nunique()),
        total_patients_any_lab=int(patient_id.nunique()) if len(id_columns) else 0,
        warnings=warnings,
    )
