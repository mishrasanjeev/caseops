from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    IpDeadlineCoverage,
    IpDocketEvent,
    IpDocketRecord,
    IpRelatedRightObligation,
    MatterDeadline,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_lifecycle import (
    IpDocketEventCreateRequest,
    IpLifecycleTransitionRequest,
)
from caseops_api.services.ip_lifecycle import (
    append_ip_docket_event,
    list_ip_docket_events,
    transition_ip_docket_lifecycle,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter

EFFECTIVE_AT = datetime(2026, 8, 7, 4, 30, tzinfo=UTC)


def _particulars(mark: str) -> dict:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {
            "text": mark,
            "evidence_reference": f"fixture:{mark.lower()}",
        },
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": "Fixture Applicant LLP"}],
        "agent": None,
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": f"fixture:{mark.lower()}",
            }
        ],
    }


def _docket(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    matter_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": matter_id is not None,
            "particulars": _particulars(title),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _context(session, bootstrap: dict) -> SessionContext:
    company = session.get(Company, str(bootstrap["company"]["id"]))
    membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
    assert company is not None and membership is not None
    user = session.get(User, membership.user_id)
    assert user is not None
    return SessionContext(company=company, membership=membership, user=user)


def _manual_event(*, membership_id: str, **overrides) -> IpDocketEventCreateRequest:
    payload = {
        "expected_lifecycle_version": 0,
        "event_kind": "examination_report",
        "source": "manual",
        "effective_at": EFFECTIVE_AT,
        "responsible_membership_id": membership_id,
        "reason": "Official examination report received and reviewed.",
        "evidence_refs": ["attachment:exam-report-1"],
        "resulting_stage": "examination",
    }
    payload.update(overrides)
    return IpDocketEventCreateRequest(**payload)


def test_append_only_events_preserve_sequence_corrections_and_registry_candidates(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    docket = _docket(client, headers, title="EVENT HISTORY MARK")
    membership_id = str(bootstrap["membership"]["id"])

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        original = append_ip_docket_event(
            session,
            context=context,
            docket_id=docket["id"],
            payload=_manual_event(membership_id=membership_id),
        )
        correction = append_ip_docket_event(
            session,
            context=context,
            docket_id=docket["id"],
            payload=_manual_event(
                membership_id=membership_id,
                event_kind="response",
                supersedes_event_id=original.id,
                correction_reason="The event type was entered incorrectly.",
                reason="Correct the event type without changing source history.",
            ),
        )
        candidate = append_ip_docket_event(
            session,
            context=context,
            docket_id=docket["id"],
            payload=_manual_event(
                membership_id=membership_id,
                event_kind="publication",
                source="registry",
                source_reference="ipindia:fixture-101",
                reason=None,
                candidate_status="candidate",
            ),
        )
        rows = list_ip_docket_events(
            session,
            context=context,
            docket_id=docket["id"],
        )

        assert [row.sequence for row in rows] == [1, 2, 3]
        assert rows[0].event_kind == "examination_report"
        assert rows[0].reason == "Official examination report received and reviewed."
        assert correction.supersedes_event_id == original.id
        assert candidate.candidate_status == "candidate"
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.company_id == context.company.id,
                    AuditEvent.target_type == "ip_docket_event",
                )
            )
        )
        assert actions == {"ip_docket.event_appended"}


def test_event_commands_reject_stale_registry_and_cross_tenant_targets(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    first_headers = auth_headers(str(first["access_token"]))
    first_docket = _docket(client, first_headers, title="FIRST TENANT MARK")
    membership_id = str(first["membership"]["id"])

    second_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second IP Firm",
            "company_slug": "second-ip-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "second-owner@example.com",
            "owner_password": "SecondOwnerPass123!",
        },
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    second_headers = auth_headers(str(second["access_token"]))
    second_docket = _docket(client, second_headers, title="SECOND TENANT MARK")
    asset = client.post(
        f"/api/ip/dockets/{second_docket['id']}/assets",
        headers=second_headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": "SECOND"},
    )
    assert asset.status_code == 201, asset.text
    application = client.post(
        f"/api/ip/dockets/{second_docket['id']}/applications",
        headers=second_headers,
        json={
            "asset_id": asset.json()["id"],
            "office": "IP India",
            "jurisdiction": "IN",
            "filing_phase": "draft",
            "source_pending_identifier_allocation": False,
        },
    )
    assert application.status_code == 201, application.text

    with get_session_factory()() as session:
        context = _context(session, first)
        with pytest.raises(HTTPException) as registry_error:
            append_ip_docket_event(
                session,
                context=context,
                docket_id=first_docket["id"],
                payload=_manual_event(
                    membership_id=membership_id,
                    source="registry",
                    reason=None,
                ),
            )
        assert registry_error.value.status_code == 422

        with pytest.raises(HTTPException) as tenant_error:
            append_ip_docket_event(
                session,
                context=context,
                docket_id=first_docket["id"],
                    payload=_manual_event(
                        membership_id=membership_id,
                        application_id=application.json()["application"]["id"],
                        expected_application_version=1,
                    ),
            )
        assert tenant_error.value.status_code == 422

        with pytest.raises(HTTPException) as stale_error:
            append_ip_docket_event(
                session,
                context=context,
                docket_id=first_docket["id"],
                payload=_manual_event(
                    membership_id=membership_id,
                    expected_lifecycle_version=9,
                ),
            )
        assert stale_error.value.status_code == 409
        assert session.scalar(select(IpDocketEvent)) is None


