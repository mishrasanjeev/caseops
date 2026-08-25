from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    IpDocketEvent,
    IpDocketRecord,
    IpRelationship,
    TrademarkInternationalRegistration,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_international import (
    TrademarkInternationalActionRequest,
    TrademarkInternationalRecordCreateRequest,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import (
    _application,
    _asset,
    _bootstrap_tenant,
    _docket,
)


def _registration_payload(
    *,
    basic_application_id: str,
    ir_number: str = "1888001",
) -> dict[str, object]:
    return {
        "docket_title": f"ASTER MADRID {ir_number}",
        "record_kind": "international_registration",
        "direction": "outbound",
        "basic_application_id": basic_application_id,
        "international_application_number": f"MM-{ir_number}",
        "ir_number": ir_number,
        "wipo_reference": f"WIPO-IR-{ir_number}",
        "holder_name": "Aster Legal Private Limited",
        "mark_name": "ASTER",
        "office_of_origin": "IP India",
        "classes": [9, 42],
        "goods_services": {"9": "Software", "42": "Software services"},
        "form_kind": "MM2",
        "wipo_status": "recorded",
        "source_url": f"https://www.wipo.int/madrid/monitor/en/showData.jsp?ID={ir_number}",
        "source_reference": f"WIPO-IR-{ir_number}",
        "source_retrieved_at": "2026-08-25T06:30:00Z",
        "application_date": "2026-08-01",
        "international_registration_date": "2026-08-20",
        "dependency_end_date": "2031-08-20",
        "renewal_due_date": "2036-08-20",
    }


def _designation_payload(
    *,
    parent_registration_id: str,
    member_code: str,
    national_status: str,
) -> dict[str, object]:
    return {
        "docket_title": f"ASTER Madrid designation {member_code}",
        "record_kind": "international_designation",
        "direction": "outbound",
        "parent_registration_id": parent_registration_id,
        "wipo_reference": f"WIPO-DES-{member_code}-1888001",
        "holder_name": "Aster Legal Private Limited",
        "mark_name": "ASTER",
        "designated_member_code": member_code,
        "designated_office": f"{member_code} Trademark Office",
        "jurisdiction": member_code,
        "designation_kind": "original",
        "classes": [9, 42],
        "goods_services": {"9": "Software", "42": "Software services"},
        "wipo_status": "notified",
        "national_status": national_status,
        "source_url": f"https://www.wipo.int/madrid/monitor/{member_code}/1888001",
        "source_reference": f"WIPO-DES-{member_code}-1888001",
        "source_retrieved_at": "2026-08-25T07:00:00Z",
        "designation_effective_date": "2026-08-20",
        "notification_date": "2026-08-22",
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"source_url": "file:///tmp/wipo.json"}, "source URL must use HTTP or HTTPS"),
        (
            {"source_retrieved_at": datetime(2026, 8, 25, 6, 30)},
            "retrieval time must include a timezone",
        ),
        ({"classes": [9, 9]}, "classes must be unique"),
        ({"goods_services": {"9": "Software"}}, "exactly one entry for every class"),
        ({"basic_application_id": None}, "requires a basic Indian application"),
    ],
)
def test_madrid_contract_rejects_unsafe_or_incomplete_evidence(
    change: dict[str, object],
    message: str,
) -> None:
    payload = _registration_payload(basic_application_id="application-1") | change
    with pytest.raises(ValidationError, match=message):
        TrademarkInternationalRecordCreateRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            _registration_payload(basic_application_id="application-1")
            | {"docket_id": "docket-1", "docket_title": "Duplicate docket"},
            "Docket title is only valid",
        ),
        (
            _registration_payload(basic_application_id="application-1")
            | {"goods_services": {"9": "Software", "42": "  "}},
            "entries cannot be blank",
        ),
        (
            _registration_payload(basic_application_id="application-1")
            | {"designated_member_code": "IN"},
            "cannot contain designation fields",
        ),
        (
            _designation_payload(
                parent_registration_id="registration-1",
                member_code="IN",
                national_status="pending",
            )
            | {"jurisdiction": None},
            "requires its parent, member, jurisdiction, kind and date",
        ),
        (
            _designation_payload(
                parent_registration_id="registration-1",
                member_code="IN",
                national_status="pending",
            )
            | {"basic_application_id": "application-1"},
            "Only the international registration may own",
        ),
        (
            _designation_payload(
                parent_registration_id="registration-1",
                member_code="IN",
                national_status="pending",
            )
            | {"ir_number": "1888001"},
            "IR number belongs to the parent",
        ),
    ],
)
def test_madrid_record_contract_rejects_conflicting_ownership(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        TrademarkInternationalRecordCreateRequest.model_validate(payload)


def test_madrid_registration_and_designations_reuse_dockets_events_and_relationships(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    company_id = str(bootstrap["company"]["id"])
    basic_docket = _docket(client, headers, "ASTER BASIC MARK")
    asset = _asset(client, headers, basic_docket["id"], "ASTER")
    application = _application(client, headers, basic_docket["id"], asset["id"])

    created = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_registration_payload(basic_application_id=application["id"]),
    )
    assert created.status_code == 201, created.text
    registration = created.json()
    assert registration["record_kind"] == "international_registration"
    assert registration["basic_application_id"] == application["id"]
    assert registration["national_status"] is None

    us_response = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_designation_payload(
            parent_registration_id=registration["id"],
            member_code="US",
            national_status="provisional_refusal",
        ),
    )
    assert us_response.status_code == 201, us_response.text
    us_designation = us_response.json()
    eu_response = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_designation_payload(
            parent_registration_id=registration["id"],
            member_code="EM",
            national_status="protected",
        ),
    )
    assert eu_response.status_code == 201, eu_response.text
    eu_designation = eu_response.json()

    source_event = client.post(
        f"/api/ip/dockets/{us_designation['docket_id']}/events",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "event_kind": "registry_change",
            "source": "registry",
            "source_reference": "WIPO-DES-US-1888001",
            "effective_at": "2026-08-25T07:00:00Z",
            "responsible_membership_id": membership_id,
            "candidate_status": "candidate",
            "evidence_refs": ["WIPO-DES-US-1888001"],
            "payload": {"authority": "wipo", "status": "notified"},
        },
    )
    assert source_event.status_code == 201, source_event.text

    designation_page = client.get(
        "/api/ip/international-registrations",
        headers=headers,
        params={
            "record_kind": "international_designation",
            "parent_registration_id": registration["id"],
            "limit": 1,
        },
    )
    assert designation_page.status_code == 200, designation_page.text
    assert designation_page.json()["total"] == 2
    assert len(designation_page.json()["items"]) == 1

    assert (
        client.get(
        f"/api/ip/international-registrations/{registration['id']}",
        headers=headers,
        ).json()["wipo_status"]
        == "recorded"
    )
    assert (
        client.get(
        f"/api/ip/international-registrations/{us_designation['id']}",
        headers=headers,
        ).json()["national_status"]
        == "provisional_refusal"
    )
    assert (
        client.get(
        f"/api/ip/international-registrations/{eu_designation['id']}",
        headers=headers,
        ).json()["national_status"]
        == "protected"
    )

    session_factory = get_session_factory()
    with session_factory() as session:
        dockets = list(
            session.scalars(
                select(IpDocketRecord).where(
                    IpDocketRecord.company_id == company_id,
                    IpDocketRecord.id.in_(
                        {
                            registration["docket_id"],
                            us_designation["docket_id"],
                            eu_designation["docket_id"],
                        }
                    ),
                )
            )
        )
        assert {row.record_type for row in dockets} == {
            "international_registration",
            "international_designation",
        }
        relationships = list(
            session.scalars(select(IpRelationship).where(IpRelationship.company_id == company_id))
        )
        assert {row.relationship_kind for row in relationships} == {
            "basic_mark",
            "madrid_designation",
        }
        assert len(relationships) == 3
        events = list(
            session.scalars(
                select(IpDocketEvent).where(
                    IpDocketEvent.company_id == company_id,
                    IpDocketEvent.docket_id == us_designation["docket_id"],
                )
            )
        )
        assert len(events) == 1
        assert events[0].payload_json["authority"] == "wipo"
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "ip_madrid.record_created",
                )
            )
        )
        assert len(audits) == 3


