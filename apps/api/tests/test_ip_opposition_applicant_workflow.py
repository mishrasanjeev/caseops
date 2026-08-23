from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from caseops_api.core.settings import get_settings
from caseops_api.db.models import Matter
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_oppositions import (
    IpOppositionApplicantActionRequest,
    IpOppositionServiceFact,
    IpOppositionWorkspaceUpsertRequest,
)
from caseops_api.schemas.ip_records import IpOppositionStageTransitionRequest
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _member,
    _responsibilities,
    _rule_payload,
)
from tests.test_ip_opposition_foundation import _complete_workspace, _transition
from tests.test_ip_record_workflow import _application, _asset, _particulars

_APPLICANT_WORKFLOW_ROUTE = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/applicant-workflow"
)
_APPLICANT_ACTIONS_ROUTE = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/applicant-actions"
)
_APPLICANT_DEADLINES_ROUTE = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/applicant-deadlines"
)


def _applicant_route(template: str, *, docket_id: str, proceeding_id: str) -> str:
    return template.format(docket_id=docket_id, proceeding_id=proceeding_id)


def _assert_model_error(model: type[BaseModel], payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        model.model_validate(payload)


def _workspace_validation_payload() -> dict[str, object]:
    return {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": 1,
        "source": "manual",
        "source_reference": "registry:opposition:041",
        "effective_at": "2026-08-23T08:00:00Z",
        "responsible_membership_id": "membership:041",
        "reason": "Validated the opposition workspace source facts.",
        "applicable_rule_version": "trade-marks-rules-2017@2026-08-23",
        "forum": "Trade Marks Registry Delhi",
        "client_instruction_state": "not_required",
        "parties": [
            {"role": "applicant", "party_name": "Applicant One", "source": "notice"},
            {"role": "opponent", "party_name": "Opponent One", "source": "notice"},
        ],
        "grounds": [
            {
                "category": "earlier_mark",
                "lawyer_detail": "Earlier registered mark relied upon in the notice.",
            }
        ],
        "challenged_scope": [{"class_number": 9, "goods_services_segment": "Computer software"}],
    }


def _applicant_action_validation_payload() -> dict[str, object]:
    return {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": 1,
        "action_kind": "counterstatement_filed",
        "source": "manual",
        "source_reference": "filing:counterstatement:041",
        "effective_at": "2026-08-23T08:00:00Z",
        "responsible_membership_id": "membership:041",
        "reason": "Recorded the signed counterstatement filing facts.",
        "filing_reference": "TM-O:041",
        "filed_on": "2026-08-23",
        "verification": {
            "signatory": "Applicant Counsel",
            "authority": "Authorized counsel for the applicant",
            "place": "New Delhi",
            "verified_on": "2026-08-23",
            "verified_paragraph_ranges": ["1-12"],
            "knowledge_basis": "Records and instructions supplied by the applicant.",
            "signed_document_ref": "document:signed-counterstatement:041",
        },
        "evidence_refs": ["filing-receipt:041"],
        "document_refs": ["document:counterstatement:041"],
    }


def _transition_validation_payload() -> dict[str, object]:
    return {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": 1,
        "to_stage": "counterstatement_due",
        "transition_kind": "normal",
        "source": "manual",
        "source_reference": "registry:opposition:041",
        "effective_at": "2026-08-23T08:00:00Z",
        "responsible_membership_id": "membership:041",
        "reason": "Validated the source and authorized the stage transition.",
        "evidence_refs": ["evidence:transition:041"],
    }


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _fixture(
    client: TestClient,
    *,
    with_number: bool = True,
) -> tuple[dict, dict, dict, dict]:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IPLF-041")
    docket_response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "IPLF-041 applicant opposition",
            "matter_id": matter["id"],
            "restricted": False,
            "particulars": _particulars("IPLF-041 APPLICANT MARK"),
        },
    )
    assert docket_response.status_code == 201, docket_response.text
    docket = docket_response.json()
    asset = _asset(client, headers, docket["id"], "IPLF-041 APPLICANT MARK")
    application = _application(client, headers, docket["id"], asset["id"])
    application_number = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "application",
            "raw_value": "TM-APP-041-2026",
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
        "side": "applicant",
        "office": "Trade Marks Registry Delhi",
        "jurisdiction": "IN",
        "stage": "draft",
        "origin_kind": "registry_event",
        "source_pending_identifier_allocation": not with_number,
    }
    if with_number:
        body["opposition_number"] = {
            "raw_value": "OPP / 041 / 2026",
            "source": "registry_notice_fixture",
            "effective_from": "2026-08-23",
            "is_primary": True,
        }
    proceeding_response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json=body,
    )
    assert proceeding_response.status_code == 201, proceeding_response.text
    return bootstrap, matter, docket, proceeding_response.json()


