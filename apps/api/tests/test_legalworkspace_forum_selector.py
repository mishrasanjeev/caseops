from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Matter
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _bootstrap_company(
    client: TestClient,
    *,
    slug: str,
    email: str,
) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Forum Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_matter(
    client: TestClient,
    token: str,
    *,
    code: str,
    forum_level: str,
    forum_catalog_entry_id: str | None = None,
    court_id: str | None = None,
    court_name: str | None = None,
    forum_state: str | None = None,
    forum_district: str | None = None,
    forum_city: str | None = None,
) -> dict:
    payload: dict[str, object] = {
        "title": f"Forum selector {code}",
        "matter_code": code,
        "client_name": "Acme Industries",
        "opposing_party": "Beta Projects",
        "status": "intake",
        "practice_area": "Commercial Litigation",
        "forum_level": forum_level,
    }
    if forum_catalog_entry_id is not None:
        payload["forum_catalog_entry_id"] = forum_catalog_entry_id
    if court_id is not None:
        payload["court_id"] = court_id
    if court_name is not None:
        payload["court_name"] = court_name
    if forum_state is not None:
        payload["forum_state"] = forum_state
    if forum_district is not None:
        payload["forum_district"] = forum_district
    if forum_city is not None:
        payload["forum_city"] = forum_city
    response = client.post("/api/matters/", headers=auth_headers(token), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_lw_s4_forum_catalog_returns_public_hierarchy(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])

    response = client.get("/api/courts/forum-catalog", headers=auth_headers(token))

    assert response.status_code == 200, response.text
    entries = {entry["id"]: entry for entry in response.json()["entries"]}
    assert "sc:india" in entries
    assert entries["sc:india"]["forum_type"] == "supreme_court"
    assert entries["sc:india"]["state"] is None
    assert entries["hc:delhi"]["forum_type"] == "high_court"
    assert entries["hc:delhi"]["state"] == "Delhi"
    assert entries["district:india-gov:delhi:centraldelhi"]["forum_level"] == "lower_court"
    assert (
        entries["district:india-gov:delhi:centraldelhi"]["name"] == "Central District Court, Delhi"
    )
    assert entries["district:india-gov:delhi:centraldelhi"]["district"] == "Central Delhi"
    assert (
        entries["district:india-gov:delhi:centraldelhi"]["source_name"]
        == "India.gov.in District Courts Contact Directory"
    )
    district_entries = [
        entry for entry in entries.values() if entry["forum_type"] == "district_court"
    ]
    assert len(district_entries) == 723
    assert all(
        entry["source_name"] == "India.gov.in District Courts Contact Directory"
        for entry in district_entries
    )
    delhi_districts = [
        entry
        for entry in entries.values()
        if entry["forum_type"] == "district_court" and entry["state"] == "Delhi"
    ]
    assert [entry["id"] for entry in delhi_districts] == [
        "district:india-gov:delhi:centraldelhi",
        "district:india-gov:delhi:northdelhi",
        "district:india-gov:delhi:rohini",
        "district:india-gov:delhi:southwestdelhi",
        "district:india-gov:delhi:eastdelhi",
        "district:india-gov:delhi:newdelhi",
        "district:india-gov:delhi:northeast",
        "district:india-gov:delhi:shahdara",
        "district:india-gov:delhi:southdelhi",
        "district:india-gov:delhi:southeastdelhi",
        "district:india-gov:delhi:westdelhi",
    ]
    assert {entry["name"] for entry in delhi_districts} == {
        "Central District Court, Delhi",
        "District Court North Delhi",
        "District Court North West Delhi",
        "Dwarka Court South West Delhi | India",
        "East District Court, Delhi",
        "New Delhi District Court, Delhi",
        "North East District Court, Delhi",
        "Shahdara District Court, Delhi",
        "South District Court, New Delhi",
        "South-East District Court, New Delhi",
        "West District Court, Delhi",
    }
    assert entries["consumer:ncdrc"]["consumer_level"] == "national"
    assert entries["consumer:scdrc:delhi"]["consumer_level"] == "state"
    assert entries["consumer:dcdrc:central-delhi"]["consumer_level"] == "district"
    assert entries["consumer:dcdrc:central-delhi"]["parent_id"] == "consumer:scdrc:delhi"
    assert all("company_id" not in entry for entry in entries.values())
    assert all(entry["source_name"] for entry in entries.values())
    assert all(entry["lineage"] for entry in entries.values())


