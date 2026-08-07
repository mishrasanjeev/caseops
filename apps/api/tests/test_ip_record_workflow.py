from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, IpDocketRecord, IpIdentifier
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _particulars(mark: str) -> dict:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {
            "text": mark,
            "evidence_reference": f"fixture:{mark.lower()}",
        },
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": "Fixture Applicant LLP"}],
        "agent": None,
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": f"fixture:{mark.lower()}",
            }
        ],
    }


def _bootstrap_tenant(
    client: TestClient,
    *,
    slug: str,
    email: str,
) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.replace("-", " ").title(),
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "IP Fixture Owner",
            "owner_email": email,
            "owner_password": "FixturePass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _docket(client: TestClient, headers: dict[str, str], title: str) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "restricted": False,
            "particulars": _particulars(title),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _asset(client: TestClient, headers: dict[str, str], docket_id: str, title: str) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket_id}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _application(
    client: TestClient,
    headers: dict[str, str],
    docket_id: str,
    asset_id: str,
) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket_id}/applications",
        headers=headers,
        json={
            "asset_id": asset_id,
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "draft",
            "source_pending_identifier_allocation": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["application"]


def test_identifier_workflow_preserves_types_history_search_and_duplicates(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    first_docket = _docket(client, headers, "ASTER")
    first_asset = _asset(client, headers, first_docket["id"], "ASTER")
    first_app = _application(client, headers, first_docket["id"], first_asset["id"])

    filed_without_number = client.patch(
        f"/api/ip/applications/{first_app['id']}/filing-phase",
        headers=headers,
        json={"expected_version": 1, "filing_phase": "filed"},
    )
    assert filed_without_number.status_code == 409
    assert "ip_application_identifier_required" in filed_without_number.text

    created_number = client.post(
        f"/api/ip/dockets/{first_docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": "TM / 123 / 2026",
            "office": "IP India",
            "jurisdiction": "IN",
            "source": "manual_fixture",
            "effective_from": "2026-08-07",
            "is_primary": True,
            "application_id": first_app["id"],
        },
    )
    assert created_number.status_code == 201, created_number.text
    first_number = created_number.json()["identifier"]
    assert first_number["raw_value"] == "TM / 123 / 2026"
    assert first_number["normalized_value"] == "tm1232026"
    assert first_number["reconciliation_status"] == "confirmed"

    search = client.get(
        "/api/ip/identifiers/search",
        headers=headers,
        params={"q": "tm-123 2026"},
    )
    assert search.status_code == 200, search.text
    assert [row["raw_value"] for row in search.json()] == ["TM / 123 / 2026"]

    second_docket = _docket(client, headers, "ASTER PLUS")
    second_asset = _asset(client, headers, second_docket["id"], "ASTER PLUS")
    second_app = _application(client, headers, second_docket["id"], second_asset["id"])
    duplicate = client.post(
        f"/api/ip/dockets/{second_docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": "tm.123.2026",
            "office": "IP India",
            "jurisdiction": "IN",
            "source": "registry_fixture",
            "effective_from": "2026-08-07",
            "is_primary": True,
            "application_id": second_app["id"],
        },
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["identifier"]["reconciliation_status"] == "needs_review"
    assert [row["id"] for row in duplicate.json()["duplicate_candidates"]] == [
        first_number["id"]
    ]
    assert second_app["id"] != first_app["id"]

    proceeding = client.post(
        f"/api/ip/dockets/{first_docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": first_app["id"],
            "proceeding_kind": "opposition",
            "side": "applicant",
            "office": "Trade Marks Registry Mumbai",
            "jurisdiction": "IN",
            "stage": "notice",
        },
    )
    assert proceeding.status_code == 201, proceeding.text
    proceeding_id = proceeding.json()["id"]
    opposition = client.post(
        f"/api/ip/dockets/{first_docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "opposition",
            "raw_value": "OPP-88-2026",
            "office": "Trade Marks Registry Mumbai",
            "jurisdiction": "IN",
            "source": "registry_fixture",
            "effective_from": "2026-08-07",
            "is_primary": True,
            "proceeding_id": proceeding_id,
        },
    )
    assert opposition.status_code == 201, opposition.text
    assert opposition.json()["identifier"]["application_id"] is None
    assert opposition.json()["identifier"]["proceeding_id"] == proceeding_id

    invalid_owner = client.post(
        f"/api/ip/dockets/{first_docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "opposition",
            "raw_value": "OPP-WRONG",
            "office": "IP India",
            "jurisdiction": "IN",
            "source": "manual_fixture",
            "effective_from": "2026-08-07",
            "is_primary": False,
            "application_id": first_app["id"],
        },
    )
    assert invalid_owner.status_code == 422

    correction = client.post(
        f"/api/ip/dockets/{first_docket['id']}/identifiers/{first_number['id']}/corrections",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": "TM/123A/2026",
            "office": "IP India",
            "jurisdiction": "IN",
            "source": "registry_correction_fixture",
            "effective_from": "2026-08-08",
            "is_primary": True,
            "application_id": first_app["id"],
            "supersedes_identifier_id": first_number["id"],
            "correction_reason": "Registry corrected the suffix.",
        },
    )
    assert correction.status_code == 201, correction.text
    corrected = correction.json()["identifier"]
    assert corrected["supersedes_identifier_id"] == first_number["id"]
    assert corrected["correction_reason"] == "Registry corrected the suffix."

    core = client.get(
        f"/api/ip/dockets/{first_docket['id']}/core-records",
        headers=headers,
    )
    assert core.status_code == 200, core.text
    identifiers = {row["id"]: row for row in core.json()["identifiers"]}
    assert identifiers[first_number["id"]]["raw_value"] == "TM / 123 / 2026"
    assert identifiers[first_number["id"]]["effective_until"] == "2026-08-08"
    assert identifiers[corrected["id"]]["raw_value"] == "TM/123A/2026"

    filed = client.patch(
        f"/api/ip/applications/{first_app['id']}/filing-phase",
        headers=headers,
        json={"expected_version": 1, "filing_phase": "filed"},
    )
    assert filed.status_code == 200, filed.text
    assert filed.json()["filing_phase"] == "filed"
    assert filed.json()["version"] == 2

    with get_session_factory()() as session:
        all_rows = list(
            session.scalars(
                select(IpIdentifier).where(IpIdentifier.company_id == company_id)
            ).all()
        )
        assert len(all_rows) == 4
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.company_id == company_id)
            ).all()
        )
    assert {
        "ip_asset.created",
        "ip_application.created",
        "ip_proceeding.created",
        "ip_identifier.created",
        "ip_identifier.corrected",
        "ip_application.phase_changed",
    }.issubset(actions)


