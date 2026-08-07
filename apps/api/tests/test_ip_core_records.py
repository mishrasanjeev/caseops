from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import UniqueConstraint

from caseops_api.db.base import Base
from caseops_api.db.models import IpIdentifier, TrademarkApplication
from caseops_api.schemas.ip_records import IpIdentifierCorrectionCreate, IpIdentifierCreate
from caseops_api.services.ip_records import (
    assert_application_can_enter_filed_phase,
    normalize_ip_identifier,
)

EXPECTED_TABLES = {
    "ip_assets",
    "trademark_applications",
    "trademark_application_scopes",
    "trademark_representations",
    "ip_proceedings",
    "ip_identifiers",
    "ip_parties_and_roles",
    "ip_relationships",
}


def test_exact_ownership_ledger_tables_are_published() -> None:
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_every_core_child_has_company_scoped_anchor_foreign_key() -> None:
    for table_name in EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]
        assert "company_id" in table.c
        if table_name == "ip_relationships":
            assert {"source_docket_id", "target_docket_id"} <= set(table.c.keys())
        elif table_name not in {
            "trademark_application_scopes",
            "trademark_representations",
        }:
            assert "docket_id" in table.c


def test_identifier_collisions_are_indexed_but_not_silently_unique_merged() -> None:
    table = Base.metadata.tables["ip_identifiers"]
    unique_column_sets = {
        tuple(constraint.columns.keys())
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("company_id", "identifier_kind", "normalized_value") not in unique_column_sets
    assert "ix_ip_identifiers_company_search" in {index.name for index in table.indexes}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("TM-A / 123 456", "tma123456"),
        ("ＴＭ–Ａ–१२३", "tm" + "a" + "१२३"),
        ("  OPP.  99/2026 ", "opp992026"),
    ],
)
def test_identifier_normalization_accepts_spacing_and_punctuation_variants(
    raw: str, expected: str
) -> None:
    assert normalize_ip_identifier(raw) == expected


def test_identifier_contract_preserves_raw_and_computes_search_value() -> None:
    payload = IpIdentifierCreate(
        identifier_kind="application",
        raw_value="TM-A / 123 456",
        application_id="application-1",
        office="Trade Marks Registry Delhi",
        jurisdiction="IN",
        source="manual-docketing",
        effective_from=date(2026, 8, 7),
        is_primary=True,
    )
    assert payload.raw_value == "TM-A / 123 456"
    assert payload.normalized_value == "tma123456"


def test_opposition_identifier_cannot_be_stored_on_application() -> None:
    with pytest.raises(ValueError, match="belong only to a proceeding"):
        IpIdentifierCreate(
            identifier_kind="opposition",
            raw_value="OPP-1",
            application_id="application-1",
            office="Trade Marks Registry Delhi",
            jurisdiction="IN",
            source="manual-docketing",
            effective_from=date(2026, 8, 7),
        )


def test_identifier_correction_requires_reason_and_superseded_identity() -> None:
    correction = IpIdentifierCorrectionCreate(
        identifier_kind="registration",
        raw_value="REG-2",
        application_id="application-1",
        office="Trade Marks Registry Delhi",
        jurisdiction="IN",
        source="official-correction",
        effective_from=date(2026, 8, 7),
        supersedes_identifier_id="identifier-1",
        correction_reason="Official register corrected a transcription error.",
    )
    assert correction.supersedes_identifier_id == "identifier-1"


def test_filed_phase_requires_confirmed_application_number_unless_source_pending() -> None:
    application = TrademarkApplication(
        id="application-1",
        company_id="company-1",
        docket_id="docket-1",
        asset_id="asset-1",
        office="Trade Marks Registry Delhi",
        jurisdiction="IN",
        filing_phase="draft",
        source_pending_identifier_allocation=False,
    )
    with pytest.raises(HTTPException) as exc_info:
        assert_application_can_enter_filed_phase(application, [])
    assert exc_info.value.status_code == 409

    application.source_pending_identifier_allocation = True
    assert_application_can_enter_filed_phase(application, [])

    application.source_pending_identifier_allocation = False
    identifier = IpIdentifier(
        company_id="company-1",
        docket_id="docket-1",
        application_id="application-1",
        proceeding_id=None,
        identifier_kind="application",
        raw_value="TM-A-1",
        normalized_value="tma1",
        office="Trade Marks Registry Delhi",
        jurisdiction="IN",
        source="official",
        effective_from=date(2026, 8, 7),
        is_primary=True,
        reconciliation_status="confirmed",
    )
    assert_application_can_enter_filed_phase(application, [identifier])
