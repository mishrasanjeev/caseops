from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.db.models import IpDocketEvent, TrademarkApplication
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_post_registration import (
    IpPostRegistrationActionRequest,
    IpPostRegistrationProfile,
    IpPostRegistrationRuleMap,
    IpPostRegistrationWorkspaceUpsertRequest,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket


def _fixture(
    client: TestClient,
    *,
    proceeding_kind: str = "rectification",
    with_number: bool = True,
) -> tuple[dict, dict, dict]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    docket = _docket(client, headers, f"{proceeding_kind.upper()} FIXTURE")
    asset = _asset(client, headers, docket["id"], f"{proceeding_kind.upper()} MARK")
    application = _application(client, headers, docket["id"], asset["id"])
    body: dict[str, object] = {
        "application_id": application["id"],
        "proceeding_kind": proceeding_kind,
        "side": "claimant",
        "office": "Trade Marks Registry Delhi",
        "jurisdiction": "IN",
        "stage": "draft",
        "origin_kind": "registry_event",
        "source_pending_identifier_allocation": not with_number,
    }
    if with_number:
        body["proceeding_number"] = {
            "raw_value": f"{proceeding_kind.upper()} / 049 / 2026",
            "source": "registry_fixture",
            "effective_from": "2026-08-24",
            "is_primary": True,
        }
    response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json=body,
    )
    assert response.status_code == 201, response.text
    proceeding = response.json()
    proceeding["application"] = application
    return bootstrap, docket, proceeding


def _profile_body(
    *,
    bootstrap: dict,
    proceeding: dict,
    **overrides: object,
) -> dict[str, object]:
    body: dict[str, object] = {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": proceeding["version"],
        "expected_profile_event_id": None,
        "effective_at": "2026-08-24T08:00:00Z",
        "responsible_membership_id": bootstrap["membership"]["id"],
        "source": "manual",
        "source_reference": "registry:post-registration:049",
        "reason": "Counsel confirmed the post-registration record from the source file.",
        "evidence_refs": ["evidence:instructions:049"],
        "document_refs": ["document:petition:049"],
        "profile": {
            "proceeding_type": proceeding["proceeding_kind"],
            "legal_basis": "Lawyer-confirmed statutory rectification basis.",
            "target_right_reference": "registration:TM-049-2026",
            "applicant_name": "Claimant Brands Private Limited",
            "respondent_name": "Registered Proprietor Limited",
            "challenged_scope": [
                {
                    "class_number": 9,
                    "goods_services_segment": "Recorded computer software",
                }
            ],
            "grounds": ["Entry remains on the register without the asserted legal basis."],
            "forum": "Trade Marks Registry Delhi",
            "form_key": "TM-O",
            "fee_status": "paid",
            "fee_reference": "fee-receipt:049",
            "service_status": "served",
            "service_reference": "service-proof:049",
            "rule_map": {
                "template_key": (f"post-registration/{proceeding['proceeding_kind']}"),
                "template_version": "lawyer-reviewed-v1",
                "authority_reference": "Trade Marks Act and Rules mapping:049",
                "source_reference": "legal-source:049",
                "mutatis_mutandis": False,
            },
        },
    }
    body.update(overrides)
    return body


def _action_body(
    *,
    bootstrap: dict,
    proceeding: dict,
    action_kind: str,
    **overrides: object,
) -> dict[str, object]:
    body: dict[str, object] = {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": proceeding["version"],
        "action_kind": action_kind,
        "effective_at": "2026-08-24T09:00:00Z",
        "responsible_membership_id": bootstrap["membership"]["id"],
        "source": "manual",
        "source_reference": "registry-action:049",
        "reason": "Counsel reviewed and confirmed the sourced procedural action.",
        "evidence_refs": ["evidence:action:049"],
        "document_refs": ["document:action:049"],
    }
    body.update(overrides)
    return body


def _workspace_url(docket: dict, proceeding: dict) -> str:
    return (
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/post-registration-workspace"
    )


def _action_url(docket: dict, proceeding: dict) -> str:
    return (
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/post-registration-actions"
    )


