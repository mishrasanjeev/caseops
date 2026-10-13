from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from caseops_api.db.models import ForumCatalogEntry
from caseops_api.db.session import get_engine, get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def test_calendar_uses_catalog_order_and_stored_court_identity(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    today = date.today().isoformat()
    # Deliberately not lexical, statutory or Calendar-local order.
    entries = [
        ("cal-dc", "Regional Court Complex", "district_court", "lower_court", 9),
        ("cal-hc", "Configured High Court, Stored Bench", "high_court", "high_court", 3),
        ("cal-sc", "Configured Supreme Court", "supreme_court", "supreme_court", 7),
        ("cal-tribunal", "Configured Tribunal", "tribunal", "tribunal", 12),
    ]
    with get_session_factory()() as session:
        for key, name, kind, level, order in entries:
            session.add(
                ForumCatalogEntry(
                    id=key,
                    name=name,
                    normalized_name=name.casefold(),
                    forum_type=kind,
                    forum_level=level,
                    state="Stored State" if kind in {"district_court", "high_court"} else None,
                    district="Stored Region" if kind == "district_court" else None,
                    city="Stored Complex" if kind == "district_court" else None,
                    source_name="Isolated test fixture",
                    lineage=name,
                    display_order=order,
                )
            )
        session.commit()
    expected_ids = {}
    for key, _, _, level, _ in entries:
        created = client.post(
            "/api/matters",
            headers=headers,
            json={
                "matter_code": key,
                "title": key,
                "practice_area": "Civil",
                "forum_catalog_entry_id": key,
                "court_forum_number": "Court 7",
                "forum_level": level,
            },
        )
        assert created.status_code == 200, created.text
        matter_id = created.json()["id"]
        hearing = client.post(
            f"/api/matters/{matter_id}/hearings",
            headers=headers,
            json={
                "hearing_on": today,
                "forum_name": "Retained hearing venue",
                "purpose": "Next hearing",
                "time_status": "exact",
                "hearing_time": "10:30:00",
                "timezone": "Asia/Kolkata",
            },
        )
        assert hearing.status_code == 200, hearing.text
        expected_ids[key] = f"hearing:{hearing.json()['id']}"
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        if "forum_catalog_entries" in statement:
            statements.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(
            "/api/calendar/events", headers=headers, params={"from": today, "to": today}
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert response.status_code == 200, response.text
    rows = response.json()["events"]
    assert [row["id"] for row in rows] == [
        expected_ids[k] for k in ["cal-hc", "cal-sc", "cal-dc", "cal-tribunal"]
    ]
    assert len(statements) == 1
    assert "matter_hearings" in statements[0]
    assert rows[0]["court_label"] == "HC - Configured High Court, Stored Bench"
    assert rows[1]["court_label"] == "SC - Configured Supreme Court"
    assert rows[2]["court_label"] == "DC - Stored Region, Regional Court Complex"
    assert (
        rows[2]["court_identity"]
        == "Stored Region, Regional Court Complex, Stored Complex, Court 7"
    )
    assert rows[3]["court_label"] == "Configured Tribunal"
    assert all(row["hearing_time"] == "10:30:00" for row in rows)
    assert all(row["timezone"] == "Asia/Kolkata" for row in rows)
    assert all(row["detail"] == "Retained hearing venue" for row in rows)


def test_legacy_hearing_has_no_invented_court_or_time(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    created = client.post(
        "/api/matters",
        headers=headers,
        json={
            "matter_code": "CAL-LEGACY",
            "title": "Unknown forum matter",
            "practice_area": "Civil",
            "forum_level": "arbitration",
        },
    )
    assert created.status_code == 200, created.text
    today = date.today().isoformat()
    hearing = client.post(
        f"/api/matters/{created.json()['id']}/hearings",
        headers=headers,
        json={
            "hearing_on": today,
            "forum_name": "Stored venue",
            "purpose": "Next hearing",
        },
    )
    assert hearing.status_code == 200, hearing.text
    rows = client.get(
        "/api/calendar/events", headers=headers, params={"from": today, "to": today}
    ).json()["events"]
    assert len(rows) == 1
    assert rows[0]["court_label"] == "Stored venue"
    assert rows[0]["court_identity"] == "Stored venue"
    assert rows[0]["forum_display_order"] is None
    assert rows[0]["hearing_time"] is None


@pytest.mark.postgres
def test_calendar_court_identity_on_postgres(isolated_postgres_client: TestClient) -> None:
    test_calendar_uses_catalog_order_and_stored_court_identity(isolated_postgres_client)


@pytest.mark.postgres
def test_legacy_calendar_court_identity_on_postgres(isolated_postgres_client: TestClient) -> None:
    test_legacy_hearing_has_no_invented_court_or_time(isolated_postgres_client)


def test_same_forum_time_ties_session_and_unknown_time_are_stable(client: TestClient) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    created = client.post(
        "/api/matters",
        headers=headers,
        json={
            "matter_code": "CAL-TIMES",
            "title": "Stored time ordering",
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
    )
    assert created.status_code == 200, created.text
    matter_id = created.json()["id"]
    today = date.today().isoformat()
    expected = []
    for clock in [None, "11:00:00", "09:00:00", "09:00:00"]:
        payload = {"hearing_on": today, "forum_name": "Stored venue", "purpose": "Listing"}
        if clock:
            payload.update(time_status="exact", hearing_time=clock)
        else:
            payload.update(time_status="session", session_label="Afternoon")
        saved = client.post(f"/api/matters/{matter_id}/hearings", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        expected.append((clock, f"hearing:{saved.json()['id']}"))
    params = {"from": today, "to": today}
    rows = client.get("/api/calendar/events", headers=headers, params=params).json()["events"]
    assert [row["id"] for row in rows] == [
        key
        for clock, key in sorted(
            expected, key=lambda pair: (pair[0] is None, pair[0] or "", pair[1])
        )
    ]
    assert rows[-1]["time_status"] == "session"
    assert rows[-1]["session_label"] == "Afternoon"
    assert rows[-1]["hearing_time"] is None
    assert all(row["session_label"] is None for row in rows[:-1])
    assert (
        client.get("/api/calendar/events", headers=headers, params=params).json()["events"] == rows
    )


@pytest.mark.postgres
def test_calendar_time_ties_on_postgres(isolated_postgres_client: TestClient) -> None:
    test_same_forum_time_ties_session_and_unknown_time_are_stable(isolated_postgres_client)