def test_identifier_search_is_tenant_scoped(client: TestClient) -> None:
    first = _bootstrap_tenant(client, email="ip-a@example.com", slug="ip-a")
    first_headers = auth_headers(str(first["access_token"]))
    docket = _docket(client, first_headers, "TENANT A MARK")
    asset = _asset(client, first_headers, docket["id"], "TENANT A MARK")
    application = _application(client, first_headers, docket["id"], asset["id"])
    created = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=first_headers,
        json={
            "identifier_kind": "application",
            "raw_value": "SECRET-2026-1",
            "office": "IP India",
            "jurisdiction": "IN",
            "source": "fixture",
            "effective_from": str(date(2026, 8, 7)),
            "is_primary": True,
            "application_id": application["id"],
        },
    )
    assert created.status_code == 201

    with get_session_factory()() as session:
        stored_docket = session.get(IpDocketRecord, docket["id"])
        assert stored_docket is not None
        stored_docket.restricted = True
        session.commit()

    restricted = client.get(
        "/api/ip/identifiers/search",
        headers=first_headers,
        params={"q": "secret 2026 1"},
    )
    assert restricted.status_code == 200
    assert restricted.json() == []

    second = _bootstrap_tenant(client, email="ip-b@example.com", slug="ip-b")
    second_headers = auth_headers(str(second["access_token"]))
    hidden = client.get(
        "/api/ip/identifiers/search",
        headers=second_headers,
        params={"q": "secret 2026 1"},
    )
    assert hidden.status_code == 200
    assert hidden.json() == []
