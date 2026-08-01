from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    CalendarEventSync,
    Company,
    CompanyMembership,
    CompanyNotice,
    InAppNotification,
    IpDocketRecord,
    NotificationDeliveryChannel,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    Statute,
    StatuteSection,
    User,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter


def _particulars(*, mark: str = "ASTER") -> dict:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {
            "text": mark,
            "evidence_reference": "attachment:mark-proof-v1",
        },
        "classes": [{"class_number": 42, "specification": "Legal software services"}],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": "Aster Legal LLP"}],
        "agent": {"name": "Aster IP team"},
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": "attachment:mark-proof-v1",
            }
        ],
    }


def test_source_action_contract_fails_closed_and_redirects_official(
    client: TestClient,
) -> None:
    unauthorized = client.get(
        "/api/source-actions/open",
        params={"url": "https://www.indiacode.nic.in/document.pdf"},
        follow_redirects=False,
    )
    assert unauthorized.status_code == 401

    token = str(bootstrap_company(client)["access_token"])
    headers = auth_headers(token)
    unsafe = client.post(
        "/api/source-actions/inspect",
        headers=headers,
        json={"source_reference": "http://127.0.0.1/private"},
    )
    assert unsafe.status_code == 200
    assert unsafe.json()["state"] == "blocked"
    assert unsafe.json()["open_url"] is None

    unknown = client.post(
        "/api/source-actions/inspect",
        headers=headers,
        json={"source_reference": "https://untrusted.example/legal.pdf"},
    )
    assert unknown.json()["state"] == "unverified"

    official = client.post(
        "/api/source-actions/inspect",
        headers=headers,
        json={"source_reference": "https://www.indiacode.nic.in/document.pdf"},
    )
    assert official.json()["state"] == "available"
    redirect = client.get(
        "/api/source-actions/open",
        headers=headers,
        params={"url": "https://www.indiacode.nic.in/document.pdf"},
        follow_redirects=False,
    )
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://www.indiacode.nic.in/document.pdf"
    assert redirect.headers["referrer-policy"] == "no-referrer"


def test_statute_curator_contract_quarantines_and_rejects_stale_write(
    client: TestClient,
) -> None:
    payload = bootstrap_company(client)
    token = str(payload["access_token"])
    with get_session_factory()() as session:
        statute = Statute(
            id="tm-act-1999",
            short_name="TM Act",
            long_name="Trade Marks Act, 1999",
            enacted_year=1999,
            source_url="https://www.indiacode.nic.in/handle/123456789/1999",
        )
        section = StatuteSection(
            statute_id=statute.id,
            section_number="11",
            section_label="Relative grounds for refusal",
            section_text="A trade mark shall not be registered where confusion is likely.",
            section_text_source="indiacode_scrape",
            source_publisher="India Code",
            section_url="https://www.indiacode.nic.in/handle/123456789/1999",
            verification_status="unverified",
            source_version=1,
        )
        session.add_all([statute, section])
        session.commit()
        section_id = section.id

    audit = client.get("/api/statutes/verification/audit", headers=auth_headers(token))
    assert audit.status_code == 200, audit.text
    assert audit.json()["unverified"] == 1

    verified = client.post(
        f"/api/statutes/verification/sections/{section_id}",
        headers=auth_headers(token),
        json={"status": "verified_official", "expected_source_version": 1},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["verification_status"] == "verified_official"
    assert len(verified.json()["source_sha256"]) == 64
    assert verified.json()["source_action"]["state"] == "available"

    stale = client.post(
        f"/api/statutes/verification/sections/{section_id}",
        headers=auth_headers(token),
        json={
            "status": "quarantined",
            "expected_source_version": 1,
            "reason": "Fixture corruption",
        },
    )
    assert stale.status_code == 409


def test_ip_docket_end_to_end_uses_existing_notice_deadline_and_billing_owners(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-001")
    membership_id = str(bootstrap["membership"]["id"])

    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "ASTER word mark",
            "matter_id": matter["id"],
            "primary_identifier": "TM-TEST-001",
            "restricted": True,
            "particulars": _particulars(),
        },
    )
    assert created.status_code == 201, created.text
    docket = created.json()
    assert docket["status"] == "ready"
    assert docket["current_particulars"]["readiness_status"] == "ready"

    stale = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_particulars(mark="ASTER PRO") | {"expected_current_version": 999, "finalize": True},
    )
    assert stale.status_code == 409

    deadline = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "trademark_response",
            "title": "Respond to examination report",
            "due_on": str(date.today() + timedelta(days=30)),
            "assignee_membership_id": membership_id,
        },
    )
    assert deadline.status_code == 200, deadline.text
    with get_session_factory()() as session:
        session.add(
            UserCalendarConnection(
                company_id=str(bootstrap["company"]["id"]),
                membership_id=membership_id,
                provider="google_calendar",
                status="connected",
                encrypted_token_ref="fixture-token-reference",
            )
        )
        session.commit()
    coverage = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-coverages",
        headers=headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": membership_id,
            "coverage_status": "accepted",
        },
    )
    assert coverage.status_code == 200, coverage.text
    coverage_row = coverage.json()["deadline_coverages"][0]
    assert coverage_row["calendar_projection_status"] == "pending"
    with get_session_factory()() as session:
        calendar_sync = session.scalar(
            select(CalendarEventSync).where(
                CalendarEventSync.source_type == "matter_deadline",
                CalendarEventSync.source_id == deadline.json()["id"],
            )
        )
        assert calendar_sync is not None
        assert calendar_sync.sync_status == "pending"
    stale_reassignment = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-coverages/{coverage_row['id']}/reassign",
        headers=headers,
        json={
            "expected_responsible_membership_id": "stale-membership",
            "responsible_membership_id": membership_id,
            "reason": "Coverage owner returned from leave",
        },
    )
    assert stale_reassignment.status_code == 409

    with get_session_factory()() as session:
        notice = CompanyNotice(
            company_id=str(bootstrap["company"]["id"]),
            created_by_membership_id=membership_id,
            direction="received",
            subject="Trademark examination report",
        )
        session.add(notice)
        session.commit()
        notice_id = notice.id
    notice_link = client.post(
        f"/api/ip/dockets/{docket['id']}/notice-links",
        headers=headers,
        json={
            "notice_id": notice_id,
            "link_kind": "official_notice",
            "accepted_effect": "deadline_candidate",
        },
    )
    assert notice_link.status_code == 200, notice_link.text

    title = client.post(
        f"/api/ip/dockets/{docket['id']}/title-interests",
        headers=headers,
        json={
            "interest_type": "ownership",
            "party_name": "Aster Legal LLP",
            "effective_from": "2026-08-01",
            "evidence_reference": "attachment:assignment-1",
        },
    )
    assert title.status_code == 200, title.text

    cost = client.post(
        f"/api/ip/dockets/{docket['id']}/cost-items",
        headers=headers,
        json={
            "category": "official_fee",
            "description": "TM-A filing fee",
            "amount_minor": 900000,
            "currency": "INR",
            "evidence_reference": "receipt:tm-a-1",
        },
    )
    assert cost.status_code == 200, cost.text
    assert cost.json()["cost_items"][0]["amount_minor"] == 900000

    incident = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents",
        headers=headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "severity": "high",
            "summary": "Calendar projection was delayed",
            "impact": {"affected_deadlines": 1},
            "containment": "Manual diary entry confirmed",
            "correction_deadline_id": deadline.json()["id"],
        },
    )
    assert incident.status_code == 200, incident.text
    incident_id = incident.json()["deadline_incidents"][0]["id"]
    verified = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident_id}/verify",
        headers=headers,
        json={"corrective_action": "Projection reconciled against the diary."},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["deadline_incidents"][0]["status"] == "verified"

    report = client.get("/api/ip/reports/docket-control", headers=headers)
    assert report.status_code == 200
    assert report.json()["docket_count"] == 1
    assert report.json()["total_cost_minor_by_currency"] == {"INR": 900000}
    assert report.json()["inactive_coverage_count"] == 0


