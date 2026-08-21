from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    IpDeadlineIncident,
    IpDocketEvent,
    TrademarkApplication,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _application, _asset, _docket


def _event(
    *,
    membership_id: str,
    application_id: str | None = None,
    application_version: int | None = None,
    event_kind: str = "formalities",
    source: str = "manual",
    effective_at: datetime | None = None,
    **overrides,
) -> dict:
    payload = {
        "expected_lifecycle_version": 0,
        "expected_application_version": application_version,
        "application_id": application_id,
        "event_kind": event_kind,
        "source": source,
        "source_reference": "ipindia:synthetic-1" if source == "registry" else None,
        "effective_at": (effective_at or datetime(2026, 8, 7, 6, 0, tzinfo=UTC)).isoformat(),
        "responsible_membership_id": membership_id,
        "reason": "Reviewed source evidence and recorded the legal event."
        if source == "manual"
        else None,
        "evidence_refs": ["attachment:official-evidence-1"],
        "document_refs": ["attachment:official-document-1"],
        "resulting_deadline_refs": ["candidate:response-deadline-1"],
        "candidate_status": "confirmed" if source == "manual" else "candidate",
        "correspondence": {
            "direction": "inward",
            "received_at": "2026-08-07T05:00:00Z",
            "due_at": "2026-09-07T05:00:00Z",
        },
        "payload": {
            "form_refs": ["form:TM-M:2026.1"],
            "fee_evidence_refs": ["receipt:synthetic-1"],
            "approval_refs": ["approval:lawyer-1"],
            "task_refs": ["matter-task:synthetic-1"],
            "deadlines_confirmed": False,
        },
    }
    payload.update(overrides)
    return payload