def test_madrid_records_are_tenant_scoped_and_terminal_dockets_disappear(
    client: TestClient,
) -> None:
    first = _bootstrap_tenant(
        client,
        slug="madrid-alpha",
        email="owner@madrid-alpha.in",
    )
    first_headers = auth_headers(str(first["access_token"]))
    basic_docket = _docket(client, first_headers, "ALPHA BASIC")
    asset = _asset(client, first_headers, basic_docket["id"], "ALPHA")
    application = _application(
        client,
        first_headers,
        basic_docket["id"],
        asset["id"],
    )
    created = client.post(
        "/api/ip/international-registrations",
        headers=first_headers,
        json=_registration_payload(
            basic_application_id=application["id"],
            ir_number="1888002",
        ),
    )
    assert created.status_code == 201, created.text
    registration = created.json()

    second = _bootstrap_tenant(
        client,
        slug="madrid-beta",
        email="owner@madrid-beta.in",
    )
    second_headers = auth_headers(str(second["access_token"]))
    assert (
        client.get(
        f"/api/ip/international-registrations/{registration['id']}",
        headers=second_headers,
        ).status_code
        == 404
    )
    cross_tenant_child = client.post(
        "/api/ip/international-registrations",
        headers=second_headers,
        json=_designation_payload(
            parent_registration_id=registration["id"],
            member_code="IN",
            national_status="examined",
        ),
    )
    assert cross_tenant_child.status_code == 404

    closed = client.post(
        f"/api/ip/dockets/{registration['docket_id']}/lifecycle",
        headers=first_headers,
        json={
            "expected_lifecycle_version": 0,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Madrid registration work has ended with retained legal history.",
            "outcome": "closed",
            "source": "manual_test",
            "evidence_ref": "test:IPLF-057A:terminal",
            "client_report_handling": "retain",
            "linked_matter_handling": "not_linked",
        },
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["is_active"] is False
    assert (
        client.get(
        f"/api/ip/international-registrations/{registration['id']}",
        headers=first_headers,
        ).status_code
        == 404
    )

    with get_session_factory()() as session:
        persisted = session.scalar(
            select(TrademarkInternationalRegistration).where(
                TrademarkInternationalRegistration.id == registration["id"]
            )
        )
        assert persisted is not None


def _action_payload(
    *,
    membership_id: str,
    expected_version: int,
    action_kind: str,
    authority: str,
    source_reference: str,
    **changes: object,
) -> dict[str, object]:
    return {
        "expected_version": expected_version,
        "expected_lifecycle_version": 0,
        "action_kind": action_kind,
        "authority": authority,
        "effective_at": "2026-08-25T09:00:00Z",
        "responsible_membership_id": membership_id,
        "reason": f"Counsel reviewed {action_kind.replace('_', ' ')} evidence.",
        "source_reference": source_reference,
        "source_retrieved_at": "2026-08-25T08:55:00Z",
        "evidence_refs": [source_reference],
    } | changes


def test_madrid_actions_reconcile_sources_without_cross_designation_overwrite(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    basic_docket = _docket(client, headers, "ASTER MADRID BASIC")
    asset = _asset(client, headers, basic_docket["id"], "ASTER")
    application = _application(client, headers, basic_docket["id"], asset["id"])
    registration = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_registration_payload(
            basic_application_id=application["id"],
            ir_number="1888057",
        ),
    ).json()
    us = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_designation_payload(
            parent_registration_id=registration["id"],
            member_code="US",
            national_status="pending_examination",
        ),
    ).json()
    eu = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_designation_payload(
            parent_registration_id=registration["id"],
            member_code="EM",
            national_status="protected",
        ),
    ).json()

    snapshot = client.post(
        f"/api/ip/international-registrations/{us['id']}/actions",
        headers=headers,
        json=_action_payload(
            membership_id=membership_id,
            expected_version=1,
            action_kind="source_snapshot",
            authority="national_office",
            source_reference="USPTO:IR-1888057:refusal",
            source_url="https://tsdr.uspto.gov/IR-1888057",
            national_status="provisional_refusal",
        ),
    )
    assert snapshot.status_code == 201, snapshot.text
    snapshot_body = snapshot.json()
    assert snapshot_body["status_applied"] is False
    assert snapshot_body["event"]["candidate_status"] == "candidate"
    assert snapshot_body["record"]["national_status"] == "pending_examination"

    workspace = client.get(
        f"/api/ip/international-registrations/{us['id']}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    assert [row["id"] for row in workspace.json()["unresolved_source_candidates"]] == [
        snapshot_body["event"]["id"]
    ]
    assert "source_reconciliation_pending" in workspace.json()["data_quality_gaps"]
    assert workspace.json()["provider_mode"] == "manual_sourced_only"

    stale = client.post(
        f"/api/ip/international-registrations/{us['id']}/actions",
        headers=headers,
        json=_action_payload(
            membership_id=membership_id,
            expected_version=1,
            action_kind="source_reconciliation",
            authority="internal",
            source_reference="review:stale",
            reconciles_event_id=snapshot_body["event"]["id"],
            reconciliation_decision="same_fact",
        ),
    )
    assert stale.status_code == 409

    reconciled = client.post(
        f"/api/ip/international-registrations/{us['id']}/actions",
        headers=headers,
        json=_action_payload(
            membership_id=membership_id,
            expected_version=2,
            action_kind="source_reconciliation",
            authority="internal",
            source_reference="review:US:1888057",
            reconciles_event_id=snapshot_body["event"]["id"],
            reconciliation_decision="same_fact",
        ),
    )
    assert reconciled.status_code == 201, reconciled.text
    assert reconciled.json()["status_applied"] is True
    assert reconciled.json()["record"]["national_status"] == "provisional_refusal"
    assert reconciled.json()["event"]["candidate_status"] == "reconciled"

    assert (
        client.get(f"/api/ip/international-registrations/{eu['id']}", headers=headers).json()[
            "national_status"
        ]
        == "protected"
    )
    assert (
        client.get(
            f"/api/ip/international-registrations/{registration['id']}", headers=headers
        ).json()["wipo_status"]
        == "recorded"
    )

    invalid_parent_status = client.post(
        f"/api/ip/international-registrations/{registration['id']}/actions",
        headers=headers,
        json=_action_payload(
            membership_id=membership_id,
            expected_version=1,
            action_kind="source_snapshot",
            authority="national_office",
            source_reference="national:invalid-parent",
            source_url="https://example.gov/invalid-parent",
            national_status="refused",
        ),
    )
    assert invalid_parent_status.status_code == 422


