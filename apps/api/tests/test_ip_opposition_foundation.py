from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import IpDocketEvent, IpIdentifier, IpProceeding
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket


def _fixture(
    client: TestClient,
    *,
    with_number: bool,
    side: str = "applicant",
) -> tuple[dict, dict, dict]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    docket = _docket(client, headers, "OPPOSITION FOUNDATION")
    asset = _asset(client, headers, docket["id"], "OPPOSITION FOUNDATION")
    application = _application(client, headers, docket["id"], asset["id"])
    application_number = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": "TM-APP-040A-2026",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registry_application_fixture",
            "effective_from": "2026-08-23",
            "is_primary": True,
            "application_id": application["id"],
        },
    )
    assert application_number.status_code == 201, application_number.text
    body: dict[str, object] = {
        "application_id": application["id"],
        "proceeding_kind": "opposition",
        "side": side,
        "office": "Trade Marks Registry Delhi",
        "jurisdiction": "IN",
        "stage": "draft",
        "origin_kind": "registry_event",
        "source_pending_identifier_allocation": not with_number,
    }
    if with_number:
        body["opposition_number"] = {
            "raw_value": "OPP / 040A / 2026",
            "source": "registry_notice_fixture",
            "effective_from": "2026-08-23",
            "is_primary": True,
        }
    response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json=body,
    )
    assert response.status_code == 201, response.text
    return bootstrap, docket, response.json()


def _transition(
    *,
    bootstrap: dict,
    version: int,
    to_stage: str,
    transition_kind: str = "normal",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": version,
        "to_stage": to_stage,
        "transition_kind": transition_kind,
        "source": "manual",
        "source_reference": "registry:opposition:040a",
        "effective_at": datetime(2026, 8, 23, 8, version, tzinfo=UTC).isoformat(),
        "responsible_membership_id": bootstrap["membership"]["id"],
        "reason": "Reviewed the opposition source and authorized the stage change.",
        "evidence_refs": [f"evidence:opposition:{version}"],
    }
    payload.update(overrides)
    return payload


def _complete_workspace(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
    expected_status: int = 200,
    **overrides: object,
) -> dict:
    body: dict[str, object] = {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": proceeding["version"],
        "source": "manual",
        "source_reference": "registry:opposition:040b",
        "source_notice_reference": "notice:opposition:040b",
        "effective_at": "2026-08-23T07:00:00Z",
        "responsible_membership_id": bootstrap["membership"]["id"],
        "reason": "Confirmed the baseline opposition profile from the source notice.",
        "applicable_rule_version": "trade-marks-rules-2017@2026-08-23",
        "forum": "Trade Marks Registry Delhi",
        "client_instruction_state": "not_required",
        "parties": [
            {
                "role": "applicant",
                "party_name": "Applicant Industries Pvt Ltd",
                "source": "opposition notice",
            },
            {
                "role": "opponent",
                "party_name": "Opponent Brands LLP",
                "source": "opposition notice",
            },
        ],
        "grounds": [
            {
                "category": "earlier_mark",
                "lawyer_detail": "Earlier registered mark asserted against the application.",
                "classification_source": "manual",
            }
        ],
        "challenged_scope": [
            {
                "class_number": 9,
                "goods_services_segment": "Recorded computer software",
            }
        ],
        "service": {
            "method": "registry email",
            "destination": "applicant@example.test",
            "served_on": "2026-08-20",
            "starts_response_period": True,
            "evidence_refs": ["evidence:service:040b"],
        },
        "evidence_refs": ["evidence:notice:040b"],
    }
    body.update(overrides)
    response = client.put(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}"
        "/opposition-workspace",
        headers=auth_headers(str(bootstrap["access_token"])),
        json=body,
    )
    assert response.status_code == expected_status, response.text
    return response.json()


def test_opposition_creation_allocates_separate_number_and_role_template(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=True)

    assert proceeding["stage"] == "draft"
    assert proceeding["origin_kind"] == "registry_event"
    assert proceeding["stage_template_version"] == "opposition-applicant-v1"
    assert proceeding["source_pending_identifier_allocation"] is False

    session = get_session_factory()()
    try:
        identifier = session.scalar(
            select(IpIdentifier).where(IpIdentifier.proceeding_id == proceeding["id"])
        )
        assert identifier is not None
        assert identifier.identifier_kind == "opposition"
        assert identifier.application_id is None
        assert identifier.raw_value == "OPP / 040A / 2026"
        assert identifier.company_id == bootstrap["company"]["id"]
        assert identifier.docket_id == docket["id"]
    finally:
        session.close()


def test_opposition_number_is_required_before_leaving_draft(client: TestClient) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=False)
    headers = auth_headers(str(bootstrap["access_token"]))

    blocked = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage",
        headers=headers,
        json=_transition(bootstrap=bootstrap, version=1, to_stage="notice_filed"),
    )
    assert blocked.status_code == 409
    assert "ip_opposition_identifier_required" in blocked.text

    session = get_session_factory()()
    try:
        row = session.get(IpProceeding, proceeding["id"])
        assert row is not None
        assert row.stage == "draft"
        assert row.version == 1
        assert session.scalar(
            select(IpDocketEvent).where(IpDocketEvent.proceeding_id == proceeding["id"])
        ) is None
    finally:
        session.close()