def test_uj06_event_preview_commit_reconcile_correct_and_report(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    docket = _docket(client, headers, "PROSECUTION MARK")
    asset = _asset(client, headers, docket["id"], "PROSECUTION MARK")
    application = _application(client, headers, docket["id"], asset["id"])

    filing_preview = client.post(
        f"/api/ip/dockets/{docket['id']}/events/preview",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=1,
            event_kind="filing",
            document_refs=[],
            evidence_refs=[],
            payload={},
        ),
    )
    assert filing_preview.status_code == 200, filing_preview.text
    assert filing_preview.json()["filing_claimed"] is False
    assert set(filing_preview.json()["unresolved_exception_codes"]) == {
        "document_evidence",
        "form_evidence",
        "fee_evidence",
        "approval_evidence",
    }

    event_payload = _event(
        membership_id=membership_id,
        application_id=application["id"],
        application_version=1,
    )
    preview = client.post(
        f"/api/ip/dockets/{docket['id']}/events/preview",
        headers=headers,
        json=event_payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["current_phase"] == "draft"
    assert preview.json()["proposed_phase"] == "formalities"
    assert preview.json()["operational_effects_are_proposals"] is True

    created = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=event_payload,
    )
    assert created.status_code == 201, created.text
    original = created.json()
    assert original["sequence"] == 1
    assert original["before_phase"] == "draft"
    assert original["after_phase"] == "formalities"
    assert original["payload_json"]["operational_completion"] is True
    assert original["payload_json"]["filing_evidence"] is False
    assert original["payload_json"]["correspondence"]["direction"] == "inward"

    duplicate_manual = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=2,
        ),
    )
    assert duplicate_manual.status_code == 409, duplicate_manual.text

    registry_payload = _event(
        membership_id=membership_id,
        application_id=application["id"],
        application_version=2,
        source="registry",
    )
    duplicate_preview = client.post(
        f"/api/ip/dockets/{docket['id']}/events/preview",
        headers=headers,
        json=registry_payload,
    )
    assert duplicate_preview.status_code == 200
    assert duplicate_preview.json()["duplicate_candidate_ids"] == [original["id"]]
    assert "duplicate_reconciliation_required" in duplicate_preview.json()[
        "unresolved_exception_codes"
    ]

    candidate_response = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=registry_payload,
    )
    assert candidate_response.status_code == 201, candidate_response.text
    candidate = candidate_response.json()
    assert candidate["candidate_status"] == "candidate"
    assert candidate["before_phase"] == "formalities"

    reconciliation = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=2,
            source="registry",
            candidate_status="reconciled",
            reconciles_event_id=candidate["id"],
            reconciliation_decision="same_fact",
        ),
    )
    assert reconciliation.status_code == 201, reconciliation.text
    assert reconciliation.json()["reconciles_event_id"] == candidate["id"]

    correction = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=3,
            event_kind="response",
            supersedes_event_id=original["id"],
            correction_reason="The source identifies the event as a response.",
        ),
    )
    assert correction.status_code == 201, correction.text
    assert correction.json()["supersedes_event_id"] == original["id"]

    backdated = client.post(
        f"/api/ip/dockets/{docket['id']}/events/preview",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=4,
            event_kind="examination_report",
            effective_at=datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
        ),
    )
    assert backdated.status_code == 200, backdated.text
    assert backdated.json()["backdated"] is True
    assert backdated.json()["recalculation_required"] is True
    assert "backdated_recalculation_review_required" in backdated.json()[
        "unresolved_exception_codes"
    ]

    backdated_payload = _event(
        membership_id=membership_id,
        application_id=application["id"],
        application_version=4,
        event_kind="examination_report",
        effective_at=datetime(2026, 8, 1, 6, 0, tzinfo=UTC),
    )
    refused_backdated = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=backdated_payload,
    )
    assert refused_backdated.status_code == 409, refused_backdated.text
    backdated_payload["acknowledged_exception_codes"] = [
        "backdated_recalculation_review_required"
    ]
    committed_backdated = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=backdated_payload,
    )
    assert committed_backdated.status_code == 201, committed_backdated.text
    assert committed_backdated.json()["payload_json"][
        "acknowledged_exception_codes"
    ] == ["backdated_recalculation_review_required"]
    assert committed_backdated.json()["payload_json"][
        "recalculation_preserved_current_phase"
    ] is True

    workspace = client.get(
        f"/api/ip/dockets/{docket['id']}/prosecution",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    assert body["current_phase"] == "response_filed"
    assert body["registry_freshness"] == "current"
    assert body["operational_completion_count"] == 5
    assert body["filing_evidence_count"] == 1
    assert body["registry_acceptance_count"] == 0
    assert body["final_disposition_count"] == 0
    assert body["unconfirmed_deadline_refs"] == ["candidate:response-deadline-1"]
    assert len(body["events"]) == 5

    with get_session_factory()() as session:
        persisted_original = session.get(IpDocketEvent, original["id"])
        stored_application = session.get(TrademarkApplication, application["id"])
        assert persisted_original is not None
        assert persisted_original.event_kind == "formalities"
        assert stored_application is not None
        assert stored_application.filing_phase == "response_filed"
        assert stored_application.version == 5
        actions = set(session.scalars(select(AuditEvent.action)).all())
        assert "ip_docket.event_appended" in actions


def test_application_terminal_state_is_fail_closed_and_restoration_is_controlled(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    docket = _docket(client, headers, "TERMINAL APPLICATION")
    asset = _asset(client, headers, docket["id"], "TERMINAL APPLICATION")
    application = _application(client, headers, docket["id"], asset["id"])

    refusal = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=1,
            event_kind="refusal",
        ),
    )
    assert refusal.status_code == 201, refusal.text
    refused = refusal.json()
    assert refused["after_phase"] == "refused"

    generic_reopen = client.patch(
        f"/api/ip/applications/{application['id']}/filing-phase",
        headers=headers,
        json={"expected_version": 2, "filing_phase": "filed"},
    )
    assert generic_reopen.status_code == 409

    child_event = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=2,
            event_kind="examination_report",
        ),
    )
    assert child_event.status_code == 409

    restored = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json=_event(
            membership_id=membership_id,
            application_id=application["id"],
            application_version=2,
            event_kind="restoration",
        ),
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["before_phase"] == "refused"
    assert restored.json()["after_phase"] == "restored"

    core = client.get(f"/api/ip/dockets/{docket['id']}/core-records", headers=headers)
    assert core.status_code == 200
    stored = core.json()["applications"][0]
    assert stored["is_active"] is True
    assert stored["lifecycle_version"] == 2
    assert stored["version"] == 3


