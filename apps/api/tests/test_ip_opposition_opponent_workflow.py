from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from caseops_api.core.settings import get_settings
from caseops_api.schemas.ip_oppositions import IpOppositionOpponentActionRequest
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _member,
    _responsibilities,
    _rule_payload,
)
from tests.test_ip_opposition_applicant_workflow import _stage
from tests.test_ip_opposition_foundation import _complete_workspace
from tests.test_ip_record_workflow import _application, _asset, _particulars

_OPPONENT_WORKFLOW_ROUTE = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opponent-workflow"
)
_OPPONENT_ACTIONS_ROUTE = "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opponent-actions"
_OPPONENT_DEADLINES_ROUTE = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opponent-deadlines"
)


def _route(template: str, docket: dict, proceeding: dict) -> str:
    return template.format(docket_id=docket["id"], proceeding_id=proceeding["id"])


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _fixture(
    client: TestClient,
    *,
    origin_kind: str = "manual_intake",
) -> tuple[dict, dict, dict, dict]:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IPLF-042")
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "IPLF-042 opponent opposition",
            "matter_id": matter["id"],
            "restricted": False,
            "particulars": _particulars("IPLF-042 TARGET MARK"),
        },
    )
    assert response.status_code == 201, response.text
    docket = response.json()
    asset = _asset(client, headers, docket["id"], "IPLF-042 TARGET MARK")
    application = _application(client, headers, docket["id"], asset["id"])
    application_number = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": "TM-APP-042-2026",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registry-application:042",
            "effective_from": "2026-08-23",
            "is_primary": True,
            "application_id": application["id"],
        },
    )
    assert application_number.status_code == 201, application_number.text
    proceeding = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": application["id"],
            "proceeding_kind": "opposition",
            "side": "opponent",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "stage": "draft",
            "origin_kind": origin_kind,
            "source_pending_identifier_allocation": True,
        },
    )
    assert proceeding.status_code == 201, proceeding.text
    return bootstrap, matter, docket, proceeding.json()


def _profile(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
    instruction_state: str = "confirmed",
) -> dict:
    return _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        client_instruction_state=instruction_state,
        client_instruction_reference=(
            "client-instruction:042" if instruction_state == "confirmed" else None
        ),
        limitation_date="2026-09-22",
        relied_on_rights=[
            {
                "mark_or_right": "IPLF-042 EARLIER MARK",
                "jurisdiction": "IN",
                "identifier": "TM-EARLIER-042",
                "status": "registered",
                "owner": "Opponent Brands LLP",
                "goods_services": "Recorded computer software",
                "reputation_claim": None,
                "use_claim": "Used continuously since 2019",
                "evidence_refs": ["registry:earlier-right:042"],
            }
        ],
        service=None,
    )


def _governed_rule(
    client: TestClient,
    *,
    bootstrap: dict,
    workflow_stage: str,
) -> tuple[dict, dict, str, str]:
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    suffix = workflow_stage.replace("_", "-")
    legal_id, legal_token = _member(
        client,
        token,
        name=f"IPLF 042 legal {suffix}",
        email=f"iplf-042-legal-{suffix}@asterlegal.in",
    )
    reviewer_id, _ = _member(
        client,
        token,
        name=f"IPLF 042 reviewer {suffix}",
        email=f"iplf-042-reviewer-{suffix}@asterlegal.in",
    )
    calendar_payload = _calendar_payload()
    calendar_payload["key"] = f"ip-india-042-{suffix}"
    calendar = client.post("/api/ip/working-calendars", headers=headers, json=calendar_payload)
    assert calendar.status_code == 201, calendar.text
    activated_calendar = client.post(
        f"/api/ip/working-calendars/{calendar.json()['id']}/activate",
        headers=auth_headers(legal_token),
        json={"reason": "Verified the synthetic official calendar fixture."},
    )
    assert activated_calendar.status_code == 200, activated_calendar.text

    rule_payload = _rule_payload()
    rule_payload.update(
        {
            "key": f"in-tm-opposition-opponent-{suffix}",
            "proceeding_kind": "opposition",
            "role": "opponent",
            "stage": workflow_stage,
            "source_record_id": f"tm-rules-opponent-{suffix}",
        }
    )
    trigger_kind = {
        "notice_filing_due": "trademark_publication",
        "opponent_evidence_due": "counterstatement_filed",
        "reply_evidence_due": "applicant_evidence_filed",
    }[workflow_stage]
    rule_payload["definition"]["trigger_kind"] = trigger_kind
    rule_payload["fixtures"][0]["calculation"]["trigger_kind"] = trigger_kind
    rule = client.post("/api/ip/deadline-rules", headers=headers, json=rule_payload)
    assert rule.status_code == 201, rule.text
    activated_rule = client.post(
        f"/api/ip/deadline-rules/{rule.json()['id']}/activate",
        headers=auth_headers(legal_token),
        json={
            "reviewer_membership_id": reviewer_id,
            "select_for_company": True,
            "auto_confirm_eligible": False,
        },
    )
    assert activated_rule.status_code == 200, activated_rule.text
    return activated_rule.json(), activated_calendar.json(), legal_id, reviewer_id