def test_normal_post_registration_journey_is_typed_and_never_auto_disposes(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    assert proceeding["stage_template_version"] == "post-registration-rectification-v1"

    initial = client.get(_workspace_url(docket, proceeding), headers=headers)
    assert initial.status_code == 200, initial.text
    assert initial.json()["readiness_gaps"] == ["post_registration_profile_required"]
    assert initial.json()["identifiers"][0]["identifier_kind"] == "rectification"

    opposition_number = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "opposition",
            "raw_value": "OPP-INCORRECT-049",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "source": "registry_fixture",
            "effective_from": "2026-08-24",
            "is_primary": False,
            "proceeding_id": proceeding["id"],
        },
    )
    assert opposition_number.status_code == 422

    saved = client.put(
        _workspace_url(docket, proceeding),
        headers=headers,
        json=_profile_body(bootstrap=bootstrap, proceeding=proceeding),
    )
    assert saved.status_code == 200, saved.text
    workspace = saved.json()
    assert workspace["ready_for_stage_progression"] is True
    assert workspace["registration_disposition_is_automatic"] is False
    assert (
        workspace["profile"]["lawyer_confirmed_by_membership_id"] == bootstrap["membership"]["id"]
    )

    stage = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="stage_update",
            stage="counterstatement_due",
        ),
    )
    assert stage.status_code == 201, stage.text
    proceeding["version"] = stage.json()["proceeding"]["version"]

    candidate = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="disposition_candidate",
            candidate_disposition="rectify_registration",
            legal_effect="Rectify only the challenged class 9 specification.",
        ),
    )
    assert candidate.status_code == 201, candidate.text
    candidate_event = candidate.json()["action_events"][-1]
    assert candidate_event["payload_json"]["registration_disposition_applied"] is False

    wrong_disposition = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="disposition_candidate",
            candidate_disposition="cancel_registration",
            legal_effect="Cancel a registration from the wrong proceeding type.",
        ),
    )
    assert wrong_disposition.status_code == 422
    assert "does not match" in wrong_disposition.text

    reviewed = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="disposition_review",
            candidate_event_id=candidate_event["id"],
            review_decision="approved",
            authorized_confirmation="Reviewing counsel approved the candidate legal effect.",
        ),
    )
    assert reviewed.status_code == 201, reviewed.text
    assert (
        reviewed.json()["action_events"][-1]["payload_json"]["registration_disposition_applied"]
        is False
    )

    session = get_session_factory()()
    try:
        application = session.scalar(
            select(TrademarkApplication).where(
                TrademarkApplication.id == proceeding["application"]["id"]
            )
        )
        assert application is not None
        assert application.filing_phase == "draft"
        assert application.is_active is True
    finally:
        session.close()


def test_mutatis_mapping_is_explicit_and_never_reuses_opposition_template(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, proceeding_kind="cancellation")
    headers = auth_headers(str(bootstrap["access_token"]))
    body = _profile_body(bootstrap=bootstrap, proceeding=proceeding)
    profile = body["profile"]
    assert isinstance(profile, dict)
    rule_map = profile["rule_map"]
    assert isinstance(rule_map, dict)
    rule_map.update(
        {
            "mutatis_mutandis": True,
            "mapped_from_rule": "Opposition evidence provisions",
            "mapped_provisions": ["evidence sequence"],
        }
    )
    incomplete = client.put(_workspace_url(docket, proceeding), headers=headers, json=body)
    assert incomplete.status_code == 422

    rule_map.update(
        {
            "excluded_provisions": ["opposition notice and opposition number"],
            "lawyer_confirmation": "Counsel mapped only the applicable evidence mechanics.",
        }
    )
    mapped = client.put(_workspace_url(docket, proceeding), headers=headers, json=body)
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["profile"]["rule_map"]["template_key"] == (
        "post-registration/cancellation"
    )

    copied = _profile_body(bootstrap=bootstrap, proceeding=proceeding)
    copied["expected_profile_event_id"] = mapped.json()["profile_event"]["id"]
    copied_profile = copied["profile"]
    assert isinstance(copied_profile, dict)
    copied_rule_map = copied_profile["rule_map"]
    assert isinstance(copied_rule_map, dict)
    copied_rule_map["template_key"] = "opposition-applicant-v1"
    rejected = client.put(_workspace_url(docket, proceeding), headers=headers, json=copied)
    assert rejected.status_code == 422
    assert "cannot be reused" in rejected.text


def test_parallel_proceedings_and_stay_are_separate_and_fail_closed(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client, proceeding_kind="non_use_removal")
    headers = auth_headers(str(bootstrap["access_token"]))
    profile = client.put(
        _workspace_url(docket, proceeding),
        headers=headers,
        json=_profile_body(bootstrap=bootstrap, proceeding=proceeding),
    )
    assert profile.status_code == 200, profile.text

    parallel = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": proceeding["application_id"],
            "proceeding_kind": "court",
            "side": "claimant",
            "office": "Delhi High Court",
            "jurisdiction": "IN",
            "stage": "filed",
            "origin_kind": "manual_intake",
        },
    )
    assert parallel.status_code == 201, parallel.text
    linked = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="parallel_proceeding_link",
            parallel_proceeding_id=parallel.json()["id"],
        ),
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["proceeding"]["id"] != parallel.json()["id"]
    assert linked.json()["proceeding"]["proceeding_kind"] == "non_use_removal"
    assert (
        linked.json()["action_events"][-1]["payload_json"]["parallel_proceeding_id"]
        == parallel.json()["id"]
    )

    stay = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="interim_stay",
            authority_reference="Delhi High Court interim order dated 2026-08-24",
        ),
    )
    assert stay.status_code == 201, stay.text
    assert stay.json()["active_stay"] is True
    blocked = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="disposition_candidate",
            candidate_disposition="remove_for_non_use",
            legal_effect="Remove the challenged registration for proven non-use.",
        ),
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ip_post_registration_stay_blocks_disposition"

    lifted = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="stay_lifted",
            authority_reference="Delhi High Court order lifting stay dated 2026-08-24",
        ),
    )
    assert lifted.status_code == 201, lifted.text
    assert lifted.json()["active_stay"] is False


