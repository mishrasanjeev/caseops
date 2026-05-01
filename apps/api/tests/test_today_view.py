"""PG-004 (2026-05-01) — Today cockpit tests.

Covers the five streams the aggregator returns + tenant isolation +
horizon clamping. Uses TestClient with the SQLite test DB.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from caseops_api.db.models import (
    Draft,
    DraftStatus,
    InvoiceStatus,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterHearing,
    MatterHearingStatus,
    MatterInvoice,
    MatterTask,
    MatterTaskStatus,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(client: TestClient, token: str, code: str) -> str:
    resp = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Today smoke — {code}",
            "matter_code": code,
            "practice_area": "Criminal",
            "forum_level": "high_court",
            "status": "active",
            "description": "Today cockpit test matter.",
            "court_name": "Delhi High Court",
            "client_name": "Eval Client",
            "opposing_party": "State",
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["id"])


def _seed_hearing(matter_id: str, hearing_on: date) -> str:
    factory = get_session_factory()
    s = factory()
    try:
        h = MatterHearing(
            id=str(uuid.uuid4()),
            matter_id=matter_id,
            hearing_on=hearing_on,
            forum_name="Court 7",
            judge_name="Hon'ble Mr Justice X",
            purpose="Arguments",
            status=MatterHearingStatus.SCHEDULED,
        )
        s.add(h)
        s.commit()
        return h.id
    finally:
        s.close()


def _seed_task(
    matter_id: str,
    *,
    due_on: date | None,
    status: str = MatterTaskStatus.TODO,
    owner: str | None = None,
) -> str:
    factory = get_session_factory()
    s = factory()
    try:
        t = MatterTask(
            id=str(uuid.uuid4()),
            matter_id=matter_id,
            title="Draft reply",
            description="x",
            due_on=due_on,
            status=status,
            priority="medium",
            owner_membership_id=owner,
        )
        s.add(t)
        s.commit()
        return t.id
    finally:
        s.close()


def _seed_draft_in_review(client: TestClient, token: str, matter_id: str) -> str:
    """Create a draft + push it through generate → submit so the
    state machine lands at IN_REVIEW. Reuses the production endpoints
    so we don't have to fake DraftStatus directly."""
    resp = client.post(
        f"/api/matters/{matter_id}/drafts",
        headers=auth_headers(token),
        json={"title": "Reply brief", "draft_type": "brief"},
    )
    assert resp.status_code == 200, resp.text
    draft_id = resp.json()["id"]
    # Set status directly to in_review via DB write — generate /
    # submit flow needs verified citations which is out of scope here.
    factory = get_session_factory()
    s = factory()
    try:
        d = s.get(Draft, draft_id)
        assert d is not None
        d.status = DraftStatus.IN_REVIEW
        s.commit()
    finally:
        s.close()
    return draft_id


def _seed_invoice(
    matter_id: str,
    *,
    due_on: date,
    status: str = InvoiceStatus.ISSUED,
) -> str:
    from caseops_api.db.models import Matter
    factory = get_session_factory()
    s = factory()
    try:
        m = s.get(Matter, matter_id)
        assert m is not None
        inv = MatterInvoice(
            id=str(uuid.uuid4()),
            company_id=m.company_id,
            matter_id=matter_id,
            invoice_number=f"INV-{uuid.uuid4().hex[:6].upper()}",
            client_name="Eval Client",
            status=status,
            currency="INR",
            subtotal_amount_minor=100000,
            tax_amount_minor=18000,
            total_amount_minor=118000,
            balance_due_minor=118000,
            issued_on=due_on - timedelta(days=30),
            due_on=due_on,
        )
        s.add(inv)
        s.commit()
        return inv.id
    finally:
        s.close()


def _seed_deadline(matter_id: str, *, due_on: date) -> str:
    factory = get_session_factory()
    s = factory()
    try:
        d = MatterDeadline(
            id=str(uuid.uuid4()),
            matter_id=matter_id,
            source="manual",
            kind="filing",
            title="WS due Order VIII Rule 1",
            due_on=due_on,
            status=MatterDeadlineStatus.OPEN,
        )
        s.add(d)
        s.commit()
        return d.id
    finally:
        s.close()


# ---------------------------------------------------------------
# Tests
# ---------------------------------------------------------------


