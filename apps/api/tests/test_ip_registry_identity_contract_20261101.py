"""B4-ADJ-12: the registry identity writer validates the identifier kind and
answers a target outside the docket with a field-anchored 422.

``identifier_kind`` is the same vocabulary as IP identifiers (application and
registration numbers belong to an application; proceeding numbers to a
proceeding). A target that is not a record of the docket in the URL, whether
it belongs to another docket or does not exist, is a 422
``registry_target_not_in_docket`` on the target field, never a 404 that reads
like the docket itself is missing.
"""

from __future__ import annotations

from typing import get_args

from fastapi.testclient import TestClient

from caseops_api.schemas.ip_registry import IpRegistryIdentifierKind
from caseops_api.services.ip_identifier_rules import IP_IDENTIFIER_KINDS
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_authorities import _bootstrap_second_company
from tests.test_ip_registry_docket_eligibility_20261031 import (
    _link_body,
    _link_count,
    _national,
)


def _post(client: TestClient, headers: dict[str, str], docket_id: str, body: dict):
    return client.post(f"/api/ip/dockets/{docket_id}/registry-links", headers=headers, json=body)


def _proceeding(client: TestClient, headers: dict[str, str], docket_id: str, application_id: str):
    response = client.post(
        f"/api/ip/dockets/{docket_id}/proceedings",
        headers=headers,
        json={
            "application_id": application_id,
            "proceeding_kind": "opposition",
            "side": "applicant",
            "office": "Trade Marks Registry Mumbai",
            "jurisdiction": "IN",
            "stage": "draft",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_registry_identifier_kind_is_the_ip_identifier_vocabulary() -> None:
    assert set(get_args(IpRegistryIdentifierKind)) == set(IP_IDENTIFIER_KINDS)


def test_free_text_and_mismatched_identifier_kinds_are_field_anchored_422(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    headers = auth_headers(str(bootstrap["access_token"]))
    docket, application = _national(client, headers, "KIND MARK")
    proceeding = _proceeding(client, headers, docket["id"], application["id"])

    unknown = _post(
        client,
        headers,
        docket["id"],
        {**_link_body(application_id=application["id"]), "identifier_kind": "trademark_number"},
    )
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["errors"][0]["loc"][:2] == ["body", "identifier_kind"]

    # An application target cannot carry a proceeding number, nor the reverse.
    for body in (
        {**_link_body(application_id=application["id"]), "identifier_kind": "opposition"},
        {
            **_link_body(application_id=application["id"]),
            "application_id": None,
            "proceeding_id": proceeding["id"],
            "identifier_kind": "registration",
        },
    ):
        refused = _post(client, headers, docket["id"], body)
        assert refused.status_code == 422, refused.text
        error = refused.json()["errors"][0]
        assert error["loc"] == ["body", "identifier_kind"]
        assert error["type"] == "registry_identifier_kind_mismatch"
    assert _link_count(company_id) == 0

    accepted = _post(
        client,
        headers,
        docket["id"],
        {
            **_link_body(application_id=application["id"]),
            "application_id": None,
            "proceeding_id": proceeding["id"],
            "identifier_kind": "opposition",
            "raw_identifier": "OPP 88 2026",
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["identifier_kind"] == "opposition"
    assert _link_count(company_id) == 1


def test_cross_docket_and_unknown_targets_are_registry_target_not_in_docket(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    headers = auth_headers(str(bootstrap["access_token"]))
    pine, pine_application = _national(client, headers, "PINE MARK")
    aster, aster_application = _national(client, headers, "ASTER MARK")
    pine_proceeding = _proceeding(client, headers, pine["id"], pine_application["id"])

    cases = (
        ("application_id", _link_body(application_id=pine_application["id"])),
        ("application_id", _link_body(application_id="00000000-0000-4000-8000-000000000000")),
        (
            "proceeding_id",
            {
                **_link_body(application_id=pine_application["id"]),
                "application_id": None,
                "proceeding_id": pine_proceeding["id"],
                "identifier_kind": "opposition",
            },
        ),
    )
    for field, body in cases:
        refused = _post(client, headers, aster["id"], body)
        assert refused.status_code == 422, refused.text
        error = refused.json()["errors"][0]
        assert error["loc"] == ["body", field]
        assert error["type"] == "registry_target_not_in_docket"
        assert "this docket" in error["msg"]
    assert _link_count(company_id) == 0

    accepted = _post(client, headers, aster["id"], _link_body(application_id=aster_application["id"]))
    assert accepted.status_code == 201, accepted.text


def test_other_tenant_target_reads_the_same_as_any_record_outside_the_docket(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    first_headers = auth_headers(str(first["access_token"]))
    _docket, first_application = _national(client, first_headers, "FIRST MARK")
    second = _bootstrap_second_company(client)
    second_headers = auth_headers(str(second["access_token"]))
    second_docket, _second_application = _national(client, second_headers, "SECOND MARK")

    refused = _post(
        client, second_headers, second_docket["id"], _link_body(application_id=first_application["id"])
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["errors"][0]["type"] == "registry_target_not_in_docket"
    assert _link_count(str(second["company"]["id"])) == 0
    assert _link_count(str(first["company"]["id"])) == 0
