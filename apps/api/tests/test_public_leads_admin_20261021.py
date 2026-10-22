"""LEAD-01..03: isolated manager access and bounded, complete safe readback."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select

from caseops_api.db.models import BillingEnrollment, PlatformReportAdmin, PlatformReportAuditEvent
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.platform_console_leads import leads_page
from tests import test_platform_console as console_cases
from tests.test_auth_company import auth_headers
from tests.test_platform_console import report_console as report_console

URL = "/api/platform-console/leads"
__all__ = ["report_console"]


def _seed(count=1):
    now = datetime(2026, 10, 21, 12, tzinfo=UTC)
    with get_session_factory()() as session:
        rows = [
            BillingEnrollment(
                id=str(uuid4()),
                is_public_lead=True,
                contact_name=f"Public Contact {index}",
                contact_email=f"public-{index}@example.com",
                contact_mobile="5550001234",
                company_name="Example Practice",
                segment="solo",
                selected_plan="solo-monthly",
                source="solo_lawyers",
                notes="<script>private notes stay plain text</script>",
                created_at=now - timedelta(seconds=index),
                utm_json={
                    "role": "solo_advocate",
                    "intent": "pricing",
                    "privacy_notice_version": "2026-10-09",
                    "private_token": "not-projected",
                },
                status_timestamps_json={
                    "demo_admission": {
                        "notification_status": "outcome_unknown",
                        "attempts": 2,
                        "last_error_code": "timeout",
                        "private_provider_body": "not-projected",
                    }
                },
            )
            for index in range(count)
        ]
        session.add_all(rows)
        session.add(
            BillingEnrollment(
                contact_email="commercial-only@example.com",
                segment="firm",
                source="demo",
                notes="commercial-only-secret",
                is_public_lead=False,
            )
        )
        session.commit()
        return [row.id for row in rows]


def test_manager_readback_is_allowlisted_and_audited(report_console):
    data = report_console
    console_cases._manager(data)
    identities = _seed()
    response = data["client"].get(URL)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    result = response.json()
    assert result["next_cursor"] is None and result["has_more"] is False
    assert len(result["items"]) == 1
    row = result["items"][0]
    assert row["id"] == identities[0]
    assert set(row) == {
        "id",
        "submitted_at",
        "contact_name",
        "contact_email",
        "contact_mobile",
        "company_name",
        "segment",
        "selected_plan",
        "source",
        "role",
        "intent",
        "notes",
        "privacy_notice_version",
        "notification",
    }
    assert row["submitted_at"].endswith(("Z", "+00:00"))
    assert row["contact_email"] == "public-0@example.com"
    assert row["contact_mobile"] == "5550001234"
    assert row["notes"] == "<script>private notes stay plain text</script>"
    assert row["notification"] == {
        "status": "outcome_unknown",
        "attempts": 2,
        "last_error_code": "timeout",
        "eligible": False,
    }
    assert "not-projected" not in response.text and "commercial-only" not in response.text
    with get_session_factory()() as session:
        audit = session.scalars(
            select(PlatformReportAuditEvent).where(
                PlatformReportAuditEvent.action == "console.report_read",
                PlatformReportAuditEvent.target_id == "public_leads",
            )
        ).all()
        assert len(audit) == 1 and audit[0].reason is None


def test_manager_pages_all_retained_rows_with_one_select_per_page(report_console):
    data = report_console
    console_cases._manager(data)
    expected = _seed(263)
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        cursor, found, pages = None, [], 0
        with get_session_factory()() as session:
            while True:
                before = len(statements)
                page = leads_page(session, cursor=cursor, limit=100)
                assert len(statements) - before == 1
                found.extend(row.id for row in page.items)
                pages += 1
                if not page.has_more:
                    assert page.next_cursor is None
                    break
                assert page.next_cursor and len(page.items) == 100
                cursor = page.next_cursor
        assert pages == 3 and found == expected and len(set(found)) == 263
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("scope", ["anonymous", "tenant", "challenge", "viewer", "revoked"])
def test_lead_pii_is_denied_outside_current_mfa_manager(report_console, scope):
    data, headers = report_console, {}
    _seed()
    if scope == "tenant":
        headers = auth_headers(data["tenant"]["access_token"])
    elif scope == "challenge":
        console_cases._accept(data["client"], console_cases._link(data["messages"]))
    elif scope == "viewer":
        console_cases._manager(data)
        console_cases._invite(data)
        token = console_cases._link(data["messages"])
        data["client"].cookies.clear()
        console_cases._accept(data["client"], token)
        console_cases._enroll(data["client"])
    elif scope == "revoked":
        console_cases._manager(data)
        with get_session_factory()() as session:
            admin = session.get(PlatformReportAdmin, data["manager_id"])
            admin.status = "revoked"
            admin.auth_epoch += 1
            session.commit()
    response = data["client"].get(URL, headers=headers)
    assert response.status_code in {401, 403}
    assert "public-0@example.com" not in response.text
    assert "private notes" not in response.text


@pytest.mark.parametrize("query", ["?limit=0", "?limit=101", "?cursor=invalid"])
def test_invalid_lead_page_inputs_fail_without_pii(report_console, query):
    console_cases._manager(report_console)
    _seed()
    response = report_console["client"].get(URL + query)
    assert response.status_code in {400, 422}
    assert "public-0@example.com" not in response.text