def test_later_opposition_number_clears_pending_state_and_allows_progression(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=False)
    headers = auth_headers(str(bootstrap["access_token"]))

    number = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "opposition",
            "raw_value": "OPP / LATER / 2026",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registry_notice_fixture",
            "effective_from": "2026-08-23",
            "is_primary": True,
            "proceeding_id": proceeding["id"],
        },
    )
    assert number.status_code == 201, number.text

    session = get_session_factory()()
    try:
        row = session.get(IpProceeding, proceeding["id"])
        assert row is not None
        assert row.source_pending_identifier_allocation is False
    finally:
        session.close()

    _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )

    progressed = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage",
        headers=headers,
        json=_transition(bootstrap=bootstrap, version=1, to_stage="notice_filed"),
    )
    assert progressed.status_code == 200, progressed.text


def test_opposition_number_rejects_a_non_opposition_owner(client: TestClient) -> None:
    bootstrap, docket, opposition = _fixture(client, with_number=True)
    headers = auth_headers(str(bootstrap["access_token"]))
    appeal = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": opposition["application_id"],
            "proceeding_kind": "appeal",
            "side": "other",
            "office": "Delhi High Court",
            "jurisdiction": "IN",
            "stage": "draft",
        },
    )
    assert appeal.status_code == 201, appeal.text

    invalid = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "opposition",
            "raw_value": "OPP / WRONG-OWNER / 2026",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registry_notice_fixture",
            "effective_from": "2026-08-23",
            "is_primary": True,
            "proceeding_id": appeal.json()["id"],
        },
    )
    assert invalid.status_code == 422
    assert "must belong to an opposition proceeding" in invalid.text


def test_role_aware_stage_transitions_are_versioned_and_append_only(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=True)
    headers = auth_headers(str(bootstrap["access_token"]))
    _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    url = f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage"

    filed = client.post(
        url,
        headers=headers,
        json=_transition(bootstrap=bootstrap, version=1, to_stage="notice_filed"),
    )
    assert filed.status_code == 200, filed.text
    assert filed.json()["proceeding"]["stage"] == "notice_filed"
    assert filed.json()["proceeding"]["version"] == 2
    assert filed.json()["event"]["before_phase"] == "draft"
    assert filed.json()["event"]["after_phase"] == "notice_filed"

    # A second distinct stage on the same legal date is not a duplicate.
    served = client.post(
        url,
        headers=headers,
        json=_transition(bootstrap=bootstrap, version=2, to_stage="service_pending"),
    )
    assert served.status_code == 200, served.text
    assert served.json()["event"]["sequence"] == 3

    stale = client.post(
        url,
        headers=headers,
        json=_transition(
            bootstrap=bootstrap,
            version=1,
            to_stage="counterstatement_due",
            effective_at="2026-08-23T08:03:00Z",
        ),
    )
    assert stale.status_code == 409
    assert "version changed" in stale.text

    invalid_jump = client.post(
        url,
        headers=headers,
        json=_transition(bootstrap=bootstrap, version=3, to_stage="decided"),
    )
    assert invalid_jump.status_code == 409
    assert "is not allowed" in invalid_jump.text

    session = get_session_factory()()
    try:
        events = list(
            session.scalars(
                select(IpDocketEvent)
                .where(
                    IpDocketEvent.proceeding_id == proceeding["id"],
                    IpDocketEvent.event_kind == "lifecycle_transition",
                )
                .order_by(IpDocketEvent.sequence)
            )
        )
        assert [row.after_phase for row in events] == ["notice_filed", "service_pending"]
        assert events[0].payload_json["expected_proceeding_version"] == 1
        assert events[1].payload_json["expected_proceeding_version"] == 2
    finally:
        session.close()


def test_exception_and_closure_paths_require_authority_and_complete_evidence(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=True)
    headers = auth_headers(str(bootstrap["access_token"]))
    _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    url = f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage"

    missing_authority = client.post(
        url,
        headers=headers,
        json=_transition(
            bootstrap=bootstrap,
            version=1,
            to_stage="counterstatement_due",
            transition_kind="skipped",
        ),
    )
    assert missing_authority.status_code == 422

    skipped = client.post(
        url,
        headers=headers,
        json=_transition(
            bootstrap=bootstrap,
            version=1,
            to_stage="counterstatement_due",
            transition_kind="skipped",
            authority_reference="order:registry:skip-service",
        ),
    )
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["event"]["payload_json"]["transition_kind"] == "skipped"

    incomplete_close = client.post(
        url,
        headers=headers,
        json=_transition(bootstrap=bootstrap, version=2, to_stage="closed"),
    )
    assert incomplete_close.status_code == 422
    assert "Closure requires" in incomplete_close.text

    closed = client.post(
        url,
        headers=headers,
        json=_transition(
            bootstrap=bootstrap,
            version=2,
            to_stage="closed",
            transition_kind="waived",
            authority_reference="order:registry:deemed-abandoned",
            outcome="deemed_abandoned",
            outcome_effective_date="2026-08-23",
            authorized_confirmation="membership:reviewer:fixture",
        ),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["proceeding"]["stage"] == "closed"


def test_generic_event_route_cannot_bypass_opposition_transition_contract(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, with_number=True)
    headers = auth_headers(str(bootstrap["access_token"]))
    bypass = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "proceeding_id": proceeding["id"],
            "event_kind": "lifecycle_transition",
            "source": "manual",
            "effective_at": "2026-08-23T09:00:00Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Attempted untyped stage transition through the generic route.",
            "evidence_refs": ["evidence:bypass"],
            "resulting_stage": "decided",
        },
    )
    assert bypass.status_code == 409
    assert "version changed" in bypass.text