def test_madrid_impact_agent_and_fee_actions_reuse_canonical_owners(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    membership_id = str(bootstrap["membership"]["id"])
    basic_docket = _docket(client, headers, "ORBIT MADRID BASIC")
    asset = _asset(client, headers, basic_docket["id"], "ORBIT")
    application = _application(client, headers, basic_docket["id"], asset["id"])
    registration = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_registration_payload(
            basic_application_id=application["id"],
            ir_number="1888058",
        ),
    ).json()
    india = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_designation_payload(
            parent_registration_id=registration["id"],
            member_code="IN",
            national_status="notified",
        ),
    ).json()

    impact = client.post(
        f"/api/ip/international-registrations/{registration['id']}/actions",
        headers=headers,
        json=_action_payload(
            membership_id=membership_id,
            expected_version=1,
            action_kind="central_attack_impact_review",
            authority="internal",
            source_reference="counsel:central-attack:1888058",
            details={
                "impact_scope": ["IR-1888058", "IN"],
                "recommended_action": "Assess transformation options; do not cancel.",
            },
        ),
    )
    assert impact.status_code == 201, impact.text
    assert impact.json()["impact_review_only"] is True
    assert impact.json()["record"]["wipo_status"] == "recorded"

    agent = client.post(
        f"/api/ip/international-registrations/{india['id']}/actions",
        headers=headers,
        json=_action_payload(
            membership_id=membership_id,
            expected_version=1,
            action_kind="local_agent_instruction",
            authority="local_agent",
            source_reference="agent-instruction:IN:1888058",
            local_agent_name="Aster India IP Counsel",
        ),
    )
    assert agent.status_code == 201, agent.text
    assert agent.json()["record"]["local_agent_name"] == "Aster India IP Counsel"
    assert agent.json()["event"]["payload_json"]["authority"] == "local_agent"

    cost_docket = client.post(
        f"/api/ip/dockets/{india['docket_id']}/cost-items",
        headers=headers,
        json={
            "category": "official_fee",
            "description": "India Madrid designation response fee",
            "amount_minor": 900000,
            "currency": "INR",
            "evidence_reference": "receipt:IN:1888058",
            "billable": False,
            "cost_nature": "actual",
        },
    )
    assert cost_docket.status_code == 200, cost_docket.text
    cost_id = cost_docket.json()["cost_items"][0]["id"]
    fee_action = client.post(
        f"/api/ip/international-registrations/{india['id']}/actions",
        headers=headers,
        json=_action_payload(
            membership_id=membership_id,
            expected_version=2,
            action_kind="fee_recorded",
            authority="internal",
            source_reference="receipt:IN:1888058",
            cost_item_refs=[cost_id],
        ),
    )
    assert fee_action.status_code == 201, fee_action.text
    workspace = client.get(
        f"/api/ip/international-registrations/{india['id']}/workspace",
        headers=headers,
    ).json()
    assert [row["id"] for row in workspace["costs"]] == [cost_id]
    assert "fee_or_cost_missing" not in workspace["data_quality_gaps"]