def test_settlement_or_withdrawal_requires_explicit_legal_effect(
    client: TestClient,
) -> None:
    bootstrap, docket, proceeding = _fixture(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    saved = client.put(
        _workspace_url(docket, proceeding),
        headers=headers,
        json=_profile_body(bootstrap=bootstrap, proceeding=proceeding),
    )
    assert saved.status_code == 200, saved.text

    incomplete = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="closure",
            stage="settled",
        ),
    )
    assert incomplete.status_code == 422

    closed = client.post(
        _action_url(docket, proceeding),
        headers=headers,
        json=_action_body(
            bootstrap=bootstrap,
            proceeding=proceeding,
            action_kind="closure",
            stage="settled",
            legal_effect="Proceeding ends without automatic alteration of the register.",
            legal_effective_date="2026-08-24",
            authorized_confirmation="Counsel confirmed the executed settlement effect.",
        ),
    )
    assert closed.status_code == 201, closed.text
    assert closed.json()["proceeding"]["stage"] == "settled"
    event = closed.json()["action_events"][-1]
    assert event["payload_json"]["legal_effect"] == (
        "Proceeding ends without automatic alteration of the register."
    )

    session = get_session_factory()()
    try:
        events = list(
            session.scalars(
                select(IpDocketEvent).where(
                    IpDocketEvent.proceeding_id == proceeding["id"],
                    IpDocketEvent.event_kind == "post_registration_action",
                )
            )
        )
        assert len(events) == 1
    finally:
        session.close()


def test_post_registration_schema_fails_closed_for_incomplete_governed_fields() -> None:
    rule_map = {
        "template_key": "post-registration/rectification",
        "template_version": "lawyer-reviewed-v1",
        "authority_reference": "Trade Marks Act and Rules mapping:049",
        "source_reference": "legal-source:049",
        "mutatis_mutandis": False,
        "mapped_from_rule": "Opposition evidence provisions",
    }
    with pytest.raises(ValidationError, match="explicitly enabled"):
        IpPostRegistrationRuleMap.model_validate(rule_map)

    body = _profile_body(
        bootstrap={"membership": {"id": "membership-schema"}},
        proceeding={"version": 1, "proceeding_kind": "rectification"},
    )
    valid_profile = body["profile"]
    assert isinstance(valid_profile, dict)
    invalid_profiles = [
        {**deepcopy(valid_profile), "fee_reference": None},
        {**deepcopy(valid_profile), "service_reference": None},
        {**deepcopy(valid_profile), "grounds": [""]},
    ]
    for invalid_profile in invalid_profiles:
        with pytest.raises(ValidationError):
            IpPostRegistrationProfile.model_validate(invalid_profile)

    naive_workspace = deepcopy(body)
    naive_workspace["effective_at"] = "2026-08-24T08:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        IpPostRegistrationWorkspaceUpsertRequest.model_validate(naive_workspace)

    base_action = _action_body(
        bootstrap={"membership": {"id": "membership-schema"}},
        proceeding={"version": 1},
        action_kind="stage_update",
        stage="petition_filed",
    )
    invalid_actions = [
        {**deepcopy(base_action), "effective_at": "2026-08-24T09:00:00"},
        {
            **deepcopy(base_action),
            "action_kind": "order_recorded",
            "authority_reference": None,
        },
        {**deepcopy(base_action), "stage": None},
        {
            **deepcopy(base_action),
            "action_kind": "parallel_proceeding_link",
            "stage": None,
        },
        {
            **deepcopy(base_action),
            "action_kind": "disposition_candidate",
            "stage": None,
        },
        {
            **deepcopy(base_action),
            "action_kind": "disposition_review",
            "stage": None,
        },
    ]
    for invalid_action in invalid_actions:
        with pytest.raises(ValidationError):
            IpPostRegistrationActionRequest.model_validate(invalid_action)