def _governed_deadline_rule(
    client: TestClient,
    *,
    bootstrap: dict,
    workflow_stage: str,
    suffix: str,
) -> tuple[dict, dict, str, str]:
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client,
        owner_token,
        name=f"IPLF 041 legal {suffix}",
        email=f"iplf-041-legal-{suffix}@asterlegal.in",
    )
    reviewer_id, _ = _member(
        client,
        owner_token,
        name=f"IPLF 041 reviewer {suffix}",
        email=f"iplf-041-reviewer-{suffix}@asterlegal.in",
    )
    legal_headers = auth_headers(legal_token)

    calendar_payload = _calendar_payload()
    calendar_payload["key"] = f"ip-india-041-{suffix}"
    calendar = client.post(
        "/api/ip/working-calendars",
        headers=owner_headers,
        json=calendar_payload,
    )
    assert calendar.status_code == 201, calendar.text
    activated_calendar = client.post(
        f"/api/ip/working-calendars/{calendar.json()['id']}/activate",
        headers=legal_headers,
        json={"reason": "Verified the synthetic official calendar fixture."},
    )
    assert activated_calendar.status_code == 200, activated_calendar.text

    rule_payload = _rule_payload()
    rule_payload.update(
        {
            "key": f"in-tm-opposition-applicant-{workflow_stage}-{suffix}",
            "proceeding_kind": "opposition",
            "role": "applicant",
            "stage": workflow_stage,
            "source_record_id": f"tm-rules-applicant-{workflow_stage}-{suffix}",
        }
    )
    rule_payload["definition"]["trigger_kind"] = (
        "opposition_notice_served"
        if workflow_stage == "counterstatement_due"
        else "opponent_evidence_filed"
    )
    rule_payload["fixtures"][0]["calculation"]["trigger_kind"] = rule_payload["definition"][
        "trigger_kind"
    ]
    rule = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=rule_payload,
    )
    assert rule.status_code == 201, rule.text
    activated_rule = client.post(
        f"/api/ip/deadline-rules/{rule.json()['id']}/activate",
        headers=legal_headers,
        json={
            "reviewer_membership_id": reviewer_id,
            "select_for_company": True,
            "auto_confirm_eligible": False,
        },
    )
    assert activated_rule.status_code == 200, activated_rule.text
    return activated_rule.json(), activated_calendar.json(), legal_id, reviewer_id