def test_lifecycle_transition_is_fail_closed_and_reopen_does_not_revive_children(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-LIFE-001")
    docket = _docket(
        client,
        headers,
        title="LIFECYCLE MARK",
        matter_id=matter["id"],
    )
    membership_id = str(bootstrap["membership"]["id"])
    deadline_response = client.post(
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
    assert deadline_response.status_code == 200, deadline_response.text
    deadline_id = deadline_response.json()["id"]

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        coverage = IpDeadlineCoverage(
            company_id=context.company.id,
            docket_id=docket["id"],
            matter_deadline_id=deadline_id,
            responsible_membership_id=membership_id,
            coverage_status="accepted",
            calendar_projection_status="pending",
        )
        obligation = IpRelatedRightObligation(
            company_id=context.company.id,
            docket_id=docket["id"],
            obligation_type="response",
            title="Respond to examination report",
            due_on=date.today() + timedelta(days=30),
            owner_membership_id=membership_id,
            matter_deadline_id=deadline_id,
            status="open",
            evidence_reference="attachment:exam-report-1",
        )
        session.add_all([coverage, obligation])
        session.commit()

        terminal, terminal_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=docket["id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=0,
                to_status="closed",
                effective_at=EFFECTIVE_AT,
                reason="Registration is no longer maintained by this firm.",
                outcome="closed",
                source="lawyer_review",
                evidence_ref="attachment:closure-instruction-1",
                linked_matter_handling="reviewed",
            ),
        )
        assert terminal.is_active is False
        assert terminal.lifecycle_version == 1
        assert terminal_event.before_phase == "ready"
        assert terminal_event.after_phase == "closed"

        session.refresh(coverage)
        session.refresh(obligation)
        deadline = session.get(MatterDeadline, deadline_id)
        assert coverage.coverage_status == "inactive_lifecycle"
        assert obligation.status == "cancelled_lifecycle"
        assert deadline is not None and deadline.status == "cancelled"

        with pytest.raises(HTTPException) as stale_transition:
            transition_ip_docket_lifecycle(
                session,
                context=context,
                docket_id=docket["id"],
                payload=IpLifecycleTransitionRequest(
                    expected_lifecycle_version=0,
                    to_status="ready",
                    effective_at=EFFECTIVE_AT,
                    reason="Stale reopening request must be rejected.",
                    outcome="reopened",
                    source="lawyer_review",
                    evidence_ref="attachment:stale-reopen",
                    linked_matter_handling="reviewed",
                ),
            )
        assert stale_transition.value.status_code == 409
        session.rollback()

    assert client.get(f"/api/ip/dockets/{docket['id']}", headers=headers).status_code == 404
    blocked_version = client.post(
        f"/api/ip/dockets/{docket['id']}/versions",
        headers=headers,
        json=_particulars("BLOCKED") | {"expected_current_version": 1, "finalize": True},
    )
    assert blocked_version.status_code == 404

    with get_session_factory()() as session:
        context = _context(session, bootstrap)
        reopened, reopened_event = transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=docket["id"],
            payload=IpLifecycleTransitionRequest(
                expected_lifecycle_version=1,
                to_status="ready",
                effective_at=EFFECTIVE_AT + timedelta(days=1),
                reason="Named lawyer approved a controlled reopen.",
                outcome="reopened",
                source="lawyer_review",
                evidence_ref="attachment:reopen-approval-1",
                linked_matter_handling="reviewed",
            ),
        )
        assert reopened.is_active is True
        assert reopened.lifecycle_version == 2
        assert reopened_event.sequence == 2
        assert reopened_event.payload_json["reopen_without_child_resurrection"] is True

        coverage = session.scalar(
            select(IpDeadlineCoverage).where(IpDeadlineCoverage.docket_id == docket["id"])
        )
        obligation = session.scalar(
            select(IpRelatedRightObligation).where(
                IpRelatedRightObligation.docket_id == docket["id"]
            )
        )
        assert coverage is not None and coverage.coverage_status == "inactive_lifecycle"
        assert obligation is not None and obligation.status == "cancelled_lifecycle"
        persisted = session.get(IpDocketRecord, docket["id"])
        assert persisted is not None and persisted.status == "ready"

    reloaded = client.get(f"/api/ip/dockets/{docket['id']}", headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["lifecycle_version"] == 2
    assert reloaded.json()["deadline_coverages"][0]["coverage_status"] == ("inactive_lifecycle")
    assert reloaded.json()["related_right_obligations"][0]["status"] == ("cancelled_lifecycle")