def test_madrid_action_contract_keeps_authority_and_reconciliation_distinct() -> None:
    base = _action_payload(
        membership_id="membership-1",
        expected_version=1,
        action_kind="source_snapshot",
        authority="wipo",
        source_reference="WIPO:IR-1",
        source_url="https://www.wipo.int/madrid/IR-1",
        wipo_status="registered",
    )
    assert TrademarkInternationalActionRequest.model_validate(base).wipo_status == "registered"
    with pytest.raises(ValidationError, match="Only a WIPO-attributed action"):
        TrademarkInternationalActionRequest.model_validate(base | {"authority": "national_office"})
    with pytest.raises(ValidationError, match="internal legal decision"):
        TrademarkInternationalActionRequest.model_validate(
            _action_payload(
                membership_id="membership-1",
                expected_version=2,
                action_kind="source_reconciliation",
                authority="wipo",
                source_reference="review:IR-1",
                source_url="https://www.wipo.int/madrid/IR-1",
                reconciles_event_id="event-1",
                reconciliation_decision="same_fact",
            )
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="change_recorded",
                authority="internal",
                source_reference="internal:change-1",
                effective_at=datetime(2026, 8, 25, 9),
            ),
            "Effective time must include a timezone",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="change_recorded",
                authority="internal",
                source_reference="internal:change-1",
                source_url="file:///tmp/evidence.json",
            ),
            "source URL must use HTTP or HTTPS",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="wipo_notification_recorded",
                authority="wipo",
                source_reference="WIPO:notice-1",
            ),
            "External-office actions require a source URL",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="change_recorded",
                authority="internal",
                source_reference="internal:change-1",
                national_status="protected",
            ),
            "Only a national-office-attributed action",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="change_recorded",
                authority="internal",
                source_reference="internal:change-1",
                local_agent_name="India Agent LLP",
            ),
            "Local agent may change only",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="local_agent_instruction",
                authority="internal",
                source_reference="internal:agent-1",
            ),
            "must remain attributed to the local agent",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="source_snapshot",
                authority="internal",
                source_reference="internal:snapshot-1",
            ),
            "snapshot must be attributed to WIPO or a national office",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="source_snapshot",
                authority="wipo",
                source_reference="WIPO:snapshot-1",
                source_url="https://www.wipo.int/madrid/snapshot-1",
            ),
            "snapshot must propose its authority-owned status",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="source_snapshot",
                authority="wipo",
                source_reference="WIPO:snapshot-1",
                source_url="https://www.wipo.int/madrid/snapshot-1",
                wipo_status="registered",
                reconciles_event_id="event-1",
            ),
            "snapshot cannot reconcile another source event",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="source_reconciliation",
                authority="internal",
                source_reference="internal:review-1",
            ),
            "requires a candidate event and explicit decision",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="change_recorded",
                authority="internal",
                source_reference="internal:change-1",
                reconciles_event_id="event-1",
            ),
            "Only source reconciliation may reference",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="change_recorded",
                authority="wipo",
                source_reference="WIPO:change-1",
                source_url="https://www.wipo.int/madrid/change-1",
                wipo_status="registered",
            ),
            "Legal status changes must enter through a sourced snapshot",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="dependency_impact_review",
                authority="internal",
                source_reference="internal:impact-1",
            ),
            "requires impact_scope and recommended_action",
        ),
        (
            _action_payload(
                membership_id="membership-1",
                expected_version=1,
                action_kind="fee_recorded",
                authority="internal",
                source_reference="internal:fee-1",
            ),
            "Fee action requires at least one canonical cost item",
        ),
    ],
)
def test_madrid_action_contract_rejects_invalid_authority_boundaries(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        TrademarkInternationalActionRequest.model_validate(payload)
