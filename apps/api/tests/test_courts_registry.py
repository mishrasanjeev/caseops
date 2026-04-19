"""§7.1 — courts master table + read-only routes."""
from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def test_courts_listing_returns_seeded_rows(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get("/api/courts/", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = {court["name"] for court in body["courts"]}
    # The migration seeds these seven — all present after auto_migrate.
    assert {
        "Supreme Court of India",
        "Delhi High Court",
        "Bombay High Court",
        "Madras High Court",
        "Karnataka High Court",
        "Telangana High Court",
        "Patna High Court",
    } <= names


def test_courts_listing_respects_forum_level_filter(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/courts/?forum_level=high_court", headers=auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(court["forum_level"] == "high_court" for court in body["courts"])
    # None of the returned rows is the Supreme Court.
    assert all(court["short_name"] != "SC" for court in body["courts"])


def test_courts_listing_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/courts/")
    assert resp.status_code == 401
    body = resp.json()
    assert body["type"] == "missing_bearer_token"


def test_judges_endpoint_returns_empty_list_when_none_seeded(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    courts_resp = client.get("/api/courts/", headers=auth_headers(token))
    sc_id = next(
        c["id"] for c in courts_resp.json()["courts"] if c["short_name"] == "SC"
    )
    resp = client.get(
        f"/api/courts/{sc_id}/judges", headers=auth_headers(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["court_id"] == sc_id
    assert body["judges"] == []


def test_judge_profile_returns_404_for_unknown_judge(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/courts/judges/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(token),
    )
    assert resp.status_code == 404
    assert "judge not found" in resp.json()["detail"].lower()


def test_judge_profile_returns_full_shape_when_seeded(client: TestClient) -> None:
    """Seed a Judge directly in the test DB so the route returns 200.

    The registry is empty by default in test fixtures; we don't want
    the test to depend on production seed scripts running. Inserting
    a single Judge proves the contract end-to-end.
    """
    from caseops_api.db.models import Court, Judge
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])

    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        sc_court = session.query(Court).filter_by(short_name="SC").first()
        assert sc_court is not None
        judge = Judge(
            court_id=sc_court.id,
            full_name="Justice Test Judge",
            honorific="Hon'ble",
            current_position="Puisne Judge",
            is_active=True,
        )
        session.add(judge)
        session.commit()
        judge_id = judge.id

    resp = client.get(
        f"/api/courts/judges/{judge_id}", headers=auth_headers(token)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["judge"]["id"] == judge_id
    assert body["judge"]["full_name"] == "Justice Test Judge"
    assert body["court"]["short_name"] == "SC"
    assert body["portfolio_matter_count"] == 0
    assert body["authority_document_count"] >= 0
    assert isinstance(body["recent_authorities"], list)
