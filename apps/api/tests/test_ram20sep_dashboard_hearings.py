from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import Matter
from caseops_api.db.session import get_session_factory
from caseops_api.services.next_hearing import apply_next_hearing_update
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(
    client: TestClient,
    token: str,
    code: str,
    *,
    status: str = "active",
    next_hearing_on: date | None = None,
) -> dict:
    payload = {
        "title": f"Ram 20 Sep matter {code}",
        "matter_code": code,
        "practice_area": "Civil",
        "forum_level": "high_court",
        "status": status,
        "description": "Dashboard and hearing regression fixture.",
        "court_name": "Delhi High Court",
        "client_name": "Regression Client",
        "opposing_party": "Regression Opponent",
    }
    if next_hearing_on is not None:
        payload["next_hearing_on"] = next_hearing_on.isoformat()
    response = client.post("/api/matters/", headers=auth_headers(token), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_dashboard_summary_counts_visible_matters_beyond_first_page(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    hearing_day = date.today() + timedelta(days=3)

    for index in range(55):
        _create_matter(
            client,
            token,
            f"RAM20-A-{index:02d}",
            next_hearing_on=hearing_day if index < 8 else None,
        )
    for index in range(7):
        _create_matter(client, token, f"RAM20-I-{index:02d}", status="intake")

    first_page = client.get("/api/matters/?limit=50", headers=auth_headers(token))
    assert first_page.status_code == 200, first_page.text
    assert len(first_page.json()["matters"]) == 50
    assert first_page.json()["next_cursor"] is not None

    summary = client.get("/api/matters/dashboard-summary", headers=auth_headers(token))
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total_visible_count"] == 62
    assert body["active_matters_count"] == 55
    assert body["intake_matters_count"] == 7
    assert body["hearings_next_7_days_count"] == 8
    assert body["upcoming_hearings_total_count"] == 8


def test_hearing_portfolio_exact_date_filter_uses_next_hearing_date(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    target_day = date.today() + timedelta(days=10)
    other_day = target_day + timedelta(days=1)
    exact_a = _create_matter(client, token, "RAM20-HF-A", next_hearing_on=target_day)
    exact_b = _create_matter(client, token, "RAM20-HF-B", next_hearing_on=target_day)
    _create_matter(client, token, "RAM20-HF-C", next_hearing_on=other_day)

    response = client.get(
        f"/api/matters/hearing-portfolio?date={target_day.isoformat()}",
        headers=auth_headers(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_count"] == 2
    assert body["truncated"] is False
    assert {matter["id"] for matter in body["matters"]} == {exact_a["id"], exact_b["id"]}
    assert {matter["next_hearing_on"] for matter in body["matters"]} == {
        target_day.isoformat()
    }


def test_hearing_follow_up_lists_active_overdue_and_missing_dates(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    overdue = _create_matter(
        client,
        token,
        "RAM20-FU-OD",
        next_hearing_on=date.today() - timedelta(days=1),
    )
    missing = _create_matter(client, token, "RAM20-FU-MISS")
    _create_matter(
        client,
        token,
        "RAM20-FU-INTAKE",
        status="intake",
        next_hearing_on=date.today() - timedelta(days=2),
    )

    response = client.get("/api/matters/hearing-follow-up", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overdue_count"] == 1
    assert body["missing_date_count"] == 1
    assert [matter["id"] for matter in body["overdue_matters"]] == [overdue["id"]]
    assert [matter["id"] for matter in body["missing_date_matters"]] == [missing["id"]]


def test_provider_next_hearing_update_materializes_calendar_hearing(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, "RAM20-CAL-A")
    hearing_day = date.today() + timedelta(days=14)

    factory = get_session_factory()
    session = factory()
    try:
        row = session.scalar(select(Matter).where(Matter.id == matter["id"]))
        assert row is not None
        result = apply_next_hearing_update(
            session,
            matter=row,
            new_date=hearing_day,
            source="ecourtsindia",
            source_ref_type="tracked_case",
            source_ref_id="provider-case-ram20",
            reason="provider_sync",
            authoritative_automatic=True,
        )
        assert result.applied is True
        session.commit()
    finally:
        session.close()

    events = client.get(
        (
            "/api/calendar/events"
            f"?from={hearing_day.isoformat()}&to={hearing_day.isoformat()}&kinds=hearing"
        ),
        headers=auth_headers(token),
    )
    assert events.status_code == 200, events.text
    hearing_events = events.json()["events"]
    assert len(hearing_events) == 1
    assert hearing_events[0]["matter_id"] == matter["id"]
    assert hearing_events[0]["occurs_on"] == hearing_day.isoformat()
    assert hearing_events[0]["detail"] == "Delhi High Court"
