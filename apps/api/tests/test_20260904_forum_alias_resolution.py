from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def test_forum_resolver_keeps_court_complex_and_consumer_families_distinct(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    district = client.get(
        "/api/courts/forum-catalog/resolve",
        headers=auth_headers(token),
        params={"query": " Tis-Hazari Court "},
    )
    assert district.status_code == 200, district.text
    assert district.json()["status"] == "ambiguous"
    assert district.json()["resolved_entry"] is None
    assert {entry["id"] for entry in district.json()["candidates"]} == {
        "district:india-gov:delhi:centraldelhi",
        "district:india-gov:delhi:westdelhi",
    }

    consumer = client.get(
        "/api/courts/forum-catalog/resolve",
        headers=auth_headers(token),
        params={"query": "Tis Hazari DCDRC"},
    )
    assert consumer.status_code == 200, consumer.text
    assert consumer.json()["status"] == "resolved"
    assert consumer.json()["resolved_entry"]["id"] == ("consumer:dcdrc:delhi:tis-hazari")
    assert consumer.json()["resolved_entry"]["forum_level"] == "tribunal"


def test_manual_matter_entry_resolves_the_same_reviewed_alias_as_bulk(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Saket alias manual entry",
            "matter_code": "SEP04-SAKET",
            "client_name": "Acme Industries",
            "opposing_party": "Beta Projects",
            "status": "intake",
            "practice_area": "Commercial Litigation",
            "forum_level": "lower_court",
            "court_name": "saket-court",
            "forum_district": "South Delhi",
        },
    )
    assert response.status_code == 200, response.text
    matter = response.json()
    assert matter["forum_catalog_entry_id"] == "district:india-gov:delhi:southdelhi"
    assert matter["court_name"] == "South District Court, New Delhi"
    assert matter["forum_state"] == "Delhi"
    assert matter["forum_district"] == "South Delhi"


def test_unknown_alias_is_not_invented_by_server_resolver(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    response = client.get(
        "/api/courts/forum-catalog/resolve",
        headers=auth_headers(token),
        params={"query": "Imaginary All India Court"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "not_found",
        "normalized_query": "imaginaryallindia",
        "resolved_entry": None,
        "candidates": [],
    }


def test_canonical_court_name_normalization_matches_alias_rules(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    response = client.get(
        "/api/courts/forum-catalog/resolve",
        headers=auth_headers(token),
        params={"query": "Central District Court Delhi"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    assert response.json()["resolved_entry"]["id"] == ("district:india-gov:delhi:centraldelhi")
