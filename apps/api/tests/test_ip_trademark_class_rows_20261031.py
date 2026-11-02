"""BUG-002: trademark class rows are validated against the Nice catalogue.

Every class the catalogue offers is accepted, every other value is refused
with a field-addressed message a lawyer can act on, and each stored row
records the Nice edition it was validated against. Legacy rows without an
edition stay readable.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.db.models import IpDocketRecord, IpTrademarkParticularVersion
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_imports import IpImportParticularPayload
from caseops_api.schemas.ip_operations import TrademarkParticularPayload
from caseops_api.services import ip_nice_classes as catalogue
from tests.test_auth_company import auth_headers, bootstrap_company

MANUAL = "/api/ip/trademark-applications/manual"


def _owner(client: TestClient) -> dict[str, str]:
    return auth_headers(str(bootstrap_company(client)["access_token"]))


def _manual_payload(classes: list[dict]) -> dict:
    return {
        "title": "Nice catalogue manual filing",
        "asset_title": "NICEMARK",
        "jurisdiction": "IN",
        "office": "IP India",
        "filing_phase": "draft",
        "source_pending_identifier_allocation": False,
        "application_number": None,
        "particulars": {
            "form_key": "TM-A",
            "form_version": "2026.1",
            "mark_kind": "word",
            "representation": {"text": "NICEMARK", "evidence_reference": "attachment:nice"},
            "classes": classes,
            "use_priority": None,
            "parties": [{"role": "applicant", "name": "Nice Applicant LLP"}],
            "agent": None,
            "filing_manifest": [],
        },
    }


def _docket_count() -> int:
    with get_session_factory()() as session:
        return len(session.scalars(select(IpDocketRecord.id)).all())


def test_multi_class_manual_application_persists_every_class_with_its_edition(
    client: TestClient,
) -> None:
    headers = _owner(client)

    created = client.post(
        MANUAL,
        headers=headers,
        json=_manual_payload(
            [
                {"class_number": 35, "specification": "Advertising; business management"},
                {"class_number": 9, "specification": "Downloadable software"},
            ]
        ),
    )

    assert created.status_code == 201, created.text
    docket_id = created.json()["docket"]["id"]
    read = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["current_particulars"]["classes_json"] == [
        {
            "class_number": 35,
            "specification": "Advertising; business management",
            "nice_edition": "NCL 13-2026",
        },
        {
            "class_number": 9,
            "specification": "Downloadable software",
            "nice_edition": "NCL 13-2026",
        },
    ]
    core = client.get(f"/api/ip/dockets/{docket_id}/core-records", headers=headers)
    assert core.status_code == 200, core.text
    assert len(core.json()["applications"]) == 1


@pytest.mark.parametrize(
    ("classes", "loc", "message"),
    [
        (
            [{"class_number": 0, "specification": "Legal services"}],
            ["body", "particulars", "classes", 0, "class_number"],
            "Class row 1: choose a Nice class between 1 and 45.",
        ),
        (
            [
                {"class_number": 45, "specification": "Legal services"},
                {"class_number": 46, "specification": "Legal services"},
            ],
            ["body", "particulars", "classes", 1, "class_number"],
            "Class row 2: choose a Nice class between 1 and 45.",
        ),
        (
            [
                {"class_number": 35, "specification": "Advertising"},
                {"class_number": 9, "specification": "Downloadable software"},
                {"class_number": 35, "specification": "Office functions"},
            ],
            ["body", "particulars", "classes", 2, "class_number"],
            "Class row 3: Nice class 35 is already listed in class row 1; list each class once.",
        ),
        (
            [{"class_number": 9.5, "specification": "Downloadable software"}],
            ["body", "particulars", "classes", 0, "class_number"],
            "Class row 1: choose a Nice class between 1 and 45.",
        ),
        (
            [{"class_number": "Class 9", "specification": "Downloadable software"}],
            ["body", "particulars", "classes", 0, "class_number"],
            "Class row 1: choose a Nice class between 1 and 45.",
        ),
        (
            [{"class_number": 9, "specification": ""}],
            ["body", "particulars", "classes", 0, "specification"],
            "Class row 1: describe the goods or services for Nice class 9 "
            "(at least 3 characters).",
        ),
        (
            [
                {
                    "class_number": 9,
                    "specification": "Downloadable software",
                    "nice_edition": "NCL 12-2025",
                }
            ],
            ["body", "particulars", "classes", 0, "nice_edition"],
            "Class row 1: only Nice edition NCL 13-2026 is supported.",
        ),
        (
            [],
            ["body", "particulars", "classes"],
            "Classes: add at least one Nice class.",
        ),
    ],
)
def test_invalid_class_rows_are_refused_with_field_addressed_messages(
    client: TestClient,
    classes: list[dict],
    loc: list,
    message: str,
) -> None:
    headers = _owner(client)
    before = _docket_count()

    refused = client.post(MANUAL, headers=headers, json=_manual_payload(classes))

    assert refused.status_code == 422, refused.text
    body = refused.json()
    # The problem detail prefixes the humanized field path (shared 422 contract);
    # the row message itself is the errors[] entry the form anchors to the field.
    assert [error["msg"] for error in body["errors"]] == [message]
    assert body["detail"].endswith(message)
    assert [error["loc"] for error in body["errors"]] == [loc]
    assert "Input should be" not in body["detail"]
    assert "Value error" not in body["detail"]
    assert _docket_count() == before


def test_every_catalogue_class_is_accepted_and_nothing_else_is() -> None:
    def payload(number: object) -> dict:
        return {
            "mark_kind": "word",
            "parties": [{"role": "applicant", "name": "Aster"}],
            "classes": [{"class_number": number, "specification": "Goods as listed"}],
        }

    for row in catalogue.NICE_CLASSES:
        accepted = TrademarkParticularPayload.model_validate(payload(row.number))
        assert accepted.classes[0].class_number == row.number
        assert accepted.classes[0].nice_edition == catalogue.NICE_EDITION
    for number in (0, 46, -1, 100, True, None, "", "45a", "٣"):
        with pytest.raises(ValidationError) as refused:
            TrademarkParticularPayload.model_validate(payload(number))
        assert [error["msg"] for error in refused.value.errors()] == [
            "Class row 1: choose a Nice class between 1 and 45."
        ]


def test_all_45_classes_in_one_application_are_accepted() -> None:
    accepted = TrademarkParticularPayload.model_validate(
        {
            "mark_kind": "word",
            "parties": [{"role": "applicant", "name": "Aster"}],
            "classes": [
                {"class_number": row.number, "specification": "Goods as listed"}
                for row in catalogue.NICE_CLASSES
            ],
        }
    )
    assert len(accepted.classes) == 45


def test_import_drafts_keep_their_source_incomplete_contract() -> None:
    """The bulk import path keeps accepting what it accepted before BUG-002."""
    base = {"mark_kind": "other", "parties": []}

    assert IpImportParticularPayload.model_validate({**base, "classes": []}).classes == []
    accepted = IpImportParticularPayload.model_validate(
        {**base, "classes": [{"class_number": 9, "specification": ""}]}
    )
    assert accepted.classes[0].model_dump() == {"class_number": 9, "specification": ""}
    with pytest.raises(ValidationError) as refused:
        IpImportParticularPayload.model_validate(
            {**base, "classes": [{"class_number": 9}, {"class_number": 9}]}
        )
    assert refused.value.errors()[0]["loc"] == ("classes", 1, "class_number")


def test_legacy_rows_without_an_edition_stay_readable_and_new_versions_record_it(
    client: TestClient,
) -> None:
    headers = _owner(client)
    created = client.post(
        MANUAL,
        headers=headers,
        json=_manual_payload([{"class_number": 30, "specification": "Biscuits"}]),
    )
    assert created.status_code == 201, created.text
    docket_id = created.json()["docket"]["id"]
    # Rows written before BUG-002 carry no edition.
    with get_session_factory()() as session:
        version = session.scalar(
            select(IpTrademarkParticularVersion).where(
                IpTrademarkParticularVersion.docket_id == docket_id
            )
        )
        assert version is not None
        version.classes_json = [{"class_number": 30, "specification": "Biscuits"}]
        session.commit()

    legacy = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["current_particulars"]["classes_json"] == [
        {"class_number": 30, "specification": "Biscuits"}
    ]

    particulars = _manual_payload([])["particulars"]
    particulars["classes"] = legacy.json()["current_particulars"]["classes_json"] + [
        {"class_number": 43, "specification": "Restaurant services"}
    ]
    appended = client.post(
        f"/api/ip/dockets/{docket_id}/versions",
        headers=headers,
        json={**particulars, "expected_current_version": 1},
    )
    assert appended.status_code == 200, appended.text
    assert appended.json()["current_particulars"]["classes_json"] == [
        {"class_number": 30, "specification": "Biscuits", "nice_edition": "NCL 13-2026"},
        {"class_number": 43, "specification": "Restaurant services", "nice_edition": "NCL 13-2026"},
    ]
