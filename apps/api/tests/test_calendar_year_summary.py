"""ENH-017 / US-064 / FT-097 — calendar year summary.

The Year view reads per-day counts from ``GET /api/calendar/summary``. The
counts must equal what the month list (``/api/calendar/events``) shows for the
same dates, for every display type, under the same tenant, open-item and
ethical-wall scope. A summary that drifts from the list would show the lawyer
a dot on a day that opens empty, or hide a hearing that exists.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event

from caseops_api.db.models import Matter, MatterAccessGrant, MatterTask
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_calendar import _create_matter, _create_task, _schedule_hearing

YEAR = 2028  # leap year: Jan 1 - Dec 31 is 366 inclusive days.


def _deadline(
    client: TestClient, headers: dict[str, str], matter_id: str, on: date, kind: str
) -> str:
    resp = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=headers,
        json={"title": f"{kind} on {on.isoformat()}", "due_on": on.isoformat(), "kind": kind},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _month_list_counts(
    client: TestClient, headers: dict[str, str], start: date, end: date
) -> Counter[tuple[str, str]]:
    """Counts by (date, display_type) from the month list in <= 92-day windows."""
    counts: Counter[tuple[str, str]] = Counter()
    window_start = start
    while window_start <= end:
        window_end = min(window_start + timedelta(days=60), end)
        resp = client.get(
            "/api/calendar/events",
            headers=headers,
            params={"from": window_start.isoformat(), "to": window_end.isoformat()},
        )
        assert resp.status_code == 200, resp.text
        for row in resp.json()["events"]:
            counts[(row["occurs_on"], row["display_type"])] += 1
        window_start = window_end + timedelta(days=1)
    return counts


def _summary_counts(body: dict) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for day in body["days"]:
        assert day["total"] == sum(day["by_display_type"].values())
        for display_type, count in day["by_display_type"].items():
            counts[(day["occurs_on"], display_type)] += count
    return counts


def _summary(client: TestClient, headers: dict[str, str], start: date, end: date):
    return client.get(
        "/api/calendar/summary",
        headers=headers,
        params={"from": start.isoformat(), "to": end.isoformat()},
    )


def test_year_summary_matches_month_lists_for_every_type_and_day(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "YR-001", "Year parity matter")
    busy = date(YEAR, 9, 26)
    # Several events of several types on one day.
    _schedule_hearing(client, headers, matter_id, busy, "Final hearing")
    _schedule_hearing(client, headers, matter_id, busy, "Mention")
    _create_task(client, headers, matter_id, "Brief counsel", busy)
    _deadline(client, headers, matter_id, busy, "filing_due")
    # Every display type, spread over the four quarters and both year edges.
    _schedule_hearing(client, headers, matter_id, date(YEAR, 1, 1), "New year listing")
    _create_task(client, headers, matter_id, "Leap day task", date(YEAR, 2, 29))
    _deadline(client, headers, matter_id, date(YEAR, 4, 15), "internal_target")
    _deadline(client, headers, matter_id, date(YEAR, 5, 2), "renewal_due")
    _deadline(client, headers, matter_id, date(YEAR, 7, 9), "client_instruction")
    _deadline(client, headers, matter_id, date(YEAR, 8, 3), "reminder")
    _deadline(client, headers, matter_id, date(YEAR, 11, 11), "renewal_grace")
    _deadline(client, headers, matter_id, date(YEAR, 12, 31), "legal_deadline")
    # Outside the year: must not be counted.
    _schedule_hearing(client, headers, matter_id, date(YEAR + 1, 1, 1), "Next year")

    start, end = date(YEAR, 1, 1), date(YEAR, 12, 31)
    resp = _summary(client, headers, start, end)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["range_from"] == start.isoformat() and body["range_to"] == end.isoformat()

    summary = _summary_counts(body)
    month_lists = _month_list_counts(client, headers, start, end)
    assert summary == month_lists
    assert body["total"] == sum(month_lists.values()) == 12
    assert {display_type for _, display_type in summary} == {
        "hearing", "task_date", "filing_deadline", "internal_target",
        "renewal", "client_instruction", "reminder", "deadline",
    }
    busy_day = next(day for day in body["days"] if day["occurs_on"] == busy.isoformat())
    assert busy_day == {
        "occurs_on": busy.isoformat(),
        "total": 4,
        "by_display_type": {"hearing": 2, "task_date": 1, "filing_deadline": 1},
    }
    occurs = [day["occurs_on"] for day in body["days"]]
    assert occurs == sorted(occurs)


def test_year_summary_excludes_what_the_month_list_excludes(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    open_matter = _create_matter(client, headers, "YR-OPEN", "Open matter")
    day = date(YEAR, 3, 10)
    hearing_id = _schedule_hearing(client, headers, open_matter, day, "Will be completed")
    task_id = _create_task(client, headers, open_matter, "Will be completed", day)
    deadline_id = _deadline(client, headers, open_matter, day, "filing_due")
    _create_task(client, headers, open_matter, "Stays open", day)

    assert client.patch(
        f"/api/matters/{open_matter}/hearings/{hearing_id}", headers=headers,
        json={"status": "completed"},
    ).status_code == 200
    assert client.patch(
        f"/api/matters/{open_matter}/tasks/{task_id}", headers=headers,
        json={"status": "completed"},
    ).status_code == 200
    assert client.patch(
        f"/api/matters/{open_matter}/deadlines/{deadline_id}", headers=headers,
        json={"status": "done"},
    ).status_code == 200

    # Cancelled items are closed work too.
    cancelled_hearing = _schedule_hearing(client, headers, open_matter, day, "Will be cancelled")
    cancelled_task = _create_task(client, headers, open_matter, "Will be cancelled", day)
    cancelled_deadline = _deadline(client, headers, open_matter, day, "internal_target")
    for path in (f"hearings/{cancelled_hearing}", f"deadlines/{cancelled_deadline}"):
        assert client.patch(
            f"/api/matters/{open_matter}/{path}", headers=headers, json={"status": "cancelled"},
        ).status_code == 200, path

    # A legacy closed matter (closed implies inactive, by constraint) hides its
    # items as well. The task write API offers no "cancelled", but stored rows
    # can carry it, so both states are written directly.
    closed = _create_matter(client, headers, "YR-CLOSED", "Closed matter")
    _create_task(client, headers, closed, "On a closed matter", day)
    with get_session_factory()() as session:
        closed_row = session.get(Matter, closed)
        closed_row.status, closed_row.is_active = "closed", False
        session.get(MatterTask, cancelled_task).status = "cancelled"
        session.commit()

    disposed = _create_matter(client, headers, "YR-DISPOSED", "Disposed matter")
    _schedule_hearing(client, headers, disposed, day, "On a disposed matter")
    matter = client.get(f"/api/matters/{disposed}", headers=headers).json()
    assert client.patch(
        f"/api/matters/{disposed}/lifecycle/status", headers=headers,
        json={
            "to_status": "disposed", "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "Final judgment entered and all work concluded",
        },
    ).status_code == 200

    start, end = date(YEAR, 1, 1), date(YEAR, 12, 31)
    body = _summary(client, headers, start, end).json()
    assert _summary_counts(body) == _month_list_counts(client, headers, start, end)
    # Completing the hearing schedules its own follow-up task on a later day;
    # on the day itself only the still-open task remains.
    assert [row for row in body["days"] if row["occurs_on"] == day.isoformat()] == [
        {"occurs_on": day.isoformat(), "total": 1, "by_display_type": {"task_date": 1}}
    ]


def test_year_summary_range_limits(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    assert _summary(client, headers, date(YEAR, 1, 1), date(YEAR, 12, 31)).status_code == 200
    too_long = _summary(client, headers, date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
    assert too_long.status_code == 400
    assert "one year" in too_long.json()["detail"]
    inverted = _summary(client, headers, date(YEAR, 2, 1), date(YEAR, 1, 1))
    assert inverted.status_code == 400
    # The event list and .ics stay at 92 days.
    year_list = client.get(
        "/api/calendar/events", headers=headers,
        params={"from": f"{YEAR}-01-01", "to": f"{YEAR}-12-31"},
    )
    assert year_list.status_code == 400


def test_year_view_quarter_exports_are_distinct_calendars(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "YR-ICS", "Quarter export matter")
    _schedule_hearing(client, headers, matter_id, date(YEAR, 11, 20), "Q4 hearing")
    quarters = [
        (date(YEAR, 1, 1), date(YEAR, 3, 31)),
        (date(YEAR, 4, 1), date(YEAR, 6, 30)),
        (date(YEAR, 7, 1), date(YEAR, 9, 30)),
        (date(YEAR, 10, 1), date(YEAR, 12, 31)),
    ]
    names = []
    for start, end in quarters:
        resp = client.get(
            "/api/calendar/events.ics", headers=headers,
            params={"from": start.isoformat(), "to": end.isoformat()},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("text/calendar")
        assert resp.text.startswith("BEGIN:VCALENDAR")
        assert ("Q4 hearing" in resp.text) == (start.month == 10)
        names.append(resp.headers["content-disposition"])
    assert names[3] == (
        f'inline; filename="caseops-calendar-{YEAR}-10-01-to-{YEAR}-12-31.ics"'
    )
    assert len(set(names)) == 4


def test_year_summary_requires_authentication(client: TestClient) -> None:
    client.cookies.clear()
    resp = client.get(
        "/api/calendar/summary", params={"from": f"{YEAR}-01-01", "to": f"{YEAR}-12-31"}
    )
    assert resp.status_code == 401


def test_year_summary_never_counts_another_tenant(client: TestClient) -> None:
    company_a = bootstrap_company(client)
    headers_a = auth_headers(str(company_a["access_token"]))
    matter_a = _create_matter(client, headers_a, "YR-A", "Tenant A matter")
    _schedule_hearing(client, headers_a, matter_a, date(YEAR, 6, 1), "Tenant A hearing")
    client.cookies.clear()
    company_b = client.post("/api/bootstrap/company", json={
        "company_name": "Year Other LLP", "company_slug": "year-other-tenant",
        "company_type": "law_firm", "owner_full_name": "Other Owner",
        "owner_email": "owner@year-other.example", "owner_password": "YearOtherStrong!234",
    })
    assert company_b.status_code == 200, company_b.text
    headers_b = auth_headers(str(company_b.json()["access_token"]))
    matter_b = _create_matter(client, headers_b, "YR-B", "Tenant B matter")
    _schedule_hearing(client, headers_b, matter_b, date(YEAR, 6, 1), "Tenant B hearing")
    _schedule_hearing(client, headers_b, matter_b, date(YEAR, 6, 2), "Tenant B only")
    client.cookies.clear()

    body_a = _summary(client, headers_a, date(YEAR, 1, 1), date(YEAR, 12, 31)).json()
    assert body_a["days"] == [
        {"occurs_on": f"{YEAR}-06-01", "total": 1, "by_display_type": {"hearing": 1}}
    ]
    body_b = _summary(client, headers_b, date(YEAR, 1, 1), date(YEAR, 12, 31)).json()
    assert body_b["total"] == 2


def test_year_summary_honours_restricted_matter_visibility(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    owner_headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, owner_headers, "YR-WALL", "Restricted matter")
    _schedule_hearing(client, owner_headers, matter_id, date(YEAR, 4, 4), "Restricted hearing")
    created = client.post("/api/companies/current/users", headers=owner_headers, json={
        "full_name": "Walled Associate", "email": "walled@year-summary.example",
        "password": "WalledAssociate!234", "role": "member",
    })
    assert created.status_code == 200, created.text
    client.cookies.clear()
    login = client.post("/api/auth/login", json={
        "company_slug": bootstrap["company"]["slug"], "email": "walled@year-summary.example",
        "password": "WalledAssociate!234",
    })
    assert login.status_code == 200, login.text
    member_headers = auth_headers(str(login.json()["access_token"]))
    member_id = login.json()["membership"]["id"]
    client.cookies.clear()

    session_factory = get_session_factory()
    with session_factory() as session:
        session.get(Matter, matter_id).restricted_access = True
        session.commit()
    start, end = date(YEAR, 1, 1), date(YEAR, 12, 31)
    hidden = _summary(client, member_headers, start, end).json()
    assert hidden["days"] == [] and hidden["total"] == 0
    assert _month_list_counts(client, member_headers, start, end) == Counter()

    with session_factory() as session:
        session.add(MatterAccessGrant(
            company_id=bootstrap["company"]["id"], matter_id=matter_id, membership_id=member_id,
        ))
        session.commit()
    granted = _summary(client, member_headers, start, end).json()
    assert granted["total"] == 1
    assert _summary_counts(granted) == _month_list_counts(client, member_headers, start, end)


def test_year_summary_query_count_is_constant(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "YR-N1", "Query count matter")
    session_factory = get_session_factory()
    engine = session_factory.kw["bind"]

    def count_selects(n_rows: int) -> int:
        for offset in range(n_rows):
            due = date(YEAR, 1, 1) + timedelta(days=offset * 7)
            _create_task(client, headers, matter_id, f"Task {offset}", due)
        statements: list[str] = []

        def record(conn, cursor, statement, *args):  # noqa: ANN001
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            year = _summary(client, headers, date(YEAR, 1, 1), date(YEAR, 12, 31))
            assert year.status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(statements)

    assert count_selects(2) == count_selects(20)