def _stage(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding_id: str,
    version: int,
    to_stage: str,
    **overrides: object,
) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding_id}/stage",
        headers=auth_headers(str(bootstrap["access_token"])),
        json=_transition(
            bootstrap=bootstrap,
            version=version,
            to_stage=to_stage,
            **overrides,
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _propose_and_confirm(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding_id: str,
    workflow_stage: str,
    trigger_event_id: str,
    rule: dict,
    calendar: dict,
    primary_id: str,
    backup_id: str,
) -> dict:
    headers = auth_headers(str(bootstrap["access_token"]))
    proposal = client.post(
        _applicant_route(
            _APPLICANT_DEADLINES_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding_id,
        ),
        headers=headers,
        json={
            "workflow_stage": workflow_stage,
            "trigger_event_id": trigger_event_id,
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-20",
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
    assert confirmed.json()["state"] == "confirmed"
    return confirmed.json()


def test_uj12_exc01_pending_opposition_number_is_explicit(client: TestClient) -> None:
    bootstrap, _, docket, proceeding = _fixture(client, with_number=False)
    response = client.get(
        _applicant_route(
            _APPLICANT_WORKFLOW_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding["id"],
        ),
        headers=auth_headers(str(bootstrap["access_token"])),
    )
    assert response.status_code == 200, response.text
    assert response.json()["opposition_number_status"] == "pending_allocation"
    assert response.json()["next_required_action"] == "record_opposition_number"


def test_uj12_normal_runs_confirmed_deadlines_and_applicant_work_product(
    client: TestClient,
) -> None:
    bootstrap, matter, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    workspace = _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    counter_rule, counter_calendar, primary_id, backup_id = _governed_deadline_rule(
        client,
        bootstrap=bootstrap,
        workflow_stage="counterstatement_due",
        suffix="counter",
    )
    counter_deadline = _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        workflow_stage="counterstatement_due",
        trigger_event_id=workspace["profile_event"]["id"],
        rule=counter_rule,
        calendar=counter_calendar,
        primary_id=primary_id,
        backup_id=backup_id,
    )
    assert counter_deadline["matter_deadline_id"] is not None
    before_stage_progression = client.get(
        _applicant_route(
            _APPLICANT_WORKFLOW_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding["id"],
        ),
        headers=headers,
    )
    assert before_stage_progression.status_code == 200
    assert before_stage_progression.json()["next_required_action"] == (
        "advance_to_counterstatement_due"
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
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=3,
        to_stage="counterstatement_due",
    )

    blocked_without_work_product = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage",
        headers=headers,
        json=_transition(
            bootstrap=bootstrap,
            version=4,
            to_stage="counterstatement_filed",
        ),
    )
    assert blocked_without_work_product.status_code == 409
    assert blocked_without_work_product.json()["code"] == (
        "ip_opposition_applicant_action_required"
    )

    filed = client.post(
        _applicant_route(
            _APPLICANT_ACTIONS_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding["id"],
        ),
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "expected_proceeding_version": 4,
            "action_kind": "counterstatement_filed",
            "source": "manual",
            "source_reference": "registry-filing:counterstatement:041",
            "effective_at": "2026-08-23T08:03:30Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Recorded the lawyer-approved TM-O counterstatement filing.",
            "filing_reference": "TM-O-ACK-041",
            "filed_on": "2026-08-23",
            "verification": {
                "signatory": "Applicant Authorized Signatory",
                "authority": "Board authorization dated 2026-08-22",
                "place": "New Delhi",
                "verified_on": "2026-08-23",
                "verified_paragraph_ranges": ["1-12", "verification"],
                "knowledge_basis": "Personal knowledge and company records.",
                "signed_document_ref": "ip-document:counterstatement:signed:041",
            },
            "evidence_refs": ["filing-receipt:counterstatement:041"],
            "document_refs": ["ip-document:counterstatement:signed:041"],
        },
    )
    assert filed.status_code == 201, filed.text
    assert (
        filed.json()["applicant_actions"][0]["payload_json"]["document_classification"]
        == "tm_o_counterstatement"
    )
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=4,
        to_stage="counterstatement_filed",
    )
    served = client.post(
        _applicant_route(
            _APPLICANT_ACTIONS_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding["id"],
        ),
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "expected_proceeding_version": 5,
            "action_kind": "counterstatement_served",
            "source": "manual",
            "source_reference": "service:counterstatement:041",
            "effective_at": "2026-08-23T08:04:30Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Recorded service of the filed counterstatement on the opponent.",
            "service": {
                "method": "registered email",
                "destination": "opponent-counsel@example.test",
                "served_on": "2026-08-23",
                "acknowledgement": "Delivery acknowledged",
                "starts_response_period": True,
                "evidence_refs": ["service-receipt:counterstatement:041"],
            },
        },
    )
    assert served.status_code == 201, served.text
    assert served.json()["next_required_action"] == "await_opponent_or_later_stage"

    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=5,
        to_stage="opponent_evidence_due",
    )
    opponent_filed = _stage(
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
    evidence_rule, evidence_calendar, evidence_primary, evidence_backup = _governed_deadline_rule(
        client,
        bootstrap=bootstrap,
        workflow_stage="applicant_evidence_due",
        suffix="evidence",
    )
    _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        workflow_stage="applicant_evidence_due",
        trigger_event_id=opponent_filed["event"]["id"],
        rule=evidence_rule,
        calendar=evidence_calendar,
        primary_id=evidence_primary,
        backup_id=evidence_backup,
    )
    election = client.post(
        _applicant_route(
            _APPLICANT_ACTIONS_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding["id"],
        ),
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "expected_proceeding_version": 8,
            "action_kind": "applicant_evidence_decision",
            "source": "manual",
            "source_reference": "instruction:rule-46:041",
            "effective_at": "2026-08-23T08:07:30Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Counsel elected to rely on the pleaded counterstatement facts.",
            "evidence_election": "rely_on_pleaded_facts",
            "evidence_refs": ["lawyer-instruction:rule-46:041"],
        },
    )
    assert election.status_code == 201, election.text
    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=8,
        to_stage="applicant_evidence_filed",
    )
    workflow = client.get(
        _applicant_route(
            _APPLICANT_WORKFLOW_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding["id"],
        ),
        headers=headers,
    )
    assert workflow.status_code == 200, workflow.text
    assert len(workflow.json()["deadlines"]) == 2
    assert workflow.json()["next_required_action"] == "await_opponent_or_later_stage"

    _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=9,
        to_stage="withdrawn",
    )
    with get_session_factory()() as session:
        linked_matter = session.get(Matter, matter["id"])
        assert linked_matter is not None
        assert linked_matter.status == "active"