def test_uj53_preview_blocks_unresolved_exception_then_close_and_reopen_persist(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-CLOSE-001")
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "CLOSE WORKFLOW MARK",
            "matter_id": matter["id"],
            "restricted": True,
            "particulars": {
                "form_key": "TM-A",
                "form_version": "2026.1",
                "mark_kind": "word",
                "representation": {"text": "CLOSE", "evidence_reference": "fixture:close"},
                "classes": [{"class_number": 9, "specification": "Software"}],
                "use_priority": None,
                "parties": [{"role": "applicant", "name": "Fixture Applicant LLP"}],
                "agent": None,
                "filing_manifest": [
                    {
                        "key": "representation",
                        "label": "Mark representation",
                        "required": True,
                        "evidence_reference": "fixture:close",
                    }
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    docket = response.json()
    company_id = str(bootstrap["company"]["id"])

    with get_session_factory()() as session:
        incident = IpDeadlineIncident(
            company_id=company_id,
            docket_id=docket["id"],
            severity="high",
            summary="Pending deadline review",
            impact_json={"scope": "synthetic"},
            status="open",
        )
        session.add(incident)
        session.commit()
        incident_id = incident.id

    close_payload = {
        "expected_lifecycle_version": 0,
        "to_status": "closed",
        "effective_at": "2026-08-07T08:00:00Z",
        "reason": "Client instructed the firm to close this record.",
        "outcome": "closed",
        "source": "client_instruction",
        "evidence_ref": "attachment:closure-instruction-1",
        "linked_matter_handling": "reviewed",
        "client_report_handling": "retain",
    }
    preview = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle/preview",
        headers=headers,
        json=close_payload,
    )
    assert preview.status_code == 200, preview.text
    blocker = f"open_deadline_incident:{incident_id}"
    assert preview.json()["blocker_codes"] == [blocker]
    assert preview.json()["requires_exception_acknowledgement"] is True

    blocked = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle",
        headers=headers,
        json=close_payload,
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ip_lifecycle_exceptions_unresolved"
    assert blocked.json()["blocker_codes"] == [blocker]

    closed = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle",
        headers=headers,
        json=close_payload | {"acknowledged_exception_codes": [blocker]},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["is_active"] is False
    assert closed.json()["lifecycle_version"] == 1
    assert closed.json()["event"]["payload_json"]["final_legal_disposition"] is True

    assert client.get(f"/api/ip/dockets/{docket['id']}", headers=headers).status_code == 404
    stale = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle",
        headers=headers,
        json={
            **close_payload,
            "to_status": "ready",
            "expected_lifecycle_version": 0,
        },
    )
    assert stale.status_code == 409

    reopened = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle",
        headers=headers,
        json={
            **close_payload,
            "to_status": "ready",
            "expected_lifecycle_version": 1,
            "reason": "Authorized lawyer approved controlled reopening.",
            "outcome": "reopened",
            "evidence_ref": "attachment:reopen-approval-1",
            "acknowledged_exception_codes": [blocker],
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "ready"
    assert reopened.json()["lifecycle_version"] == 2

    reloaded = client.get(f"/api/ip/dockets/{docket['id']}", headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["status"] == "ready"
    assert reloaded.json()["lifecycle_version"] == 2


def test_transfer_requires_active_same_tenant_successor_and_preserves_redirect(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    source = _docket(client, headers, "TRANSFER SOURCE")
    successor = _docket(client, headers, "TRANSFER SUCCESSOR")
    payload = {
        "expected_lifecycle_version": 0,
        "to_status": "transferred",
        "effective_at": "2026-08-08T08:00:00Z",
        "reason": "Responsibility transferred under written instruction.",
        "outcome": "transferred",
        "source": "client_instruction",
        "evidence_ref": "attachment:transfer-instruction-1",
        "successor_docket_id": successor["id"],
        "client_report_handling": "successor",
        "linked_matter_handling": "not_linked",
    }
    transferred = client.post(
        f"/api/ip/dockets/{source['id']}/lifecycle",
        headers=headers,
        json=payload,
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["status"] == "transferred"
    assert transferred.json()["successor_docket_id"] == successor["id"]

    with get_session_factory()() as session:
        history = list(
            session.scalars(
                select(IpDocketEvent)
                .where(IpDocketEvent.docket_id == source["id"])
                .order_by(IpDocketEvent.sequence)
            )
        )
        assert history[-1].payload_json["successor_docket_id"] == successor["id"]
        assert history[-1].payload_json["client_report_handling"] == "successor"
