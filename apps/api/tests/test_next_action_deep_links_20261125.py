"""Next action "Open" must go to the item (Nov 24 workbook row 2).

Task and deadline next-actions linked to /app/matters/{id}: the overview that
renders the card. "Open" therefore re-navigated to the same page and looked
dead. Every kind must link away from the overview, and a task or deadline
link must name the exact item so the Tasks page can open it.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company, tenant_legal_today
from tests.test_today_view import (
    _create_matter,
    _seed_deadline,
    _seed_draft_in_review,
    _seed_hearing,
    _seed_invoice,
    _seed_task,
)


def _next_action(client: TestClient, token: str, matter_id: str) -> dict:
    response = client.get(f"/api/matters/{matter_id}/next-action", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body is not None
    return body


def test_overdue_and_upcoming_task_links_open_that_task(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    today = tenant_legal_today(client, auth_headers(token))
    overdue_matter = _create_matter(client, token, "NA-LINK-OVERDUE")
    overdue_task = _seed_task(overdue_matter, due_on=today - timedelta(days=1))
    body = _next_action(client, token, overdue_matter)
    assert body["kind"] == "task"
    assert body["href"] == f"/app/matters/{overdue_matter}/tasks?task={overdue_task}"

    upcoming_matter = _create_matter(client, token, "NA-LINK-SOON")
    upcoming_task = _seed_task(upcoming_matter, due_on=today + timedelta(days=4))
    body = _next_action(client, token, upcoming_matter)
    assert body["kind"] == "task"
    assert body["href"] == f"/app/matters/{upcoming_matter}/tasks?task={upcoming_task}"


def test_deadline_link_opens_that_deadline(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    today = tenant_legal_today(client, auth_headers(token))
    for offset, code in ((-1, "NA-DL-PAST"), (0, "NA-DL-TODAY"), (5, "NA-DL-LATER")):
        matter_id = _create_matter(client, token, code)
        deadline_id = _seed_deadline(matter_id, due_on=today + timedelta(days=offset))
        body = _next_action(client, token, matter_id)
        assert body["kind"] == "deadline", code
        assert body["href"] == f"/app/matters/{matter_id}/tasks?deadline={deadline_id}", code


def test_no_next_action_kind_links_back_to_the_overview(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    today = tenant_legal_today(client, auth_headers(token))
    seeds = {
        "task": lambda m: _seed_task(m, due_on=today + timedelta(days=2)),
        "deadline": lambda m: _seed_deadline(m, due_on=today + timedelta(days=2)),
        "hearing": lambda m: _seed_hearing(m, today + timedelta(days=2)),
        "draft": lambda m: _seed_draft_in_review(client, token, m),
        "invoice": lambda m: _seed_invoice(m, due_on=today - timedelta(days=3)),
    }
    seen = set()
    for kind, seed in seeds.items():
        matter_id = _create_matter(client, token, f"NA-ALL-{kind.upper()}")
        seed(matter_id)
        body = _next_action(client, token, matter_id)
        seen.add(body["kind"])
        overview = f"/app/matters/{matter_id}"
        assert body["href"].startswith(overview + "/"), (kind, body["href"])
        assert body["href"].split("?")[0] != overview, (kind, body["href"])
    assert seen == set(seeds)