def test_matter_disposal_archives_ip_docket_without_reopening_resurrection(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-LIFECYCLE-001")
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Lifecycle-protected mark",
            "matter_id": matter["id"],
            "primary_identifier": "TM-LIFECYCLE-001",
            "restricted": True,
            "particulars": _particulars(mark="LIFECYCLE"),
        },
    )
    assert created.status_code == 201, created.text
    docket_id = created.json()["id"]

    disposed = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=headers,
        json={
            "to_status": "disposed",
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "Engagement completed and file disposition approved",
        },
    )
    assert disposed.status_code == 200, disposed.text
    assert disposed.json()["status"] == "disposed"
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 0
    assert client.get(f"/api/ip/dockets/{docket_id}", headers=headers).status_code == 404
    rejected_write = client.post(
        f"/api/ip/dockets/{docket_id}/versions",
        headers=headers,
        json=_particulars(mark="MUST NOT WRITE")
        | {"expected_current_version": 1, "finalize": True},
    )
    assert rejected_write.status_code == 404

    reopened = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=headers,
        json={
            "to_status": "intake",
            "expected_from_status": "disposed",
            "expected_updated_at": disposed.json()["updated_at"],
            "reason": "Client returned with materially new instructions",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "intake"
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 0
    assert client.get(f"/api/ip/dockets/{docket_id}", headers=headers).status_code == 404
    reloaded = client.get(f"/api/matters/{matter['id']}", headers=headers)
    assert reloaded.status_code == 200
    assert reloaded.json()["status"] == "intake"

    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_id)
        assert docket is not None
        assert docket.status == "archived"
        assert docket.archived_by_matter_disposal is True


def test_notification_external_block_creates_exactly_one_visible_fallback(
    client: TestClient,
) -> None:
    bootstrap_company(client)
    with get_session_factory()() as session:
        membership = session.scalar(select(CompanyMembership))
        assert membership is not None
        company = session.get(Company, membership.company_id)
        user = session.get(User, membership.user_id)
        assert company is not None and user is not None
        context = SessionContext(company=company, membership=membership, user=user)
        external = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=membership,
            channel=NotificationDeliveryChannel.EMAIL,
            event_type="ip.deadline.critical",
            source_type="ip_deadline",
            source_id="deadline-fixture-1",
            title="Critical IP deadline",
            body="A critical deadline requires review.",
        )
        assert external is not None
        session.commit()
        assert external.dispatch_owner == "durable_intent"
        assert external.fallback_intent_id is not None
        intents = list(session.scalars(select(NotificationDeliveryIntent)).all())
        visible = list(session.scalars(select(InAppNotification)).all())
        events = list(session.scalars(select(NotificationDeliveryEvent)).all())
        assert len(intents) == 2
        assert len(visible) == 1
        assert visible[0].title == "Critical IP deadline"
        assert {event.event_type for event in events} >= {"intent_created", "delivered"}
