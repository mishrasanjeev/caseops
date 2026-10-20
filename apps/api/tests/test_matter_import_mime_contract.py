from __future__ import annotations

from typing import NoReturn, get_type_hints
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from caseops_api.services import matter_imports


def test_bad_request_helper_always_raises_http_400() -> None:
    with pytest.raises(HTTPException) as caught:
        matter_imports._raise_bad_request("Unsupported import input.")

    assert caught.value.status_code == 400
    assert caught.value.detail == "Unsupported import input."


def test_bad_request_helper_declares_no_return_path() -> None:
    assert get_type_hints(matter_imports._raise_bad_request)["return"] is NoReturn


@pytest.mark.parametrize(
    ("filename", "content_type", "detail"),
    [
        (
            "matters.pdf",
            "text/csv",
            "Unsupported matter import file type. Upload CSV, JSON, or XLSX.",
        ),
        (
            "matters.csv.zip",
            "text/csv",
            "Unsupported matter import file type. Upload CSV, JSON, or XLSX.",
        ),
        (
            "matters",
            "text/csv",
            "Unsupported matter import file type. Upload CSV, JSON, or XLSX.",
        ),
        ("matters.csv", "application/json", "Unsupported matter import CSV MIME type."),
        ("matters.json", "text/csv", "Unsupported matter import JSON MIME type."),
        ("matters.xlsx", "text/csv", "Unsupported matter import XLSX MIME type."),
    ],
)
def test_invalid_file_type_or_mime_rejects_before_any_parser(
    filename: str,
    content_type: str,
    detail: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parsers = [
        Mock(side_effect=AssertionError("Rejected input reached a parser.")) for _ in range(3)
    ]
    for name, parser in zip(("_parse_csv", "_parse_json", "_parse_xlsx"), parsers, strict=True):
        monkeypatch.setattr(matter_imports, name, parser)

    with pytest.raises(HTTPException) as caught:
        matter_imports.parse_matter_import_mapping(
            filename=filename,
            content_type=content_type,
            content=b"Matter Title,Matter Code\nExample,MIME-1\n",
        )

    assert caught.value.status_code == 400
    assert caught.value.detail == detail
    for parser in parsers:
        parser.assert_not_called()


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("matters.CSV", " TEXT/CSV; charset=utf-8", "csv"),
        ("matters.JSON", "APPLICATION/JSON; charset=utf-8", "json"),
        (
            "matters.XLSX",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xlsx",
        ),
    ],
)
def test_matching_mime_and_extension_remain_accepted(
    filename: str,
    content_type: str,
    expected: str,
) -> None:
    assert matter_imports._detect_mapping_kind(filename, content_type) == expected
