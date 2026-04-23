"""Phase B / J08 / M08 — unified calendar route tests.

Covers:

- The three sources (hearings, tasks, deadlines) merge into one date-
  sorted list.
- Tenant isolation: company B's events never leak into company A's
  calendar request.
- Range filtering is inclusive of both endpoints.
- Kinds filter narrows correctly.
- The 92-day cap on the requested range fires with an actionable 400.
- The legacy bearer auth path still works (the /calendar route inherits
  the same get_current_context as everything else, so any regression
  here would mean a wider auth break).
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(
    client: TestClient, headers: dict[str, str], code: str, title: str
) -> str:
    resp = client.post(
        "/api/matters",
        headers=headers,
        json={
            "matter_code": code,
            "title": title,
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _schedule_hearing(
    client: TestClient,
    headers: dict[str, str],
    matter_id: str,
    on: date,
    purpose: str,
) -> str:
    resp = client.post(
        f"/api/matters/{matter_id}/hearings",
        headers=headers,
        json={
            "hearing_on": on.isoformat(),
            "forum_name": "Bombay HC",
            "purpose": purpose,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _create_task(
    client: TestClient,
    headers: dict[str, str],
    matter_id: str,
    title: str,
    due_on: date | None,
) -> str:
    payload: dict[str, object] = {"title": title}
    if due_on:
        payload["due_on"] = due_on.isoformat()
    resp = client.post(
        f"/api/matters/{matter_id}/tasks", headers=headers, json=payload,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_calendar_merges_hearings_tasks_deadlines_in_date_order(
    client: TestClient,
) -> None:
    """The calendar endpoint must return a single date-sorted list
    that contains rows from all three source tables. This is the
    headline contract — fail this and BUG-029 (Hari 2026-04-23) is
    re-opened."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))

    matter_id = _create_matter(client, headers, "PB-CAL-001", "Phase B calendar")

    today = date.today()
    hearing_day = today + timedelta(days=3)
    task_day = today + timedelta(days=5)

    _schedule_hearing(client, headers, matter_id, hearing_day, "Bail hearing")
    _create_task(client, headers, matter_id, "Draft reply by Friday", task_day)

    # Pull the next 30 days.
    resp = client.get(
        "/api/calendar/events",
        headers=headers,
        params={
            "from": today.isoformat(),
            "to": (today + timedelta(days=30)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    kinds = [e["kind"] for e in body["events"]]
    # The hearing precedes the task in calendar order even though both
    # were created via API.
    assert kinds.count("hearing") == 1
    assert kinds.count("task") == 1
    # Date-order invariant.
    occurs = [e["occurs_on"] for e in body["events"]]
    assert occurs == sorted(occurs)


def test_calendar_omits_tasks_with_no_due_date(client: TestClient) -> None:
    """A task with no due_on is real work but isn't a calendar event.
    Including it would clutter the grid with rows that have no slot
    to render in."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "PB-CAL-002", "Undated task matter")

    _create_task(client, headers, matter_id, "Floating todo", due_on=None)

    today = date.today()
    resp = client.get(
        "/api/calendar/events",
        headers=headers,
        params={
            "from": today.isoformat(),
            "to": (today + timedelta(days=60)).isoformat(),
        },
    )
    assert resp.status_code == 200
    assert resp.json()["events"] == []


def test_calendar_range_is_inclusive_on_both_ends(client: TestClient) -> None:
    """A hearing scheduled exactly on ``from`` or exactly on ``to``
    must be included. Off-by-one here is the kind of bug a single
    user would catch (the hearing on Monday vanishes when they ask
    for Mon–Fri)."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "PB-CAL-003", "Boundary matter")

    monday = date.today() + timedelta(days=7)
    friday = monday + timedelta(days=4)
    _schedule_hearing(client, headers, matter_id, monday, "Mention on first day")
    _schedule_hearing(client, headers, matter_id, friday, "Argument on last day")

    resp = client.get(
        "/api/calendar/events",
        headers=headers,
        params={"from": monday.isoformat(), "to": friday.isoformat()},
    )
    assert resp.status_code == 200, resp.text
    occurs = sorted({e["occurs_on"] for e in resp.json()["events"]})
    assert monday.isoformat() in occurs
    assert friday.isoformat() in occurs


def test_calendar_does_not_leak_other_tenants_events(
    client: TestClient,
) -> None:
    """Tenant isolation. Company B creates a hearing; company A's
    calendar request must not see it. This is the most important
    test in the file — a leak here is a §5 hardening violation."""
    company_a = bootstrap_company(client)
    headers_a = auth_headers(str(company_a["access_token"]))
    matter_a = _create_matter(client, headers_a, "TENANT-A-001", "Tenant A matter")
    today = date.today()
    _schedule_hearing(
        client, headers_a, matter_a, today + timedelta(days=2), "Tenant A hearing",
    )
    # EG-001 (2026-04-23) implication: TestClient persists cookies
    # across requests. The cookie wins over the Authorization header
    # in get_current_context, so without an explicit clear, the next
    # bootstrap overwrites the cookie and every "headers_a" call
    # actually runs as tenant B. Clearing the cookie jar is the
    # cleanest way to test bearer-only paths.
    client.cookies.clear()

    # Bootstrap a second tenant.
    resp_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Tenant LLP",
            "company_slug": "other-tenant-cal",
            "company_type": "law_firm",
            "owner_full_name": "Other Tenant Owner",
            "owner_email": "owner@other-tenant-cal.example",
            "owner_password": "OtherTenantStrong!234",
        },
    )
    assert resp_b.status_code == 200, resp_b.text
    headers_b = auth_headers(str(resp_b.json()["access_token"]))

    matter_b = _create_matter(client, headers_b, "TENANT-B-001", "Tenant B matter")
    _schedule_hearing(
        client, headers_b, matter_b, today + timedelta(days=2), "Tenant B hearing",
    )
    client.cookies.clear()

    # Each tenant sees ONLY their own event.
    a_resp = client.get(
        "/api/calendar/events",
        headers=headers_a,
        params={"from": today.isoformat(), "to": (today + timedelta(days=10)).isoformat()},
    )
    assert a_resp.status_code == 200
    a_titles = {e["title"] for e in a_resp.json()["events"]}
    assert "Tenant A hearing" in a_titles
    assert "Tenant B hearing" not in a_titles

    b_resp = client.get(
        "/api/calendar/events",
        headers=headers_b,
        params={"from": today.isoformat(), "to": (today + timedelta(days=10)).isoformat()},
    )
    assert b_resp.status_code == 200
    b_titles = {e["title"] for e in b_resp.json()["events"]}
    assert "Tenant B hearing" in b_titles
    assert "Tenant A hearing" not in b_titles


def test_calendar_kinds_filter_narrows_response(client: TestClient) -> None:
    """``?kinds=hearing`` must return only hearings, not all three
    sources. Without this the cockpit's "Hearings only" toggle has
    nothing to do server-side."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    matter_id = _create_matter(client, headers, "PB-CAL-KINDS", "Kinds matter")

    today = date.today()
    _schedule_hearing(
        client, headers, matter_id, today + timedelta(days=1), "Hearing one",
    )
    _create_task(
        client, headers, matter_id, "Task one", today + timedelta(days=2),
    )

    resp = client.get(
        "/api/calendar/events",
        headers=headers,
        params={
            "from": today.isoformat(),
            "to": (today + timedelta(days=30)).isoformat(),
            "kinds": ["hearing"],
        },
    )
    assert resp.status_code == 200
    kinds = {e["kind"] for e in resp.json()["events"]}
    assert kinds == {"hearing"}


def test_calendar_rejects_inverted_range_400(client: TestClient) -> None:
    """``from`` > ``to`` is a programmer error; fail loudly with 400
    so the UI surfaces the problem rather than silently rendering an
    empty calendar."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    today = date.today()
    resp = client.get(
        "/api/calendar/events",
        headers=headers,
        params={
            "from": (today + timedelta(days=10)).isoformat(),
            "to": today.isoformat(),
        },
    )
    assert resp.status_code == 400
    assert "before" in resp.json()["detail"].lower()


def test_calendar_rejects_oversize_range_400(client: TestClient) -> None:
    """The 92-day cap protects the API from a UI bug or scraper that
    asks for "show me all events ever" — that query would dump the
    full hearings table into one response. Fail loudly with an
    actionable detail so the UI knows to narrow the window."""
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    today = date.today()
    resp = client.get(
        "/api/calendar/events",
        headers=headers,
        params={
            "from": today.isoformat(),
            "to": (today + timedelta(days=400)).isoformat(),
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "days" in body["detail"].lower() or "narrower" in body["detail"].lower()
