from __future__ import annotations

import csv
import io

from caseops_api.services.csv_security import csv_bytes, csv_safe_cell, csv_safe_mapping


def test_csv_safe_cell_escapes_formula_prefixes_after_whitespace() -> None:
    assert csv_safe_cell("=HYPERLINK(\"https://evil.example\")").startswith("'=")
    assert csv_safe_cell(" +SUM(1,2)").startswith("' +")
    assert csv_safe_cell("\t@cmd").startswith("'\t@")
    assert csv_safe_cell("-10") == "'-10"
    assert csv_safe_cell(10) == "10"
    assert csv_safe_cell(None) == ""
    assert csv_safe_cell("ordinary text") == "ordinary text"


def test_csv_safe_mapping_and_bytes_escape_exported_values() -> None:
    row = csv_safe_mapping({"label": "@malicious", "count": 3})
    assert row == {"label": "'@malicious", "count": "3"}

    content = csv_bytes(["label", "count"], [["=1+1", 3]]).decode("utf-8")
    parsed = list(csv.DictReader(io.StringIO(content)))

    assert parsed == [{"label": "'=1+1", "count": "3"}]