def _propose_and_confirm(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
    workflow_stage: str,
    trigger_event_id: str,
) -> dict:
    rule, calendar, primary_id, backup_id = _governed_rule(
        client,
        bootstrap=bootstrap,
        workflow_stage=workflow_stage,
    )
    headers = auth_headers(str(bootstrap["access_token"]))
    proposal = client.post(
        _route(_OPPONENT_DEADLINES_ROUTE, docket, proceeding),
        headers=headers,
        json={
            "workflow_stage": workflow_stage,
            "trigger_event_id": trigger_event_id,
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-23",
            "base_date_certainty": "certain",
            "date_precision": "date",
            "is_critical": True,
        },
    )
    assert proposal.status_code == 201, proposal.text
    deadline = proposal.json()["deadline"]
    confirmed = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(primary_id, backup_id),
            "reminder_offsets_days": [7, 1, 0],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def _action(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
    version: int,
    action_kind: str,
    **overrides: object,
) -> dict:
    body: dict[str, object] = {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": version,
        "action_kind": action_kind,
        "source": "manual",
        "source_reference": f"source:{action_kind}:042",
        "effective_at": f"2026-08-23T08:{version - 1:02d}:30Z",
        "responsible_membership_id": bootstrap["membership"]["id"],
        "reason": f"Lawyer confirmed the opponent {action_kind.replace('_', ' ')} action.",
        "evidence_refs": [f"evidence:{action_kind}:042"],
    }
    body.update(overrides)
    response = client.post(
        _route(_OPPONENT_ACTIONS_ROUTE, docket, proceeding),
        headers=auth_headers(str(bootstrap["access_token"])),
        json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_number(client: TestClient, *, bootstrap: dict, docket: dict, proceeding: dict) -> None:
    response = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "identifier_kind": "opposition",
            "raw_value": "OPP / 042 / 2026",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registry-allocation:042",
            "effective_from": "2026-08-23",
            "is_primary": True,
            "proceeding_id": proceeding["id"],
        },
    )
    assert response.status_code == 201, response.text


def _opponent_action_validation_payload() -> dict[str, object]:
    return {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": 1,
        "action_kind": "notice_filed",
        "source": "manual",
        "source_reference": "registry-filing:042",
        "effective_at": "2026-08-23T08:00:00Z",
        "responsible_membership_id": "membership:042",
        "reason": "Counsel reviewed and approved the signed notice.",
        "filing_reference": "TM-O-ACK-042",
        "filed_on": "2026-08-23",
        "verification": {
            "signatory": "Authorized Signatory",
            "authority": "Board authority",
            "place": "New Delhi",
            "verified_on": "2026-08-23",
            "verified_paragraph_ranges": ["1-14", "verification"],
            "knowledge_basis": "Personal knowledge and company records",
            "signed_document_ref": "document:signed-tmo:042",
        },
        "evidence_refs": ["filing-receipt:042"],
        "document_refs": ["document:signed-tmo:042"],
    }


def _assert_model_error(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError) as error:
        IpOppositionOpponentActionRequest.model_validate(payload)
    assert message in str(error.value)


