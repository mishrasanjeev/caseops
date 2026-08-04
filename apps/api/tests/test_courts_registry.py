"""§7.1 — courts master table + read-only routes."""
from __future__ import annotations

import json
from datetime import date

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


def test_judge_profile_returns_source_backed_descriptive_analytics(
    client: TestClient,
) -> None:
    from caseops_api.db.models import AuthorityDocument, Court, Judge
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        sc_court = session.query(Court).filter_by(short_name="SC").first()
        assert sc_court is not None
        judge = Judge(
            court_id=sc_court.id,
            full_name="Justice ADP Analytics",
            honorific="Hon'ble",
            current_position="Puisne Judge",
            is_active=True,
        )
        session.add(judge)
        session.flush()
        for index in range(5):
            session.add(
                AuthorityDocument(
                    source="adp06_test_source",
                    adapter_name="adp06-test-authorities-v1",
                    court_name=sc_court.name,
                    forum_level=sc_court.forum_level,
                    document_type="judgment",
                    title=f"Section 138 descriptive authority {index}",
                    case_reference=f"CRL.A. 13{index}/2026",
                    bench_name="Justice ADP Analytics",
                    neutral_citation=f"2026 INSC {index}",
                    decision_date=date(2026, 1, index + 1),
                    canonical_key=f"adp06-judge-analytics-{index}",
                    source_reference=(
                        f"https://official.example.test/adp06-{index}.pdf"
                    ),
                    summary=(
                        "Bounded source-backed summary for indexed authority "
                        "metadata only."
                    ),
                    document_text=(
                        "FULL JUDGMENT TEXT SHOULD NEVER BE RETURNED BY THE "
                        "COURT CONTEXT EXPLORER."
                    ),
                    extracted_char_count=2000,
                    judges_json=json.dumps(["ADP Analytics"]),
                    sections_cited_json=json.dumps(
                        ["Section 138 Negotiable Instruments Act"]
                    ),
                )
            )
        session.commit()
        judge_id = judge.id

    resp = client.get(
        f"/api/courts/judges/{judge_id}", headers=auth_headers(token)
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    analytics = body["analytics"]
    assert analytics["sample_size"] == 5
    assert analytics["sample_size_label"] == "descriptive"
    assert analytics["pattern_claims_suppressed"] is False
    assert analytics["case_list"]
    assert analytics["case_list"][0]["source_reference"].startswith(
        "https://official.example.test/adp06-"
    )
    assert analytics["case_list"][0]["source_action"]["target_type"] == (
        "authority_document"
    )
    assert analytics["case_list"][0]["source_action"]["target_id"]
    assert analytics["case_list"][0]["summary_preview"]
    assert "document_text" not in analytics["case_list"][0]
    assert any(
        item["label"] == "Negotiable Instruments Act"
        for item in analytics["statute_counts"]
    )
    assert any(
        item["label"] == "Supreme Court of India" and item["count"] == 5
        for item in analytics["court_counts"]
    )
    assert analytics["practice_area_trends"]

    response_text = json.dumps(analytics).casefold()
    for forbidden in (
        "best judge",
        "best bench",
        "best court",
        "most suitable judge",
        "success probability",
        "likely to win",
        "likely to lose",
        "favorable recommendation",
        "unfavorable recommendation",
        "judge reputation score",
        "judge shopping",
        "outcome prediction",
        "full judgment text should never be returned",
        "source_payload",
    ):
        assert forbidden not in response_text


def test_judge_profile_suppresses_pattern_language_for_low_sample(
    client: TestClient,
) -> None:
    from caseops_api.db.models import AuthorityDocument, Court, Judge
    from caseops_api.db.session import get_session_factory

    token = str(bootstrap_company(client)["access_token"])
    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        sc_court = session.query(Court).filter_by(short_name="SC").first()
        assert sc_court is not None
        judge = Judge(
            court_id=sc_court.id,
            full_name="Justice ADP Low Sample",
            honorific="Hon'ble",
            current_position="Puisne Judge",
            is_active=True,
        )
        session.add(judge)
        session.flush()
        session.add(
            AuthorityDocument(
                source="adp06_test_source",
                adapter_name="adp06-test-authorities-v1",
                court_name=sc_court.name,
                forum_level=sc_court.forum_level,
                document_type="judgment",
                title="Single descriptive authority",
                case_reference="CRL.A. 1/2026",
                bench_name="Justice ADP Low Sample",
                neutral_citation=None,
                decision_date=date(2026, 2, 1),
                canonical_key="adp06-low-sample-judge-analytics",
                source_reference="https://official.example.test/adp06-low.pdf",
                summary="One indexed authority is not enough for pattern language.",
                extracted_char_count=120,
                judges_json=json.dumps(["ADP Low Sample"]),
                sections_cited_json=json.dumps(["Section 438 CrPC"]),
            )
        )
        session.commit()
        judge_id = judge.id

    resp = client.get(
        f"/api/courts/judges/{judge_id}", headers=auth_headers(token)
    )

    assert resp.status_code == 200, resp.text
    analytics = resp.json()["analytics"]
    assert analytics["sample_size"] == 1
    assert analytics["sample_size_label"] == "insufficient"
    assert analytics["pattern_claims_suppressed"] is True
    assert analytics["practice_area_trends"] == []
    assert any("Sample size is below" in item for item in analytics["limitations"])
