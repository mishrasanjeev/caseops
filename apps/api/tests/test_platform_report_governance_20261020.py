from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from caseops_api.governance import generated_data_class_projection as compiled
from caseops_api.governance.data_class_projection import (
    require_admissible_data_class,
    reset_projection_state_cache,
)

ROOT = Path(__file__).resolve().parents[3]
TABLES = (
    "platform_report_admins",
    "platform_console_sessions",
    "platform_console_tokens",
    "platform_console_deliveries",
    "platform_report_audit_events",
)
LINK_CLASS = "platform-console-account-link-delivery"


def _map() -> dict:
    return json.loads(
        (ROOT / "docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize("name", TABLES)
def test_console_security_tables_have_explicit_protected_owners(name: str) -> None:
    data = _map()
    row = next(row for row in data["sql_tables"] if row["table_name"] == name)
    assert row["policy_profile_id"] == "security_identity_control"
    assert row["disposition_handler_id"] == "registry_fail_closed"
    assert row["purpose"] == data["table_purpose_overrides"][name]
    assert name in compiled.INVENTORIED_SQL_TABLES


@pytest.mark.parametrize("name", (*TABLES, LINK_CLASS))
def test_reporting_grants_do_not_authorize_security_record_disposition(name: str) -> None:
    reset_projection_state_cache()
    try:
        with pytest.raises(HTTPException) as error:
            require_admissible_data_class(name)
        assert error.value.detail["type"] == "data_class_registered_but_not_reviewed"
    finally:
        reset_projection_state_cache()


def test_credential_fingerprints_are_not_generic_lifecycle_evidence() -> None:
    rows = {row["table_name"]: row for row in _map()["sql_tables"]}
    for table, names in (
        (
            "platform_console_sessions",
            ("secret_hash", "csrf_hash", "credential_hash", "factor_hash"),
        ),
        ("platform_console_tokens", ("token_hash", "credential_hash")),
        ("platform_console_deliveries", ("claim_hash",)),
        ("platform_report_admins", ("encrypted_totp_secret", "recovery_code_hashes")),
    ):
        for name in names:
            assert rows[table]["columns"][name]["category_id"] == "security_secret_or_credential"
    assert rows["platform_report_audit_events"]["columns"]["reason"]["category_id"] == (
        "privileged_or_raw_content"
    )


def test_mail_link_disclosure_is_separate_from_report_bodies_and_retention() -> None:
    row = next(row for row in _map()["non_sql_data_classes"] if row["id"] == LINK_CLASS)
    assert row["sensitivity"] == "restricted_authentication_link_and_personal_contact_data"
    assert row["tenant_configurable"] is False
    assert row["disposition_handler_id"] == "registry_fail_closed"
    assert row["status"] == "inventory_registered_runtime_policy_unapproved"
    assert "not deleted by link expiry" in row["default_retention"]
    assert "not a residency guarantee" in row["region_subprocessor"]
    assert "not delivery" in row["source_licence_limits"]
    assert "cannot be automatically replayed" in row["source_licence_limits"]
    assert "No raw password, TOTP secret, recovery code, client content" in row["purpose"]
    assert LINK_CLASS in compiled.INVENTORIED_NON_SQL_CLASSES