def test_uj12_exc02_exception_requires_source_evidence_and_approval(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    _complete_workspace(
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
        to_stage="counterstatement_due",
    )
    url = f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage"
    incomplete = _transition(
        bootstrap=bootstrap,
        version=3,
        to_stage="counterstatement_due",
        transition_kind="extended",
        authority_reference="registry-order:extension:041",
    )
    incomplete.pop("source_reference")
    incomplete.pop("evidence_refs")
    rejected = client.post(url, headers=headers, json=incomplete)
    assert rejected.status_code == 422

    accepted = client.post(
        url,
        headers=headers,
        json=_transition(
            bootstrap=bootstrap,
            version=3,
            to_stage="counterstatement_due",
            transition_kind="extended",
            authority_reference="registry-order:extension:041",
            authorized_confirmation="membership:approver:041",
            effective_at="2026-08-24T09:00:00Z",
        ),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["event"]["payload_json"]["transition_kind"] == "extended"


def test_applicant_workflow_enforces_capability_and_tenant_boundaries(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    owner_token = str(bootstrap["access_token"])
    member_email = "iplf-041-reader@asterlegal.in"
    created_member = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "IPLF 041 Reader",
            "email": member_email,
            "password": "ApplicantReader123!",
            "role": "member",
        },
    )
    assert created_member.status_code == 200, created_member.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": member_email,
            "password": "ApplicantReader123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    member_headers = auth_headers(str(login.json()["access_token"]))
    workflow_url = _applicant_route(
        _APPLICANT_WORKFLOW_ROUTE,
        docket_id=docket["id"],
        proceeding_id=proceeding["id"],
    )
    readable = client.get(workflow_url, headers=member_headers)
    assert readable.status_code == 200, readable.text
    denied = client.post(
        _applicant_route(
            _APPLICANT_DEADLINES_ROUTE,
            docket_id=docket["id"],
            proceeding_id=proceeding["id"],
        ),
        headers=member_headers,
        json={
            "workflow_stage": "counterstatement_due",
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
            "company_name": "IPLF 041 Other Tenant",
            "company_slug": "iplf-041-other-tenant",
            "company_type": "law_firm",
            "owner_full_name": "Other Tenant Owner",
            "owner_email": "owner@iplf-041-other.example",
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


def test_opposition_workspace_schema_rejects_incomplete_or_ambiguous_facts() -> None:
    invalid_reservice = {
        "method": "email",
        "destination": "opponent@example.test",
        "served_on": "2026-08-23",
        "reservice_on": "2026-08-22",
        "evidence_refs": ["service-receipt:041"],
    }
    _assert_model_error(
        IpOppositionServiceFact,
        invalid_reservice,
        "Re-service date cannot precede",
    )

    cases: list[tuple[dict[str, object], str]] = []

    payload = _workspace_validation_payload()
    payload["effective_at"] = "2026-08-23T08:00:00"
    cases.append((payload, "Opposition profile time must include a timezone"))

    payload = _workspace_validation_payload()
    payload.update({"source": "registry", "source_reference": None})
    cases.append((payload, "Registry opposition profiles require a source reference"))

    payload = _workspace_validation_payload()
    payload["parties"] = [
        {"role": "applicant", "party_name": "Applicant One", "source": "notice"},
        {"role": "agent", "party_name": "Applicant Agent", "source": "notice"},
    ]
    cases.append((payload, "requires both applicant and opponent parties"))

    payload = _workspace_validation_payload()
    payload["parties"] = [
        {"role": "applicant", "party_name": "Applicant One", "source": "notice"},
        {"role": "applicant", "party_name": " applicant one ", "source": "notice"},
        {"role": "opponent", "party_name": "Opponent One", "source": "notice"},
    ]
    cases.append((payload, "Duplicate opposition party and role entries"))

    payload = _workspace_validation_payload()
    payload["challenged_scope"] = [
        {"class_number": 9, "goods_services_segment": "Computer software"},
        {"class_number": 9, "goods_services_segment": " computer software "},
    ]
    cases.append((payload, "Duplicate challenged class segments"))

    payload = _workspace_validation_payload()
    payload["client_instruction_state"] = "confirmed"
    cases.append((payload, "Confirmed client instruction requires a reference"))

    for invalid_payload, message in cases:
        _assert_model_error(
            IpOppositionWorkspaceUpsertRequest,
            invalid_payload,
            message,
        )


def test_applicant_action_schema_rejects_incomplete_or_misplaced_evidence() -> None:
    cases: list[tuple[dict[str, object], str]] = []

    payload = _applicant_action_validation_payload()
    payload["effective_at"] = "2026-08-23T08:00:00"
    cases.append((payload, "Applicant action time must include a timezone"))

    payload = _applicant_action_validation_payload()
    payload.pop("filing_reference")
    cases.append((payload, "A filed counterstatement requires filing facts"))

    payload = _applicant_action_validation_payload()
    payload["action_kind"] = "counterstatement_served"
    cases.append((payload, "Counterstatement service requires complete service facts"))

    payload = _applicant_action_validation_payload()
    payload["action_kind"] = "applicant_evidence_decision"
    cases.append((payload, "Applicant evidence requires an explicit"))

    payload = _applicant_action_validation_payload()
    payload.update(
        {
            "action_kind": "counterstatement_served",
            "evidence_election": "rely_on_pleaded_facts",
            "service": {
                "method": "email",
                "destination": "opponent@example.test",
                "served_on": "2026-08-23",
                "evidence_refs": ["service-receipt:041"],
            },
        }
    )
    cases.append((payload, "An evidence election is only valid for applicant evidence"))

    payload = _applicant_action_validation_payload()
    payload.update(
        {
            "action_kind": "applicant_evidence_decision",
            "evidence_election": "file_evidence",
            "evidence_refs": [],
            "document_refs": [],
        }
    )
    cases.append((payload, "Filed applicant evidence requires document and filing evidence"))

    for invalid_payload, message in cases:
        _assert_model_error(
            IpOppositionApplicantActionRequest,
            invalid_payload,
            message,
        )


def test_opposition_transition_schema_requires_governed_source_evidence() -> None:
    cases: list[tuple[dict[str, object], str]] = []

    payload = _transition_validation_payload()
    payload["effective_at"] = "2026-08-23T08:00:00"
    cases.append((payload, "Opposition transition time must include a timezone"))

    payload = _transition_validation_payload()
    payload.update({"source": "registry", "source_reference": None})
    cases.append((payload, "Registry transitions require a source reference"))

    payload = _transition_validation_payload()
    payload.update(
        {
            "transition_kind": "extended",
            "authority_reference": "registry-order:extension:041",
            "authorized_confirmation": "membership:approver:041",
            "evidence_refs": [],
        }
    )
    cases.append((payload, "Exceptional opposition stages require source evidence"))

    payload = _transition_validation_payload()
    payload.update(
        {
            "transition_kind": "extended",
            "authority_reference": "registry-order:extension:041",
            "authorized_confirmation": None,
        }
    )
    cases.append((payload, "Exceptional opposition stages require authorized confirmation"))

    for invalid_payload, message in cases:
        _assert_model_error(
            IpOppositionStageTransitionRequest,
            invalid_payload,
            message,
        )
