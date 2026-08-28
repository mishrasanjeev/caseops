from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    CalendarEventSync,
    Communication,
    Company,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeMatterLink,
    InAppNotification,
    IpDeadlineCoverage,
    IpDocketEvent,
    IpDocketRecord,
    IpMatterLink,
    MatterAccessGrant,
    MatterAttachment,
    MatterTimeEntry,
    NotificationDeliveryChannel,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    Statute,
    StatuteSection,
    Team,
    User,
    UserCalendarConnection,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.notification_delivery import (
    apply_notification_provider_event,
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
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
        json={
            "source_reference": "https://www.indiacode.nic.in/document.pdf",
            "verified": True,
        },
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
    assert verified.status_code == 409, verified.text
    assert "different legal reviewer" in verified.json()["detail"]

    stale = client.post(
        f"/api/statutes/verification/sections/{section_id}",
        headers=auth_headers(token),
        json={
            "status": "quarantined",
            "expected_source_version": 1,
            "reason": "Fixture corruption",
        },
    )
    assert stale.status_code == 200
    assert stale.json()["verification_status"] == "quarantined"


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
    # Every claimed assignment participant enters the same tenant-scoped
    # Membership/User fence. A nonexistent optimistic token is therefore a
    # nondisclosing membership miss, not a stale-row conflict.
    assert stale_reassignment.status_code == 404, stale_reassignment.text
    assert stale_reassignment.headers["content-type"].startswith(
        "application/problem+json"
    )
    stale_problem = stale_reassignment.json()
    assert stale_problem["status"] == 404
    assert stale_problem["detail"] == "Company membership not found."
    assert stale_problem["instance"].endswith(
        f"/deadline-coverages/{coverage_row['id']}/reassign"
    )
    after_stale_reassignment = client.get(
        f"/api/ip/dockets/{docket['id']}", headers=headers
    )
    assert after_stale_reassignment.status_code == 200
    persisted_after_stale = next(
        row
        for row in after_stale_reassignment.json()["deadline_coverages"]
        if row["id"] == coverage_row["id"]
    )
    assert persisted_after_stale == coverage_row
    with get_session_factory()() as session:
        assert session.scalar(
            select(AuditEvent.id).where(
                AuditEvent.company_id == str(bootstrap["company"]["id"]),
                AuditEvent.target_id == coverage_row["id"],
                AuditEvent.action == "ip_deadline_coverage.transfer_proposed",
            )
        ) is None

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
    impact_scan = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident_id}/impact-scan",
        headers=headers,
        json={
            "complete": True,
            "items": [
                {
                    "record_type": "matter_deadline",
                    "record_reference": deadline.json()["id"],
                    "relationship": "calendar projection under review",
                    "assessment": "not_affected",
                    "scan_method": "manual diary reconciliation",
                    "evidence_reference": "reconciliation:projection-1",
                }
            ],
        },
    )
    assert impact_scan.status_code == 200, impact_scan.text
    for recipient_type in ("client", "insurer", "regulator", "court"):
        decision = client.post(
            f"/api/ip/dockets/{docket['id']}/deadline-incidents/"
            f"{incident_id}/notification-decisions",
            headers=headers,
            json={
                "recipient_type": recipient_type,
                "recipient_reference": f"{recipient_type}:projection-1",
                "decision": "not_applicable",
                "rationale": "No right was affected by the delayed projection.",
                "approval_evidence_reference": f"approval:{recipient_type}:projection-1",
            },
        )
        assert decision.status_code == 200, decision.text
    verified = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident_id}/verify",
        headers=headers,
        json={
            "outcome": "disproved",
            "corrective_action": "Projection reconciled against the diary.",
            "root_cause": "The external projection was delayed without changing the deadline.",
            "preventive_action": "Projection drift is now reviewed in the daily control.",
            "resolution_evidence_reference": "reconciliation:projection-resolution-1",
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["deadline_incidents"][0]["status"] == "disproved"

    report = client.get("/api/ip/reports/docket-control", headers=headers)
    assert report.status_code == 200
    assert report.json()["docket_count"] == 1
    assert report.json()["total_cost_minor_by_currency"] == {"INR": 900000}
    assert report.json()["inactive_coverage_count"] == 0


def test_ip_remaining_operations_end_to_end(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    company_id = str(bootstrap["company"]["id"])
    owner_id = str(bootstrap["membership"]["id"])
    matter = _mk_matter(client, token, "IP-COMPLETE-001")

    with get_session_factory()() as session:
        replacement_user = User(
            email="ip-backup@example.test",
            full_name="IP Backup",
            password_hash="not-used-in-this-test",
            is_active=True,
        )
        replacement = CompanyMembership(
            company_id=company_id,
            role="member",
            is_active=True,
        )
        replacement.user = replacement_user
        session.add_all([replacement_user, replacement])
        session.commit()
        replacement_id = replacement.id

    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Completed operations mark",
            "matter_id": matter["id"],
            "primary_identifier": "TM-COMPLETE-001",
            "restricted": True,
            "particulars": _particulars(mark="COMPLETE"),
        },
    )
    assert created.status_code == 201, created.text
    docket_id = created.json()["id"]

    deadline = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Pay licence royalty",
            "due_on": str(date.today() + timedelta(days=45)),
            "assignee_membership_id": owner_id,
        },
    )
    assert deadline.status_code == 200, deadline.text
    coverage_payload = {
        "matter_deadline_id": deadline.json()["id"],
        "responsible_membership_id": owner_id,
        "backup_membership_id": replacement_id,
        "coverage_status": "accepted",
    }
    blocked_coverage = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages",
        headers=headers,
        json=coverage_payload,
    )
    assert blocked_coverage.status_code == 409, blocked_coverage.text
    blocked_problem = blocked_coverage.json()
    assert blocked_problem["code"] == "ip_coverage_replacement_lacks_access"
    assert blocked_problem["blocked_docket_ids"] == [docket_id]
    assert "Completed operations mark" not in str(blocked_problem)
    with get_session_factory()() as session:
        assert session.scalar(
            select(IpDeadlineCoverage.id).where(
                IpDeadlineCoverage.docket_id == docket_id,
                IpDeadlineCoverage.matter_deadline_id == deadline.json()["id"],
            )
        ) is None
        assert session.scalar(
            select(AuditEvent.id).where(
                AuditEvent.company_id == company_id,
                AuditEvent.target_type == "ip_deadline_coverage",
                AuditEvent.action == "ip_deadline_coverage.accepted",
            )
        ) is None
        # A live backup is an operational role, so this restricted docket needs
        # durable, unbounded access before the positive-path fixture can exist.
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=docket_id,
                membership_id=replacement_id,
                access_level="member",
                reason="Unbounded restricted-docket access for the backup fixture.",
                granted_by_membership_id=owner_id,
            )
        )
        session.commit()

    coverage = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages",
        headers=headers,
        json=coverage_payload,
    )
    assert coverage.status_code == 200, coverage.text
    coverage_row = coverage.json()["deadline_coverages"][0]
    before_bulk = {
        row["id"]: row
        for row in client.get(f"/api/ip/dockets/{docket_id}", headers=headers).json()[
            "deadline_coverages"
        ]
    }
    bulk = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=headers,
        json={
            "from_membership_id": owner_id,
            "to_membership_id": replacement_id,
            "reason": "Responsible lawyer is on approved leave",
            "expected_versions": {coverage_row["id"]: coverage_row["reassignment_version"]},
        },
    )
    # The replacement is already this row's backup. The role-collision guard is
    # intentionally evaluated before access: either defect must refuse the
    # whole transfer, and the structural coverage invariant is independent of
    # whether this restricted docket later grants the replacement access.
    assert bulk.status_code == 409, bulk.text
    assert bulk.json()["code"] == "ip_coverage_distinct_backup_required"
    assert bulk.json()["blocked_docket_ids"] == [docket_id]

    # Fail closed: the original owner still holds the coverage.
    refreshed_docket = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert refreshed_docket.status_code == 200
    after_bulk = {
        row["id"]: row for row in refreshed_docket.json()["deadline_coverages"]
    }
    # Nothing moved: every coverage row is exactly as it was before the refusal.
    assert after_bulk == before_bulk
    assert all(
        row["responsible_membership_id"] != replacement_id for row in after_bulk.values()
    )

    shared_hash = "a" * 64
    with get_session_factory()() as session:
        notice = CompanyNotice(
            company_id=company_id,
            created_by_membership_id=owner_id,
            direction="received",
            subject="Registry examination report",
            authority="Trade Marks Registry",
            original_filename="examination.pdf",
            storage_key="tests/ip/examination.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256_hex=shared_hash,
        )
        session.add(notice)
        session.flush()
        session.add(
            CompanyNoticeMatterLink(
                company_id=company_id,
                notice_id=notice.id,
                matter_id=matter["id"],
            )
        )
        session.add(
            MatterAttachment(
                matter_id=matter["id"],
                uploaded_by_membership_id=owner_id,
                original_filename="duplicate-examination.pdf",
                storage_key="tests/ip/duplicate-examination.pdf",
                content_type="application/pdf",
                size_bytes=10,
                sha256_hex=shared_hash,
            )
        )
        session.add(
            Communication(
                company_id=company_id,
                matter_id=matter["id"],
                direction="inbound",
                channel="email",
                subject="Client instruction",
                body="Proceed with the response.",
                status="logged",
            )
        )
        time_entry = MatterTimeEntry(
            matter_id=matter["id"],
            author_membership_id=owner_id,
            work_date=date.today(),
            description="Official filing fee evidence owner",
            duration_minutes=0,
            billable=True,
            rate_currency="INR",
            total_amount_minor=900000,
        )
        session.add(time_entry)
        session.commit()
        time_entry_id = time_entry.id

    discovered = client.post(
        f"/api/ip/dockets/{docket_id}/evidence/discover",
        headers=headers,
    )
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["discovered_count"] == 3
    assert discovered.json()["duplicate_count"] == 1
    notice_candidate = next(
        row for row in discovered.json()["candidates"] if row["source_type"] == "company_notice"
    )
    accepted = client.post(
        f"/api/ip/dockets/{docket_id}/evidence/{notice_candidate['id']}/review",
        headers=headers,
        json={
            "expected_status": notice_candidate["status"],
            "action": "accept",
            "link_kind": "official_notice",
            "accepted_effect": "deadline_candidate",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["notice_links"][0]["link_kind"] == "official_notice"

    title = client.post(
        f"/api/ip/dockets/{docket_id}/title-interests",
        headers=headers,
        json={
            "interest_type": "licence",
            "party_name": "Aster Licensee Pvt Ltd",
            "effective_from": "2026-08-01",
            "evidence_reference": "attachment:licence-1",
            "recordal_status": "pending",
        },
    )
    assert title.status_code == 200, title.text
    interest_id = title.json()["title_interests"][0]["id"]
    obligation = client.post(
        f"/api/ip/dockets/{docket_id}/related-right-obligations",
        headers=headers,
        json={
            "title_interest_id": interest_id,
            "obligation_type": "royalty",
            "title": "Quarterly licence royalty",
            "due_on": str(date.today() + timedelta(days=45)),
            "owner_membership_id": replacement_id,
            "matter_deadline_id": deadline.json()["id"],
            "evidence_reference": "attachment:licence-1",
        },
    )
    assert obligation.status_code == 200, obligation.text
    obligation_id = obligation.json()["related_right_obligations"][0]["id"]
    completed = client.post(
        f"/api/ip/dockets/{docket_id}/related-right-obligations/{obligation_id}/complete",
        headers=headers,
        json={
            "expected_status": "open",
            "completion_evidence_reference": "receipt:royalty-1",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["related_right_obligations"][0]["status"] == "completed"

    cost = client.post(
        f"/api/ip/dockets/{docket_id}/cost-items",
        headers=headers,
        json={
            "category": "official_fee",
            "description": "TM-A filing fee",
            "amount_minor": 900000,
            "currency": "INR",
            "evidence_reference": "receipt:tm-a-complete",
            "billing_link_type": "time_entry",
            "billing_link_id": time_entry_id,
        },
    )
    assert cost.status_code == 200, cost.text
    assert cost.json()["cost_items"][0]["reconciliation_status"] == "matched"
    report = client.post(
        f"/api/ip/dockets/{docket_id}/cost-items/reconcile",
        headers=headers,
    )
    assert report.status_code == 200, report.text
    assert report.json()["accounting_owner"] == "matter_billing"
    assert report.json()["matched_count"] == 1
    assert len(report.json()["checksum_sha256"]) == 64

    with get_session_factory()() as session:
        persisted_coverage = session.get(IpDeadlineCoverage, coverage_row["id"])
        assert persisted_coverage is not None
        # The bulk transfer above was refused because the replacement already
        # holds backup cover, so the distinct-role invariant is durable too.
        assert persisted_coverage.responsible_membership_id != replacement_id
        assert (
            persisted_coverage.responsible_membership_id
            == before_bulk[coverage_row["id"]]["responsible_membership_id"]
        )
        assert (
            persisted_coverage.reassignment_version
            == before_bulk[coverage_row["id"]]["reassignment_version"]
        )


def test_matter_disposal_preserves_independent_ip_docket_lifecycle(
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
    listed = client.get("/api/ip/dockets", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    preserved = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert preserved.status_code == 200
    assert preserved.json()["status"] == created.json()["status"]
    assert preserved.json()["lifecycle_version"] == created.json()["lifecycle_version"]
    independent_write = client.post(
        f"/api/ip/dockets/{docket_id}/versions",
        headers=headers,
        json=_particulars(mark="INDEPENDENT")
        | {"expected_current_version": 1, "finalize": True},
    )
    assert independent_write.status_code == 200, independent_write.text
    assert independent_write.json()["current_version"] == 2

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
    assert client.get("/api/ip/dockets", headers=headers).json()["count"] == 1
    assert client.get(f"/api/ip/dockets/{docket_id}", headers=headers).status_code == 200
    reloaded = client.get(f"/api/matters/{matter['id']}", headers=headers)
    assert reloaded.status_code == 200
    assert reloaded.json()["status"] == "intake"

    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, docket_id)
        assert docket is not None
        assert docket.status == independent_write.json()["status"]
        assert docket.archived_by_matter_disposal is False


def test_ip_matter_links_are_effective_dated_many_to_many_and_timeline_is_referenced(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    operational_matter = _mk_matter(client, token, "IP-LINK-OPS-001")
    advisory_matter = _mk_matter(client, token, "IP-LINK-ADV-001")
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Many-to-many mark",
            "matter_id": operational_matter["id"],
            "primary_identifier": "TM-LINK-001",
            "restricted": False,
            "particulars": _particulars(mark="LINKED"),
        },
    )
    assert created.status_code == 201, created.text
    docket = created.json()

    initial_links = client.get(
        f"/api/ip/dockets/{docket['id']}/matter-links", headers=headers
    )
    assert initial_links.status_code == 200, initial_links.text
    assert initial_links.json()["active_count"] == 1
    assert initial_links.json()["links"][0]["relation_role"] == "operational"

    advisory = client.post(
        f"/api/ip/dockets/{docket['id']}/matter-links",
        headers=headers,
        json={
            "matter_id": advisory_matter["id"],
            "relation_role": "advisory",
            "source_reference": "engagement:advisory-001",
            "reason": "Advice on a related trademark filing strategy.",
            "expected_docket_updated_at": docket["updated_at"],
        },
    )
    assert advisory.status_code == 201, advisory.text
    advisory_link = advisory.json()
    assert advisory_link["lifecycle"]["matter_status"] == advisory_matter["status"]
    assert advisory_link["lifecycle"]["docket_status"] == docket["status"]

    duplicate = client.post(
        f"/api/ip/dockets/{docket['id']}/matter-links",
        headers=headers,
        json={
            "matter_id": advisory_matter["id"],
            "relation_role": "advisory",
            "reason": "Duplicate active advisory relationship should fail.",
            "expected_docket_updated_at": client.get(
                f"/api/ip/dockets/{docket['id']}", headers=headers
            ).json()["updated_at"],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "ip_matter_link_duplicate", duplicate.text
    assert duplicate.json()["detail"] == "That active Matter link already exists."

    second_operational = client.post(
        f"/api/ip/dockets/{docket['id']}/matter-links",
        headers=headers,
        json={
            "matter_id": advisory_matter["id"],
            "relation_role": "operational",
            "reason": "A second operational relationship must be rejected.",
            "expected_docket_updated_at": client.get(
                f"/api/ip/dockets/{docket['id']}", headers=headers
            ).json()["updated_at"],
        },
    )
    assert second_operational.status_code == 409, second_operational.text
    assert second_operational.json()["code"] == "ip_operational_matter_exists"

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, bootstrap["membership"]["id"])
        assert membership is not None
        link_effective_from = datetime.fromisoformat(advisory_link["effective_from"])
        session.add(
            IpDocketEvent(
                company_id=membership.company_id,
                docket_id=docket["id"],
                sequence=1,
                event_kind="formalities",
                source="registry",
                source_reference="registry:before-link-001",
                effective_at=link_effective_from - timedelta(days=1),
                responsible_membership_id=membership.id,
                entered_by_membership_id=membership.id,
                reason="This event predates the advisory relationship.",
                evidence_refs_json=["registry:before-link-001"],
                document_refs_json=[],
                resulting_deadline_refs_json=[],
                candidate_status="candidate",
                payload_json={},
            )
        )
        event = IpDocketEvent(
            company_id=membership.company_id,
            docket_id=docket["id"],
            sequence=2,
            event_kind="official_action",
            source="registry",
            source_reference="registry:action-001",
            effective_at=datetime.now(UTC),
            responsible_membership_id=membership.id,
            entered_by_membership_id=membership.id,
            reason="Registry examination report received.",
            evidence_refs_json=["registry:action-001"],
            document_refs_json=[],
            resulting_deadline_refs_json=[],
            candidate_status="confirmed",
            payload_json={},
        )
        session.add(event)
        session.commit()
        event_id = event.id

    timeline = client.get(
        f"/api/matters/{advisory_matter['id']}/timeline",
        headers=headers,
        params={"types": "ip_event", "sort": "asc", "limit": 1},
    )
    assert timeline.status_code == 200, timeline.text
    assert len(timeline.json()["items"]) == 1
    timeline_event = timeline.json()["items"][0]
    assert timeline_event["source_id"] == event_id
    assert timeline_event["source_type"] == "ip_docket_event"
    assert timeline_event["links"]["ip_docket"] == f"/app/ip?docket={docket['id']}"
    with get_session_factory()() as session:
        # Timeline composition is by reference; it never creates a Matter activity copy.
        assert session.get(IpDocketEvent, event_id) is not None
        assert session.scalar(
            select(IpMatterLink).where(IpMatterLink.id == advisory_link["id"])
        ) is not None

    refreshed_docket = client.get(
        f"/api/ip/dockets/{docket['id']}", headers=headers
    ).json()
    retired = client.post(
        f"/api/ip/dockets/{docket['id']}/matter-links/{advisory_link['id']}/retire",
        headers=headers,
        json={
            "reason": "The advisory engagement has concluded.",
            "expected_link_updated_at": advisory_link["updated_at"],
            "expected_docket_updated_at": refreshed_docket["updated_at"],
        },
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["link"]["retired_at"] is not None
    assert retired.json()["link"]["reason"] == advisory_link["reason"]
    assert (
        retired.json()["link"]["retirement_reason"]
        == "The advisory engagement has concluded."
    )
    assert retired.json()["operational_pointer_cleared"] is False


def test_matter_ip_link_query_count_is_bounded_by_page_not_link_count(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-LINK-PERF-001")

    def create_docket(index: int) -> None:
        response = client.post(
            "/api/ip/dockets",
            headers=headers,
            json={
                "title": f"Bounded link {index}",
                "matter_id": matter["id"],
                "primary_identifier": f"TM-LINK-PERF-{index:03d}",
                "restricted": False,
                "particulars": _particulars(mark=f"BOUND {index}"),
            },
        )
        assert response.status_code == 201, response.text

    def measured_read() -> tuple[int, dict]:
        query_count = 0

        def count_query(*_args: object) -> None:
            nonlocal query_count
            query_count += 1

        engine = get_engine()
        event.listen(engine, "before_cursor_execute", count_query)
        try:
            response = client.get(
                f"/api/matters/{matter['id']}/ip-links",
                headers=headers,
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_query)
        assert response.status_code == 200, response.text
        return query_count, response.json()

    create_docket(0)
    one_link_queries, one_link = measured_read()
    assert one_link["count"] == 1

    for index in range(1, 8):
        create_docket(index)
    many_link_queries, many_links = measured_read()
    assert many_links["count"] == 8
    assert many_link_queries <= one_link_queries + 1
    assert many_link_queries <= 24


def test_matter_ip_link_warning_matches_inactive_team_visibility_policy(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    member_email = "inactive-team-link-reader@asterlegal.in"
    created_member = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": "Inactive Team Link Reader",
            "email": member_email,
            "role": "member",
            "password": "MemberPass123!",
        },
    )
    assert created_member.status_code == 200, created_member.text
    team_response = client.post(
        "/api/teams/",
        headers=headers,
        json={"name": "Historical IP Team", "slug": "historical-ip-team"},
    )
    assert team_response.status_code == 201, team_response.text
    team = team_response.json()
    with get_session_factory()() as session:
        membership_id = session.scalar(
            select(CompanyMembership.id)
            .join(User, User.id == CompanyMembership.user_id)
            .where(User.email == member_email)
        )
    assert membership_id is not None
    add_member = client.post(
        f"/api/teams/{team['id']}/members",
        headers=headers,
        json={"membership_id": membership_id},
    )
    assert add_member.status_code == 200, add_member.text
    scope = client.put(
        "/api/teams/scoping",
        headers=headers,
        json={"enabled": True},
    )
    assert scope.status_code == 200, scope.text
    matter = _mk_matter(client, token, "IP-LINK-INACTIVE-TEAM-001")
    assigned = client.patch(
        f"/api/matters/{matter['id']}",
        headers=headers,
        json={
            "team_id": team["id"],
            "expected_updated_at": matter["updated_at"],
        },
    )
    assert assigned.status_code == 200, assigned.text
    docket = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Historical team visibility",
            "matter_id": matter["id"],
            "primary_identifier": "TM-LINK-INACTIVE-TEAM-001",
            "restricted": False,
            "particulars": _particulars(mark="HISTORICAL TEAM"),
        },
    )
    assert docket.status_code == 201, docket.text
    with get_session_factory()() as session:
        persisted_team = session.get(Team, team["id"])
        assert persisted_team is not None
        persisted_team.is_active = False
        session.commit()

    response = client.get(
        f"/api/matters/{matter['id']}/ip-links",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 1
    assert payload["links"][0]["access_mismatch_warning"] is False


def test_ip_matter_links_omit_inaccessible_side_without_link_metadata_leak(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    create_member = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "IP Docket Reader",
            "email": "ip-reader@asterlegal.in",
            "role": "admin",
            "password": "MemberPass123!",
        },
    )
    assert create_member.status_code == 200, create_member.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "ip-reader@asterlegal.in",
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    member_headers = auth_headers(str(login.json()["access_token"]))
    matter = _mk_matter(client, owner_token, "IP-LINK-WALLED-001")
    created = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "Visible IP, restricted Matter",
            "matter_id": matter["id"],
            "primary_identifier": "TM-LINK-WALLED-001",
            "restricted": False,
            "particulars": _particulars(mark="WALLED"),
        },
    )
    assert created.status_code == 201, created.text
    docket_id = created.json()["id"]
    restricted = client.post(
        f"/api/matters/{matter['id']}/access/restricted",
        headers=owner_headers,
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text

    owner_links = client.get(
        f"/api/ip/dockets/{docket_id}/matter-links", headers=owner_headers
    )
    assert owner_links.status_code == 200, owner_links.text
    assert owner_links.json()["links"][0]["access_mismatch_warning"] is True

    member_docket = client.get(f"/api/ip/dockets/{docket_id}", headers=member_headers)
    assert member_docket.status_code == 200, member_docket.text
    hidden_links = client.get(
        f"/api/ip/dockets/{docket_id}/matter-links", headers=member_headers
    )
    assert hidden_links.status_code == 200, hidden_links.text
    assert hidden_links.json() == {
        "docket_id": docket_id,
        "links": [],
        "count": 0,
        "active_count": 0,
    }
    assert (
        client.get(f"/api/matters/{matter['id']}/ip-links", headers=member_headers).status_code
        == 404
    )


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
            # This test exercises provider fallback only. A declared
            # ``ip_deadline`` must reference a real, operational deadline and
            # is correctly blocked by the canonical target fence.
            source_type="provider_fixture",
            source_id="deadline-fixture-1",
            title="Critical IP deadline",
            body="A critical deadline requires review.",
        )
        assert external is not None
        session.commit()
        assert external.dispatch_owner == "durable_intent"
        assert external.title is None
        assert external.body is None
        assert external.fallback_intent_id is not None
        intents = list(session.scalars(select(NotificationDeliveryIntent)).all())
        visible = list(session.scalars(select(InAppNotification)).all())
        events = list(session.scalars(select(NotificationDeliveryEvent)).all())
        assert len(intents) == 2
        assert len(visible) == 1
        assert visible[0].title == "Critical IP deadline"
        assert {event.event_type for event in events} >= {"intent_created", "delivered"}


def test_notification_external_cutover_uses_only_durable_intent_and_webhook(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap_company(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "sendgrid_api_key", "test-sendgrid-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    send_calls: list[dict] = []

    def fake_send(**kwargs):
        send_calls.append(kwargs)
        return True, "sg-durable-1", None

    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        fake_send,
    )
    with get_session_factory()() as session:
        membership = session.scalar(select(CompanyMembership))
        assert membership is not None
        company = session.get(Company, membership.company_id)
        user = session.get(User, membership.user_id)
        assert company is not None and user is not None
        context = SessionContext(company=company, membership=membership, user=user)
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=membership,
            channel=NotificationDeliveryChannel.EMAIL,
            event_type="ip.deadline.critical",
            source_type="provider_fixture",
            source_id="deadline-live-fixture",
            title="Critical IP deadline",
            body="Open CaseOps to review the deadline.",
        )
        assert intent is not None
        assert intent.status == "queued"
        assert intent.comparison_status == "dual_read_matched"
        result = process_notification_delivery_intent(
            session,
            intent_id=intent.id,
            context=context,
        )
        assert result.status == "sent"
        assert result.external_calls == 1
        assert intent.fallback_intent_id is None
        assert len(send_calls) == 1
        assert send_calls[0]["custom_args"] == {"notification_intent_id": intent.id}
        mismatched = apply_notification_provider_event(
            session,
            event={
                "event": "delivered",
                "notification_intent_id": intent.id,
                "sg_message_id": "different-message.filter",
                "sg_event_id": "event-wrong-message",
            },
        )
        assert mismatched is False
        matched = apply_notification_provider_event(
            session,
            event={
                "event": "delivered",
                "notification_intent_id": intent.id,
                "sg_message_id": "sg-durable-1.filter",
                "sg_event_id": "event-durable-1",
            },
        )
        assert matched is True
        session.commit()
        session.refresh(intent)
        assert intent.status == "delivered"
        assert intent.delivered_at is not None
        assert intent.fallback_intent_id is None
        visible = list(session.scalars(select(InAppNotification)).all())
        assert visible == []
