"""IPLF-039D per-path evidence for the complete UJ-58 incident lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    CompanyMembership,
    IpDeadlineIncident,
    IpWorkspaceConfiguration,
    LegalHold,
    LegalHoldStatus,
    MatterDeadline,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars

RECIPIENT_TYPES = ("client", "insurer", "regulator", "court")


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-039D-UJ58")
    created = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Incident Mark",
            "matter_id": matter["id"],
            "restricted": True,
            "particulars": _particulars("INCIDENT MARK"),
        },
    )
    assert created.status_code == 201, created.text
    return headers, created.json(), bootstrap


def _open_incident(client: TestClient, headers: dict[str, str], docket_id: str, **kw):
    body = {
        "severity": "high",
        "summary": "Suspected missed response deadline on the examination report.",
        "impact": {"affected_rights": ["TM 1234567"], "clients_notified": False},
        "defect_scope": "record_specific",
        "defect_fingerprint": "deadline-rule-application-v3",
        "evidence_snapshot": {
            "calculation_version_refs": ["calc:v3"],
            "rule_version_refs": ["rule:opposition-response:v7"],
            "calendar_version_refs": ["calendar:india-2026:v2"],
            "source_refs": ["registry:event:opaque-17"],
            "message_refs": ["message:opaque-21"],
            "provider_event_refs": ["provider:opaque-44"],
            "audit_refs": ["audit:opaque-91"],
        },
    }
    body.update(kw)
    response = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-incidents", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    return response.json()["deadline_incidents"][0]


def _action(
    client: TestClient,
    headers: dict[str, str],
    docket_id: str,
    incident_id: str,
    action_type: str,
):
    return client.post(
        f"/api/ip/dockets/{docket_id}/deadline-incidents/{incident_id}/actions",
        headers=headers,
        json={
            "action_type": action_type,
            "action_status": "completed",
            "action_reference": f"task:{action_type}:1",
            "details": f"Human reviewer completed the {action_type} control.",
            "evidence_reference": f"evidence:{action_type}:1",
        },
    )


def _scan(
    client: TestClient,
    headers: dict[str, str],
    docket_id: str,
    incident_id: str,
    assessment: str = "affected",
):
    response = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-incidents/{incident_id}/impact-scan",
        headers=headers,
        json={
            "complete": True,
            "items": [
                {
                    "record_type": "trademark_application",
                    "record_reference": "TM-1234567",
                    "relationship": "same rule and source version",
                    "assessment": assessment,
                    "scan_method": "defect fingerprint match",
                    "evidence_reference": "scan:2026-08-21:1",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text


def _decide_recipients(
    client: TestClient,
    headers: dict[str, str],
    docket_id: str,
    incident_id: str,
    *,
    decision: str = "not_applicable",
):
    for recipient_type in RECIPIENT_TYPES:
        response = client.post(
            f"/api/ip/dockets/{docket_id}/deadline-incidents/"
            f"{incident_id}/notification-decisions",
            headers=headers,
            json={
                "recipient_type": recipient_type,
                "recipient_reference": f"{recipient_type}:confidential-identity",
                "decision": decision,
                "rationale": "Risk partner approved this recipient-specific decision.",
                "approval_evidence_reference": f"approval:{recipient_type}:1",
                **(
                    {"communication_reference": f"communication:{recipient_type}:1"}
                    if decision == "notify"
                    else {}
                ),
            },
        )
        assert response.status_code == 200, response.text


def _resolve(
    client: TestClient,
    headers: dict[str, str],
    docket_id: str,
    incident_id: str,
    outcome: str,
):
    return client.post(
        f"/api/ip/dockets/{docket_id}/deadline-incidents/{incident_id}/verify",
        headers=headers,
        json={
            "outcome": outcome,
            "corrective_action": "Risk partner approved the recorded disposition.",
            "root_cause": "A bounded rule-version mismatch caused the suspected result.",
            "preventive_action": "Regression coverage and source-version checks were added.",
            "resolution_evidence_reference": f"resolution:{outcome}:1",
        },
    )


def _counts():
    with get_session_factory()() as session:
        return (
            int(session.scalar(select(func.count()).select_from(NotificationDeliveryIntent)) or 0),
            int(session.scalar(select(func.count()).select_from(MatterDeadline)) or 0),
        )


def test_uj58_normal_complete_human_review_and_immutable_resolution(client: TestClient) -> None:
    headers, docket, _ = _setup(client)
    incident = _open_incident(client, headers, docket["id"])
    assert incident["status"] == "open"
    assert len(incident["preservation_manifest_sha256"]) == 64
    assert incident["evidence_snapshot_json"]["rule_version_refs"] == [
        "rule:opposition-response:v7"
    ]

    premature = _resolve(client, headers, docket["id"], incident["id"], "verified")
    assert premature.status_code == 409
    assert "incident_impact_scan_incomplete" in premature.text

    for action_type in ("containment", "corrective_task", "prevention"):
        response = _action(client, headers, docket["id"], incident["id"], action_type)
        assert response.status_code == 200, response.text
    _scan(client, headers, docket["id"], incident["id"])
    _decide_recipients(client, headers, docket["id"], incident["id"])
    resolved = _resolve(client, headers, docket["id"], incident["id"], "verified")
    assert resolved.status_code == 200, resolved.text
    closed = resolved.json()["deadline_incidents"][0]
    assert closed["status"] == "verified"
    assert closed["verified_at"] is not None
    assert {row["action_type"] for row in closed["actions"]} == {
        "containment",
        "corrective_task",
        "prevention",
    }

    terminal_mutation = _action(
        client, headers, docket["id"], incident["id"], "external_advice"
    )
    assert terminal_mutation.status_code == 409


def test_uj58_exc01_disproved_suspicion_retains_scan_and_decisions(client: TestClient) -> None:
    headers, docket, _ = _setup(client)
    incident = _open_incident(client, headers, docket["id"])
    _scan(client, headers, docket["id"], incident["id"], assessment="not_affected")
    _decide_recipients(client, headers, docket["id"], incident["id"])
    resolved = _resolve(client, headers, docket["id"], incident["id"], "disproved")
    assert resolved.status_code == 200, resolved.text
    disproved = resolved.json()["deadline_incidents"][0]
    assert disproved["status"] == "disproved"
    assert disproved["impacts"][0]["assessment"] == "not_affected"
    assert len(disproved["notification_decisions"]) == 4
    assert disproved["resolution_evidence_reference"] == "resolution:disproved:1"


def test_uj58_exc02_never_invents_remedy_deadline_or_communication(client: TestClient) -> None:
    headers, docket, _ = _setup(client)
    before = _counts()
    incident = _open_incident(
        client,
        headers,
        docket["id"],
        severity="critical",
        impact={"remedy_available": "uncertain", "clients_notified": False},
    )
    assert incident["impact_json"]["remedy_available"] == "uncertain"
    assert incident["actions"] == []
    assert incident["notification_decisions"] == []
    assert _counts() == before


def test_uj58_exc03_legal_hold_and_policy_both_block_deletion(client: TestClient) -> None:
    headers, docket, bootstrap = _setup(client)
    incident = _open_incident(client, headers, docket["id"])
    company_id = str(bootstrap["company"]["id"])
    owner_id = str(bootstrap["membership"]["id"])
    with get_session_factory()() as session:
        approver_user = User(
            email="incident-hold-approver@example.test",
            full_name="Incident Hold Approver",
            password_hash="not-used",
            is_active=True,
        )
        session.add(approver_user)
        session.flush()
        approver = CompanyMembership(
            company_id=company_id, user_id=approver_user.id, role="admin"
        )
        session.add(approver)
        session.flush()
        now = datetime.now(UTC)
        session.add(
            LegalHold(
                company_id=company_id,
                key="uj58-company-hold",
                title="Incident preservation hold",
                authority_reference="hold-order:2026:58",
                status=LegalHoldStatus.ACTIVE,
                created_by_membership_id=owner_id,
                created_by_membership_company_id=company_id,
                creator_label_snapshot="Firm owner",
                approved_by_membership_id=approver.id,
                approved_by_membership_company_id=company_id,
                approver_label_snapshot="Records approver",
                activated_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    blocked = client.delete(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident['id']}",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert "legal_hold_blocks_incident_deletion" in blocked.text

    with get_session_factory()() as session:
        hold = session.scalar(select(LegalHold).where(LegalHold.company_id == company_id))
        assert hold is not None
        hold.status = LegalHoldStatus.RELEASED
        hold.released_at = datetime.now(UTC)
        session.commit()
    retained = client.delete(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident['id']}",
        headers=headers,
    )
    assert retained.status_code == 409
    assert "incident_evidence_retained_by_policy" in retained.text


def test_uj58_exc04_recipient_decisions_are_versioned_and_identity_hashed(
    client: TestClient,
) -> None:
    headers, docket, _ = _setup(client)
    incident = _open_incident(client, headers, docket["id"])
    _decide_recipients(client, headers, docket["id"], incident["id"])
    changed = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/"
        f"{incident['id']}/notification-decisions",
        headers=headers,
        json={
            "recipient_type": "client",
            "recipient_reference": "client:confidential-identity",
            "decision": "notify",
            "rationale": "Client communication approved after the initial assessment.",
            "approval_evidence_reference": "approval:client:2",
            "communication_reference": "communication:client:2",
        },
    )
    assert changed.status_code == 200, changed.text
    decisions = changed.json()["deadline_incidents"][0]["notification_decisions"]
    client_versions = [row for row in decisions if row["recipient_type"] == "client"]
    assert [row["decision_version"] for row in client_versions] == [1, 2]
    assert client_versions[0]["recipient_reference_sha256"] == client_versions[1][
        "recipient_reference_sha256"
    ]
    assert "confidential-identity" not in changed.text


def test_uj58_exc05_platform_defect_stops_automation_until_evidenced_release(
    client: TestClient,
) -> None:
    headers, docket, bootstrap = _setup(client)
    membership_id = str(bootstrap["membership"]["id"])
    configured = client.put(
        "/api/ip/workspace/configuration",
        headers=headers,
        json={
            "enabled_asset_types": ["trademark"],
            "jurisdictions": ["IN"],
            "offices": ["IP India"],
            "timezone": "Asia/Kolkata",
            "holiday_calendar_key": "test-calendar",
            "working_day_policy": {"working_weekdays": [0, 1, 2, 3, 4]},
            "document_taxonomy_version": "ip-taxonomy-2026.1",
            "event_catalog_version": "ip-events-v1",
            "deadline_rule_versions": {"IN-TM": "2026.1"},
            "notification_channels": ["in_app"],
            "critical_event_policy": {"escalation_after_minutes": 30},
            "escalation_owner_membership_id": membership_id,
            "provider_keys": [],
            "accept_provider_terms": False,
        },
    )
    assert configured.status_code == 200, configured.text
    session_factory = get_session_factory()
    with session_factory() as session:
        workspace = session.scalar(
            select(IpWorkspaceConfiguration).where(
                IpWorkspaceConfiguration.company_id == str(bootstrap["company"]["id"])
            )
        )
        assert workspace is not None
        workspace.enabled_automations_json = [
            "deadline_automation",
            "notification_automation",
        ]
        workspace.workspace_enabled = True
        session.commit()

    incident = _open_incident(
        client,
        headers,
        docket["id"],
        defect_scope="platform_wide",
        kill_switch_features=["deadline_automation", "notification_automation"],
        kill_switch_evidence_reference="incident-command:2026-08-21:stop-1",
    )
    assert {row["feature_id"] for row in incident["kill_switches"]} == {
        "deadline_automation",
        "notification_automation",
    }
    configuration = client.get("/api/ip/workspace/configuration", headers=headers)
    assert configuration.status_code == 200, configuration.text
    assert configuration.json()["configuration"]["version"] == 2
    assert configuration.json()["configuration"]["enabled_automations_json"] == []

    blocked_enable = client.post(
        "/api/ip/workspace/enable",
        headers=headers,
        json={
            "expected_config_version": 2,
            "enabled_automations": ["deadline_automation"],
        },
    )
    assert blocked_enable.status_code == 409
    assert "incident_kill_switch:deadline_automation" in blocked_enable.text
    readiness = client.get("/api/ip/readiness", headers=headers)
    assert readiness.status_code == 200, readiness.text
    by_id = {row["feature_id"]: row for row in readiness.json()["features"]}
    assert by_id["deadline_automation"]["reason"] == "incident_kill_switch"
    assert by_id["deadline_automation"]["blocked_by_incident_id"] == incident["id"]

    early_release = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident['id']}"
        "/kill-switches/deadline_automation/release",
        headers=headers,
        json={
            "expected_version": 1,
            "release_reason": "Attempted before closure.",
            "release_evidence_reference": "release:test:early",
        },
    )
    assert early_release.status_code == 409

    _scan(client, headers, docket["id"], incident["id"], assessment="not_affected")
    _decide_recipients(client, headers, docket["id"], incident["id"])
    assert _resolve(
        client, headers, docket["id"], incident["id"], "disproved"
    ).status_code == 200
    released = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident['id']}"
        "/kill-switches/deadline_automation/release",
        headers=headers,
        json={
            "expected_version": 1,
            "release_reason": "Fingerprint scan disproved the platform-wide defect.",
            "release_evidence_reference": "release:approval:1",
        },
    )
    assert released.status_code == 200, released.text
    deadline_switch = next(
        row
        for row in released.json()["deadline_incidents"][0]["kill_switches"]
        if row["feature_id"] == "deadline_automation"
    )
    assert deadline_switch["status"] == "released"
    assert deadline_switch["version"] == 2


def test_uj58_restricted_incident_is_tenant_hidden(client: TestClient) -> None:
    headers, docket, _ = _setup(client)
    incident = _open_incident(client, headers, docket["id"])
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other IP Firm",
            "company_slug": "other-ip-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@otherip.example",
            "owner_password": "OtherFirmPass123!",
        },
    )
    assert other.status_code == 200, other.text
    hidden = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-incidents/{incident['id']}/actions",
        headers=auth_headers(str(other.json()["access_token"])),
        json={
            "action_type": "containment",
            "action_status": "completed",
            "action_reference": "task:hidden",
            "details": "This must not be visible across tenants.",
            "evidence_reference": "evidence:hidden",
        },
    )
    assert hidden.status_code == 404
    with get_session_factory()() as session:
        stored = session.get(IpDeadlineIncident, incident["id"])
        assert stored is not None
        assert stored.status == "open"