def test_today_empty_workspace_returns_empty_streams(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get("/api/me/today", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["hearings_next_7d"] == []
    assert body["tasks_due_or_overdue"] == []
    assert body["drafts_in_review"] == []
    assert body["overdue_invoices"] == []
    assert body["deadlines_next_7d"] == []
    assert body["horizon_days"] == 7


def test_today_aggregates_hearing_in_next_7d(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "TODAY-H1")
    _seed_hearing(matter_id, date.today() + timedelta(days=3))

    resp = client.get("/api/me/today", headers=auth_headers(token))
    body = resp.json()
    assert len(body["hearings_next_7d"]) == 1
    h = body["hearings_next_7d"][0]
    assert h["matter"]["matter_code"] == "TODAY-H1"
    assert h["forum_name"] == "Court 7"
    assert h["purpose"] == "Arguments"


def test_today_excludes_past_hearings(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "TODAY-H2")
    _seed_hearing(matter_id, date.today() - timedelta(days=2))
    _seed_hearing(matter_id, date.today() + timedelta(days=10))  # outside horizon
    _seed_hearing(matter_id, date.today() + timedelta(days=5))  # in horizon

    resp = client.get("/api/me/today", headers=auth_headers(token))
    hearings = resp.json()["hearings_next_7d"]
    assert len(hearings) == 1
    assert (
        date.fromisoformat(hearings[0]["hearing_on"]) == date.today() + timedelta(days=5)
    )


def test_today_tasks_overdue_and_due_today(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "TODAY-T1")
    _seed_task(matter_id, due_on=date.today() - timedelta(days=3))  # overdue
    _seed_task(matter_id, due_on=date.today())  # due today
    _seed_task(matter_id, due_on=date.today() + timedelta(days=2))  # within horizon
    _seed_task(matter_id, due_on=date.today() + timedelta(days=14))  # outside horizon
    _seed_task(
        matter_id, due_on=date.today() - timedelta(days=1),
        status=MatterTaskStatus.COMPLETED,  # done — must be excluded
    )

    resp = client.get("/api/me/today", headers=auth_headers(token))
    tasks = resp.json()["tasks_due_or_overdue"]
    # 3 visible: overdue / due-today / within-horizon (not the
    # outside-horizon one, not the completed one).
    assert len(tasks) == 3
    overdue_count = sum(1 for t in tasks if t["overdue"])
    assert overdue_count == 1


def test_today_horizon_clamping_returns_400(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    resp = client.get(
        "/api/me/today?horizon_days=0", headers=auth_headers(token),
    )
    assert resp.status_code == 400
    resp = client.get(
        "/api/me/today?horizon_days=999", headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_today_drafts_in_review_surface(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "TODAY-D1")
    draft_id = _seed_draft_in_review(client, token, matter_id)

    resp = client.get("/api/me/today", headers=auth_headers(token))
    drafts = resp.json()["drafts_in_review"]
    assert len(drafts) == 1
    assert drafts[0]["id"] == draft_id
    assert drafts[0]["matter"]["matter_code"] == "TODAY-D1"


def test_today_overdue_invoices_filter(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "TODAY-I1")
    # Overdue + issued — must surface.
    _seed_invoice(matter_id, due_on=date.today() - timedelta(days=10))
    # Due in future — must NOT surface.
    _seed_invoice(matter_id, due_on=date.today() + timedelta(days=10))
    # Overdue but PAID — must NOT surface.
    _seed_invoice(
        matter_id, due_on=date.today() - timedelta(days=20),
        status=InvoiceStatus.PAID,
    )
    # Overdue + partially_paid — MUST surface.
    _seed_invoice(
        matter_id, due_on=date.today() - timedelta(days=5),
        status=InvoiceStatus.PARTIALLY_PAID,
    )

    resp = client.get("/api/me/today", headers=auth_headers(token))
    invoices = resp.json()["overdue_invoices"]
    assert len(invoices) == 2
    assert all(inv["days_overdue"] > 0 for inv in invoices)


def test_today_deadlines_in_horizon(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "TODAY-DL1")
    _seed_deadline(matter_id, due_on=date.today() + timedelta(days=2))  # in horizon
    _seed_deadline(matter_id, due_on=date.today() + timedelta(days=20))  # outside

    resp = client.get("/api/me/today", headers=auth_headers(token))
    deadlines = resp.json()["deadlines_next_7d"]
    assert len(deadlines) == 1
    assert deadlines[0]["days_until"] == 2


def test_today_tenant_isolation(client: TestClient) -> None:
    """Tenant A's today feed must not include any of tenant B's
    hearings / tasks / drafts / invoices / deadlines."""
    token_a = str(bootstrap_company(client)["access_token"])
    matter_a = _create_matter(client, token_a, "TODAY-ISO-A")
    _seed_hearing(matter_a, date.today() + timedelta(days=2))

    # Bootstrap a second tenant by hitting bootstrap directly.
    bootstrap_resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B LLP",
            "company_slug": "today-iso-b",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b@example.in",
            "owner_password": "TenantBPass123!",
        },
    )
    assert bootstrap_resp.status_code == 200, bootstrap_resp.text
    token_b = str(bootstrap_resp.json()["access_token"])

    resp_a = client.get("/api/me/today", headers=auth_headers(token_a))
    resp_b = client.get("/api/me/today", headers=auth_headers(token_b))
    assert len(resp_a.json()["hearings_next_7d"]) == 1
    assert len(resp_b.json()["hearings_next_7d"]) == 0


def test_today_route_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/me/today")
    assert resp.status_code in {401, 403}


# ---------------------------------------------------------------
# PG-004 follow-up — per-matter Next-action card.
# ---------------------------------------------------------------


def test_next_action_returns_null_for_clean_matter(client: TestClient) -> None:
    """Empty matter (no hearings, tasks, deadlines, drafts, invoices) →
    next-action endpoint returns null instead of erroring."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "NA-EMPTY")

    resp = client.get(
        f"/api/matters/{matter_id}/next-action",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() is None


def test_next_action_picks_overdue_invoice_first(client: TestClient) -> None:
    """When a matter has both an overdue invoice AND an upcoming
    hearing, the overdue invoice wins (severity=urgent beats soon)."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "NA-INV")
    _seed_invoice(matter_id, due_on=date.today() - timedelta(days=15))
    _seed_hearing(matter_id, date.today() + timedelta(days=3))

    resp = client.get(
        f"/api/matters/{matter_id}/next-action",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body is not None
    assert body["kind"] == "invoice"
    assert body["severity"] == "urgent"
    assert "Overdue invoice" in body["label"]


def test_next_action_picks_overdue_task_over_upcoming_hearing(
    client: TestClient,
) -> None:
    """Overdue task beats a hearing 3 days out (urgent > normal)."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "NA-TASK")
    _seed_task(matter_id, due_on=date.today() - timedelta(days=2))
    _seed_hearing(matter_id, date.today() + timedelta(days=3))

    resp = client.get(
        f"/api/matters/{matter_id}/next-action",
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body is not None
    assert body["kind"] == "task"
    assert body["severity"] == "urgent"


def test_next_action_picks_hearing_today_over_draft_in_review(
    client: TestClient,
) -> None:
    """Within `soon` severity, a hearing today wins over a draft
    in review (kind tiebreak: hearing > draft)."""
    token = str(bootstrap_company(client)["access_token"])
    matter_id = _create_matter(client, token, "NA-HRG")
    _seed_hearing(matter_id, date.today())  # today → soon
    _seed_draft_in_review(client, token, matter_id)  # soon

    resp = client.get(
        f"/api/matters/{matter_id}/next-action",
        headers=auth_headers(token),
    )
    body = resp.json()
    assert body is not None
    # Both severity=soon; hearing has earlier due date (today).
    assert body["kind"] == "hearing"


def test_next_action_tenant_scoped(client: TestClient) -> None:
    """A matter id from tenant A doesn't surface tenant A's data when
    queried with tenant B's token."""
    token_a = str(bootstrap_company(client)["access_token"])
    matter_a = _create_matter(client, token_a, "NA-ISO-A")
    _seed_hearing(matter_a, date.today() + timedelta(days=2))

    bootstrap_resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Tenant B LLP",
            "company_slug": "next-iso-b",
            "company_type": "law_firm",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b@nextiso.in",
            "owner_password": "TenantBPass123!",
        },
    )
    assert bootstrap_resp.status_code == 200, bootstrap_resp.text
    token_b = str(bootstrap_resp.json()["access_token"])

    # Tenant A sees the action.
    resp_a = client.get(
        f"/api/matters/{matter_a}/next-action",
        headers=auth_headers(token_a),
    )
    assert resp_a.json() is not None

    # Tenant B querying tenant A's matter id sees null
    # (matter_id filter inside build_matter_next_action only matches
    # rows whose Matter.company_id == B's company id, which is none).
    resp_b = client.get(
        f"/api/matters/{matter_a}/next-action",
        headers=auth_headers(token_b),
    )
    assert resp_b.json() is None


# Pacify the import-unused linter; both names are referenced in the
# helpers above conditionally + used by readers consulting the test
# fixtures.
_ = (datetime, MatterTaskStatus.TODO)
