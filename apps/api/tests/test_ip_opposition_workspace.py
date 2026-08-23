from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import IpDocketEvent, IpPartyAndRole
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers
from tests.test_ip_opposition_foundation import (
    _complete_workspace,
    _fixture,
    _transition,
)
from tests.test_ip_record_workflow import _bootstrap_tenant

OPPOSITION_WORKSPACE_ROUTE = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opposition-workspace"
)


def test_applicant_workspace_is_versioned_and_confirms_ai_assisted_ground(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=True)
    headers = auth_headers(str(bootstrap["access_token"]))
    url = (
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}"
        "/opposition-workspace"
    )

    empty = client.get(url, headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["ready_for_stage_progression"] is False
    assert "opposition_profile_required" in empty.json()["readiness_gaps"]
    assert empty.json()["linked_matter_id"] == docket["matter_id"]

    registration = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "registration",
            "raw_value": "TM-REG-040B-2026",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registration_fixture",
            "effective_from": "2026-08-23",
            "is_primary": False,
            "application_id": proceeding["application_id"],
        },
    )
    assert registration.status_code == 201, registration.text

    saved = _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        grounds=[
            {
                "category": "bad_faith",
                "lawyer_detail": "Counsel confirmed the AI-assisted bad-faith classification.",
                "classification_source": "ai_assisted",
            }
        ],
    )
    assert saved["ready_for_stage_progression"] is True
    assert saved["profile_revision_count"] == 1
    assert saved["profile"]["lawyer_confirmed_by_membership_id"] == bootstrap[
        "membership"
    ]["id"]
    assert saved["profile"]["grounds"][0]["classification_source"] == "ai_assisted"
    assert {row["identifier_kind"] for row in saved["application_identifiers"]} == {
        "application"
    }
    assert saved["opposition_identifiers"][0]["identifier_kind"] == "opposition"

    revised = _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        effective_at="2026-08-23T07:30:00Z",
        expected_profile_event_id=saved["profile_event"]["id"],
        reason="Corrected the opponent name after lawyer review of the registry notice.",
        parties=[
            {
                "role": "applicant",
                "party_name": "Applicant Industries Pvt Ltd",
                "source": "opposition notice",
            },
            {
                "role": "opponent",
                "party_name": "Opponent Brands Private Limited",
                "source": "corrected opposition notice",
            },
        ],
    )
    assert revised["profile_revision_count"] == 2
    assert {row["party_name"] for row in revised["parties"]} == {
        "Applicant Industries Pvt Ltd",
        "Opponent Brands Private Limited",
    }
    assert revised["profile_event"]["supersedes_event_id"] == saved["profile_event"]["id"]

    stale_profile = _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        expected_status=409,
        effective_at="2026-08-23T07:45:00Z",
        expected_profile_event_id=saved["profile_event"]["id"],
        reason="Attempted a stale profile correction after a concurrent lawyer save.",
    )
    assert "profile changed" in stale_profile["detail"].lower()

    session = get_session_factory()()
    try:
        history = list(
            session.scalars(
                select(IpDocketEvent).where(
                    IpDocketEvent.proceeding_id == proceeding["id"],
                    IpDocketEvent.event_kind == "opposition_profile",
                )
            )
        )
        retired_party = session.scalar(
            select(IpPartyAndRole).where(
                IpPartyAndRole.proceeding_id == proceeding["id"],
                IpPartyAndRole.party_name == "Opponent Brands LLP",
            )
        )
        assert len(history) == 2
        assert retired_party is not None and retired_party.effective_until is not None
    finally:
        session.close()


def test_opponent_workspace_requires_instruction_limitation_and_relied_right(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(
        client,
        with_number=True,
        side="opponent",
    )
    pending = _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        client_instruction_state="pending",
        service=None,
    )
    assert pending["ready_for_stage_progression"] is False
    assert set(pending["readiness_gaps"]) == {
        "confirmed_client_instruction_required",
        "limitation_date_required",
        "relied_on_right_required",
    }

    ready = _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        effective_at="2026-08-23T07:40:00Z",
        expected_profile_event_id=pending["profile_event"]["id"],
        reason="Recorded client authority, limitation, and the relied-on registration.",
        client_instruction_state="confirmed",
        client_instruction_reference="instruction:client-email:2026-08-22",
        limitation_date="2026-09-20",
        relied_on_rights=[
            {
                "mark_or_right": "PRIOR BRAND",
                "jurisdiction": "IN",
                "identifier": "TM-111111",
                "status": "registered",
                "owner": "Opponent Brands LLP",
                "goods_services": "Recorded computer software",
                "evidence_refs": ["evidence:registration:111111"],
            }
        ],
        service=None,
    )
    assert ready["ready_for_stage_progression"] is True
    assert ready["readiness_gaps"] == []


def test_workspace_gate_versions_and_tenant_boundary_fail_closed(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=True)
    headers = auth_headers(str(bootstrap["access_token"]))
    stage = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage",
        headers=headers,
        json=_transition(bootstrap=bootstrap, version=1, to_stage="notice_filed"),
    )
    assert stage.status_code == 409
    assert stage.json()["code"] == "ip_opposition_workspace_incomplete"

    body = {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": 99,
        "source": "manual",
        "source_notice_reference": "notice:stale",
        "effective_at": "2026-08-23T08:00:00Z",
        "responsible_membership_id": bootstrap["membership"]["id"],
        "reason": "Attempted a stale opposition profile save for conflict proof.",
        "applicable_rule_version": "rules-v1",
        "forum": "Trade Marks Registry Delhi",
        "parties": [
            {"role": "applicant", "party_name": "Applicant A", "source": "notice"},
            {"role": "opponent", "party_name": "Opponent B", "source": "notice"},
        ],
        "grounds": [
            {
                "category": "other",
                "lawyer_detail": "A sufficiently detailed pleaded ground.",
            }
        ],
        "challenged_scope": [
            {"class_number": 9, "goods_services_segment": "Computer software"}
        ],
    }
    url = (
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}"
        "/opposition-workspace"
    )
    stale_response = client.put(url, headers=headers, json=body)
    assert stale_response.status_code == 409
    assert "version changed" in stale_response.text

    outsider = _bootstrap_tenant(
        client,
        slug="opposition-workspace-outsider",
        email="opposition-workspace-outsider@example.com",
    )
    hidden = client.get(
        url,
        headers=auth_headers(str(outsider["access_token"])),
    )
    assert hidden.status_code == 404