def test_iplf_uj_13_normal_tracks_notice_rule45_and_rule47(client: TestClient) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    workspace = _profile(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        workflow_stage="notice_filing_due",
        trigger_event_id=workspace["profile_event"]["id"],
    )
    filed = _action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        version=1,
        action_kind="notice_filed",
        filing_reference="TM-O-ACK-042",
        filed_on="2026-08-23",
        verification={
            "signatory": "Opponent Authorized Signatory",
            "authority": "Board authorization dated 2026-08-22",
            "place": "New Delhi",
            "verified_on": "2026-08-23",
            "verified_paragraph_ranges": ["1-14", "verification"],
            "knowledge_basis": "Personal knowledge and opponent company records.",
            "signed_document_ref": "document:tm-o-signed:042",
        },
        document_refs=["document:tm-o-signed:042"],
    )
    assert filed["next_required_action"] == "record_opposition_number"
    _add_number(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=1,
        to_stage="notice_filed",
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=2,
        to_stage="service_pending",
    )
    _action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        version=3,
        action_kind="notice_served",
        service={
            "method": "registered email",
            "destination": "applicant-counsel@example.test",
            "served_on": "2026-08-23",
            "acknowledgement": "Delivery acknowledged",
            "starts_response_period": True,
            "evidence_refs": ["service-receipt:notice:042"],
        },
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=3,
        to_stage="counterstatement_due",
    )
    counterstatement = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=4,
        to_stage="counterstatement_filed",
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=5,
        to_stage="opponent_evidence_due",
    )
    _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        workflow_stage="opponent_evidence_due",
        trigger_event_id=counterstatement["event"]["id"],
    )
    _action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        version=6,
        action_kind="opponent_evidence_decision",
        evidence_election="rely_on_pleaded_facts",
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=6,
        to_stage="opponent_evidence_filed",
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=7,
        to_stage="applicant_evidence_due",
    )
    applicant_evidence = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=8,
        to_stage="applicant_evidence_filed",
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=9,
        to_stage="reply_evidence_due",
    )
    _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        workflow_stage="reply_evidence_due",
        trigger_event_id=applicant_evidence["event"]["id"],
    )
    result = _action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        version=10,
        action_kind="reply_evidence_decision",
        evidence_election="no_reply_evidence",
    )
    assert len(result["deadlines"]) == 3
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=10,
        to_stage="reply_evidence_filed",
    )
    response = client.get(
        _route(_OPPONENT_WORKFLOW_ROUTE, docket, proceeding),
        headers=auth_headers(str(bootstrap["access_token"])),
    )
    assert response.status_code == 200, response.text
    assert response.json()["next_required_action"] == "await_hearing_or_later_stage"


def test_iplf_uj_13_exc_01_closes_watch_hit_without_filing(client: TestClient) -> None:
    bootstrap, _, docket, proceeding = _fixture(client, origin_kind="watch_hit")
    _profile(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    result = _action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        version=1,
        action_kind="watch_hit_closed",
    )
    assert result["next_required_action"] == "watch_hit_closed_no_proceeding"
    assert result["opposition_number_status"] == "pending_allocation"


def test_iplf_uj_13_exc_02_pending_instruction_escalates_before_limitation(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    workspace = _profile(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        instruction_state="pending",
    )
    _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        workflow_stage="notice_filing_due",
        trigger_event_id=workspace["profile_event"]["id"],
    )
    result = _action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        version=1,
        action_kind="client_instruction_escalated",
        escalation_reference="client-escalation:042",
        escalation_due_on="2026-09-15",
    )
    assert result["next_required_action"] == "await_client_instruction"
    tasks = client.get(
        f"/api/ip/tasks?docket_id={docket['id']}",
        headers=auth_headers(str(bootstrap["access_token"])),
    )
    assert tasks.status_code == 200, tasks.text
    assert tasks.json()["tasks"][0]["priority"] == "urgent"
    assert tasks.json()["tasks"][0]["due_on"] == "2026-09-15"


def test_iplf_uj_13_exc_03_rejection_opens_task_without_filed_stage(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    workspace = _profile(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        workflow_stage="notice_filing_due",
        trigger_event_id=workspace["profile_event"]["id"],
    )
    result = _action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        version=1,
        action_kind="notice_filing_rejected",
        rejection_reference="registry-rejection:042",
        corrective_due_on="2026-08-25",
    )
    assert result["next_required_action"] == "correct_rejected_notice"
    assert result["corrective_task_id"]
    assert result["opponent_actions"][0]["resulting_stage"] is None
    _add_number(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )

    blocked = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "expected_lifecycle_version": 0,
            "expected_proceeding_version": 1,
            "to_stage": "notice_filed",
            "transition_kind": "normal",
            "source": "manual",
            "source_reference": "registry:opposition:042",
            "effective_at": "2026-08-23T10:00:00Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Attempted stage transition without an accepted corrected filing.",
            "evidence_refs": ["evidence:rejection:042"],
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ip_opposition_opponent_action_required"