def test_lw_s4_catalog_supports_required_forum_shapes(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])

    supreme = _create_matter(
        client,
        token,
        code="LW-S4-SC",
        forum_level="supreme_court",
        forum_catalog_entry_id="sc:india",
    )
    assert supreme["forum_level"] == "supreme_court"
    assert supreme["court_id"] == "supreme-court-india"
    assert supreme["court_name"] == "Supreme Court of India"
    assert supreme["forum_state"] is None

    high_court = _create_matter(
        client,
        token,
        code="LW-S4-HC",
        forum_level="high_court",
        forum_catalog_entry_id="hc:delhi",
    )
    assert high_court["court_id"] == "delhi-hc"
    assert high_court["court_name"] == "Delhi High Court"
    assert high_court["forum_state"] == "Delhi"

    mapped_high_court = _create_matter(
        client,
        token,
        code="LW-S4-HC-MAP",
        forum_level="high_court",
        forum_catalog_entry_id="hc:delhi",
        court_id="delhi-hc",
    )
    assert mapped_high_court["court_id"] == "delhi-hc"
    assert mapped_high_court["forum_catalog_entry_id"] == "hc:delhi"

    court_only = _create_matter(
        client,
        token,
        code="LW-S4-COURT",
        forum_level="high_court",
        court_id="delhi-hc",
    )
    assert court_only["court_id"] == "delhi-hc"
    assert court_only["court_name"] == "Delhi High Court"
    assert court_only["forum_catalog_entry_id"] is None
    assert court_only["forum_state"] == "Delhi"

    district = _create_matter(
        client,
        token,
        code="LW-S4-DIST",
        forum_level="lower_court",
        forum_catalog_entry_id="district:india-gov:delhi:southwestdelhi",
    )
    assert district["forum_level"] == "lower_court"
    assert district["court_id"] is None
    assert district["forum_state"] == "Delhi"
    assert district["court_name"] == "Dwarka Court South West Delhi | India"
    assert district["forum_district"] == "South West Delhi"
    assert district["forum_city"] is None

    uncatalogued_district = _create_matter(
        client,
        token,
        code="LW-S4-DIST-FALLBACK",
        forum_level="lower_court",
        court_name="Kamrup Metro District Court",
        forum_state="Assam",
        forum_district="Kamrup Metro",
    )
    assert uncatalogued_district["forum_level"] == "lower_court"
    assert uncatalogued_district["court_id"] is None
    assert uncatalogued_district["forum_catalog_entry_id"] is None
    assert uncatalogued_district["court_name"] == "Kamrup Metro District Court"
    assert uncatalogued_district["forum_state"] == "Assam"
    assert uncatalogued_district["forum_district"] == "Kamrup Metro"
    consumer = _create_matter(
        client,
        token,
        code="LW-S4-CONS",
        forum_level="tribunal",
        forum_catalog_entry_id="consumer:dcdrc:central-delhi",
    )
    assert consumer["forum_level"] == "tribunal"
    assert consumer["forum_consumer_level"] == "district"
    assert consumer["forum_district"] == "Central"


def test_lw_s4_rejects_mismatched_catalog_metadata_and_preserves_legacy_fallback(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])

    mismatch = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Bad forum mismatch",
            "matter_code": "LW-S4-BAD",
            "status": "intake",
            "practice_area": "Commercial",
            "forum_level": "supreme_court",
            "forum_catalog_entry_id": "hc:delhi",
        },
    )
    assert mismatch.status_code == 400, mismatch.text

    unmapped_court_spoof = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Bad unmapped catalog court spoof",
            "matter_code": "LW-S4-SPOOF-UNMAPPED",
            "status": "intake",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "forum_catalog_entry_id": "hc:calcutta",
            "court_id": "delhi-hc",
        },
    )
    assert unmapped_court_spoof.status_code == 400, unmapped_court_spoof.text

    mapped_court_spoof = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Bad mapped catalog court spoof",
            "matter_code": "LW-S4-SPOOF-MAPPED",
            "status": "intake",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "forum_catalog_entry_id": "hc:delhi",
            "court_id": "karnataka-hc",
        },
    )
    assert mapped_court_spoof.status_code == 400, mapped_court_spoof.text

    legacy = _create_matter(
        client,
        token,
        code="LW-S4-LEGACY",
        forum_level="arbitration",
        court_name="SIAC",
    )
    assert legacy["forum_level"] == "arbitration"
    assert legacy["court_name"] == "SIAC"
    assert legacy["forum_catalog_entry_id"] is None

    legacy_update = client.patch(
        f"/api/matters/{legacy['id']}",
        headers=auth_headers(token),
        json={
            "forum_level": "high_court",
            "court_id": "karnataka-hc",
            "court_name": "Karnataka High Court",
        },
    )
    assert legacy_update.status_code == 200, legacy_update.text
    updated_legacy = legacy_update.json()
    assert updated_legacy["court_id"] == "karnataka-hc"
    assert updated_legacy["court_name"] == "Karnataka High Court"
    assert updated_legacy["forum_catalog_entry_id"] is None


def test_lw_s4_forum_update_is_tenant_scoped_and_audited(
    client: TestClient,
) -> None:
    owner = _bootstrap_company(
        client,
        slug="lw-s4-owner",
        email="owner@lw-s4-owner.in",
    )
    owner_token = str(owner["access_token"])
    other = _bootstrap_company(
        client,
        slug="lw-s4-other",
        email="owner@lw-s4-other.in",
    )
    other_token = str(other["access_token"])
    matter = _create_matter(
        client,
        owner_token,
        code="LW-S4-UPD",
        forum_level="arbitration",
        court_name="SIAC",
    )

    blocked = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(other_token),
        json={"forum_catalog_entry_id": "hc:karnataka", "forum_level": "high_court"},
    )
    assert blocked.status_code == 404, blocked.text

    update = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(owner_token),
        json={"forum_catalog_entry_id": "hc:karnataka", "forum_level": "high_court"},
    )
    assert update.status_code == 200, update.text
    updated = update.json()
    assert updated["court_id"] == "karnataka-hc"
    assert updated["forum_state"] == "Karnataka"

    factory = get_session_factory()
    with factory() as session:
        persisted = session.scalar(select(Matter).where(Matter.id == matter["id"]))
        assert persisted is not None
        assert persisted.company_id == owner["company"]["id"]
        audit = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == owner["company"]["id"])
                .where(AuditEvent.action == "matter.forum.updated")
            )
        )
    assert len(audit) == 1
    metadata = json.loads(audit[0].metadata_json or "{}")
    assert metadata["before"]["court_name"] == "SIAC"
    assert metadata["after"]["forum_catalog_entry_id"] == "hc:karnataka"
