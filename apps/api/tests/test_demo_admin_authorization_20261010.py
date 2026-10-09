from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from caseops_api.core.cookies import CSRF_COOKIE, CSRF_HEADER
from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingEnrollment, PlatformAdminAuditEvent
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.saas_billing import DemoRequest
from caseops_api.services import billing_demo
from tests.test_auth_company import auth_headers, bootstrap_company


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def admin_client(request):
    return request.getfixturevalue(request.param)


@pytest.mark.parametrize("authenticated", [False, True], ids=["anonymous", "tenant-owner"])
@pytest.mark.parametrize(
    ("method", "suffix"),
    [("POST", "/retry-notification"), ("DELETE", "")],
    ids=["retry", "delete"],
)
def test_demo_admin_denial_preserves_lead_and_outbox(
    admin_client, monkeypatch, authenticated, method, suffix
):
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "founder-guard@example.com")
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: False)
    transports = []
    monkeypatch.setattr(billing_demo, "_send_notification", transports.append)
    get_settings.cache_clear()
    admin_client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    identity = str(uuid4())
    payload = DemoRequest(
        idempotency_key=identity,
        contact_name="Offline Guard Advocate",
        contact_email="guard-advocate@example.com",
        segment="solo",
        source="solo_lawyers",
        role="solo_advocate",
        intent="pilot",
        privacy_notice_version="2026-10-09",
    )
    admission = admin_client.post(
        "/api/billing/enrollments/demo-request", json=payload.model_dump(mode="json")
    )
    assert admission.status_code == 200, admission.text
    assert admission.json()["id"] == identity
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        assert row is not None
        state = dict(row.status_timestamps_json["demo_admission"])
        state.update(notification_status="retry_pending", attempts=1, last_error_code="timeout")
        row.status_timestamps_json = {**row.status_timestamps_json, "demo_admission": state}
        session.commit()
        before = deepcopy(row.status_timestamps_json)
        original_email = row.contact_email

    headers = {}
    if authenticated:
        token = str(bootstrap_company(admin_client)["access_token"])
        headers = auth_headers(token)
    else:
        admin_client.cookies.clear()
        # Reach authentication rather than satisfying the test at the CSRF fence.
        csrf_token = str(uuid4())
        admin_client.cookies.set(CSRF_COOKIE, csrf_token)
        headers[CSRF_HEADER] = csrf_token
    denied = admin_client.request(
        method,
        f"/api/platform-admin/enrollments/{identity}{suffix}",
        headers=headers,
        json={"reason": "Unauthorized offline probe"},
    )
    assert denied.status_code == (403 if authenticated else 401), denied.text
    assert original_email not in denied.text
    assert transports == []
    with get_session_factory()() as session:
        retained = session.get(BillingEnrollment, identity)
        assert retained is not None
        assert retained.contact_email == original_email
        assert retained.status == "demo_requested"
        assert retained.status_timestamps_json == before
        assert session.scalar(
            select(PlatformAdminAuditEvent.id).where(
                PlatformAdminAuditEvent.target_id == identity,
                PlatformAdminAuditEvent.action.in_(
                    [
                        "platform.demo_notification.retry_requested",
                        "platform.demo_enrollment.deleted",
                    ]
                ),
            )
        ) is None