def test_opponent_workflow_enforces_capability_and_tenant_boundaries(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    _profile(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    owner_token = str(bootstrap["access_token"])
    member_email = "iplf-042-reader@asterlegal.in"
    created_member = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "IPLF 042 Reader",
            "email": member_email,
            "password": "OpponentReader123!",
            "role": "member",
        },
    )
    assert created_member.status_code == 200, created_member.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": member_email,
            "password": "OpponentReader123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    member_headers = auth_headers(str(login.json()["access_token"]))
    workflow_url = _route(_OPPONENT_WORKFLOW_ROUTE, docket, proceeding)
    readable = client.get(workflow_url, headers=member_headers)
    assert readable.status_code == 200, readable.text
    denied = client.post(
        _route(_OPPONENT_DEADLINES_ROUTE, docket, proceeding),
        headers=member_headers,
        json={
            "workflow_stage": "notice_filing_due",
            "trigger_event_id": "outside-capability",
            "rule_version_id": "outside-capability",
            "calendar_version_id": "outside-capability",
            "base_date": None,
            "base_date_certainty": "unknown",
            "date_precision": "date",
            "is_critical": True,
        },
    )
    assert denied.status_code == 403, denied.text

    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "IPLF 042 Other Tenant",
            "company_slug": "iplf-042-other-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Other Tenant Owner",
            "owner_email": "owner@iplf-042-other.example",
            "owner_password": "OtherTenant123!",
        },
    )
    assert second.status_code == 200, second.text
    client.cookies.clear()
    hidden = client.get(
        workflow_url,
        headers=auth_headers(str(second.json()["access_token"])),
    )
    assert hidden.status_code == 404, hidden.text


def test_opponent_action_schema_rejects_incomplete_or_misplaced_evidence() -> None:
    cases: list[tuple[dict[str, object], str]] = []

    payload = _opponent_action_validation_payload()
    payload["effective_at"] = "2026-08-23T08:00:00"
    cases.append((payload, "Opponent action time must include a timezone"))

    payload = _opponent_action_validation_payload()
    payload.pop("filing_reference")
    cases.append((payload, "A filed TM-O notice requires filing facts"))

    payload = _opponent_action_validation_payload()
    payload.update({"action_kind": "notice_filing_rejected", "verification": None})
    cases.append((payload, "A rejected TM-O filing requires rejection evidence"))

    payload = _opponent_action_validation_payload()
    payload.update({"action_kind": "notice_served", "verification": None})
    cases.append((payload, "TM-O notice service requires complete service facts"))

    payload = _opponent_action_validation_payload()
    payload.update({"action_kind": "client_instruction_escalated", "verification": None})
    cases.append((payload, "Client-instruction escalation requires a reference"))

    payload = _opponent_action_validation_payload()
    payload.update({"action_kind": "opponent_evidence_decision", "verification": None})
    cases.append((payload, "Rule 45 requires an explicit evidence"))

    payload = _opponent_action_validation_payload()
    payload.update({"action_kind": "reply_evidence_decision", "verification": None})
    cases.append((payload, "Rule 47 requires an explicit reply-evidence election"))

    payload = _opponent_action_validation_payload()
    payload["evidence_election"] = "rely_on_pleaded_facts"
    cases.append((payload, "An evidence election is only valid for an evidence decision"))

    payload = _opponent_action_validation_payload()
    payload.update(
        {
            "action_kind": "opponent_evidence_decision",
            "verification": None,
            "evidence_election": "file_evidence",
            "evidence_refs": [],
            "document_refs": [],
        }
    )
    cases.append((payload, "Filed evidence requires document and filing evidence references"))

    payload = _opponent_action_validation_payload()
    payload.update(
        {
            "action_kind": "watch_hit_closed",
            "verification": None,
            "evidence_refs": [],
        }
    )
    cases.append((payload, "Closing a watch hit requires source evidence"))

    for invalid_payload, message in cases:
        _assert_model_error(invalid_payload, message)


def test_opponent_actions_and_deadlines_fail_closed_out_of_sequence(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    _profile(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    headers = auth_headers(str(bootstrap["access_token"]))
    ungoverned_action = client.post(
        _route(_OPPONENT_ACTIONS_ROUTE, docket, proceeding),
        headers=headers,
        json={
            **_opponent_action_validation_payload(),
            "responsible_membership_id": bootstrap["membership"]["id"],
        },
    )
    assert ungoverned_action.status_code == 409, ungoverned_action.text
    assert "Confirm the governed notice filing due" in ungoverned_action.json()["detail"]

    _add_number(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    staged = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=1,
        to_stage="withdrawn",
    )
    rule, calendar, _, _ = _governed_rule(
        client,
        bootstrap=bootstrap,
        workflow_stage="notice_filing_due",
    )
    out_of_stage = client.post(
        _route(_OPPONENT_DEADLINES_ROUTE, docket, proceeding),
        headers=headers,
        json={
            "workflow_stage": "notice_filing_due",
            "trigger_event_id": staged["event"]["id"],
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-23",
            "base_date_certainty": "certain",
            "date_precision": "date",
            "is_critical": True,
        },
    )
    assert out_of_stage.status_code == 409, out_of_stage.text
    assert "requires opposition stage 'draft'" in out_of_stage.json()["detail"]
