"""Explicit exports for the neutral IP file parser's shared metadata contract."""

from __future__ import annotations

import pytest

from caseops_api.services import ip_import_files
from caseops_api.services.ip_import_files import METADATA_FIELDS

PUBLIC_EXPORTS = (
    "MAX_IMPORT_BYTES",
    "MAX_IMPORT_ROWS",
    "MAX_IMPORT_COLUMNS",
    "MAX_EXPANDED_BYTES",
    "MAX_SOURCE_TEXT_BYTES",
    "HEADER_ALIASES",
    "METADATA_FIELDS",
    "normalize_header",
    "source_value",
    "parse_ip_import_file",
)


@pytest.mark.parametrize("name", PUBLIC_EXPORTS)
def test_owned_public_contract_is_explicitly_exported(name: str) -> None:
    assert name in ip_import_files.__all__
    assert hasattr(ip_import_files, name)


def test_exports_are_exact_unique_and_exclude_dependency_and_private_names() -> None:
    assert tuple(ip_import_files.__all__) == PUBLIC_EXPORTS
    assert len(ip_import_files.__all__) == len(set(ip_import_files.__all__))
    assert not any(name.startswith("_") for name in ip_import_files.__all__)


def test_named_metadata_export_preserves_the_complete_contract() -> None:
    assert METADATA_FIELDS is ip_import_files.METADATA_FIELDS
    assert METADATA_FIELDS == {
        "source_reference",
        "image_reference",
        "source_status",
        "comment",
        "takeover_request",
        "name_change_request",
        "address_change_request",
        "internal_remarks",
        "registration_number",
        "filing_number",
        "priority_date",
        "notes",
    }


def test_public_parser_limits_preserve_all_existing_values() -> None:
    assert (
        ip_import_files.MAX_IMPORT_BYTES,
        ip_import_files.MAX_IMPORT_ROWS,
        ip_import_files.MAX_IMPORT_COLUMNS,
        ip_import_files.MAX_EXPANDED_BYTES,
        ip_import_files.MAX_SOURCE_TEXT_BYTES,
    ) == (10 * 1024 * 1024, 1000, 100, 50 * 1024 * 1024, 10 * 1024 * 1024)


def test_exported_functions_are_defined_by_the_parser_module() -> None:
    for name in ("normalize_header", "source_value", "parse_ip_import_file"):
        function = getattr(ip_import_files, name)
        assert callable(function)
        assert function.__module__ == ip_import_files.__name__
