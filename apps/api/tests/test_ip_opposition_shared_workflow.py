from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    IpDeadline,
    TrademarkApplication,
    TrademarkApplicationScope,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_oppositions import IpOppositionSharedActionRequest
from tests.test_auth_company import auth_headers
from tests.test_ip_opposition_applicant_workflow import _fixture, _stage
from tests.test_ip_opposition_foundation import _complete_workspace
from tests.test_ip_opposition_opponent_workflow import (
    _fixture as _opponent_fixture,
)
from tests.test_ip_opposition_opponent_workflow import _profile, _propose_and_confirm
from tests.test_ip_record_workflow import _application

SHARED_WORKFLOW_PATH = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opposition-shared-workflow"  # noqa: E501
)
SHARED_ACTIONS_PATH = (
    "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opposition-shared-actions"  # noqa: E501
)


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def test_shared_opposition_routes_are_published_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "get" in paths[SHARED_WORKFLOW_PATH]
    assert "post" in paths[SHARED_ACTIONS_PATH]


def _route(docket: dict, proceeding: dict, suffix: str) -> str:
    return f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/{suffix}"


def _shared_body(
    bootstrap: dict,
    proceeding: dict,
    *,
    action_kind: str,
    **details: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "expected_lifecycle_version": 0,
        "expected_proceeding_version": proceeding["version"],
        "action_kind": action_kind,
        "source": "manual",
        "source_reference": f"registry:{action_kind}:043",
        "effective_at": "2026-08-25T12:30:00+05:30",
        "responsible_membership_id": bootstrap["membership"]["id"],
        "reason": f"Counsel verified the {action_kind.replace('_', ' ')} record.",
        "authorized_confirmation": "Approved by responsible IP counsel.",
        "evidence_refs": [f"evidence:{action_kind}:043"],
        "document_refs": [f"document:{action_kind}:043"],
        "acknowledged_exception_codes": ["backdated_recalculation_review_required"],
    }
    payload.update(details)
    return payload


def _verification() -> dict[str, object]:
    return {
        "signatory": "Authorized IP Counsel",
        "authority": "Filed under signed client authority",
        "place": "New Delhi",
        "verified_on": "2026-08-23",
        "verified_paragraph_ranges": ["1-12", "verification"],
        "knowledge_basis": "Client records and registry documents",
        "signed_document_ref": "document:signed-affidavit:043",
    }


def _service() -> dict[str, object]:
    return {
        "method": "email_and_registry_portal",
        "destination": "Opposing counsel and registry account",
        "served_on": "2026-08-23",
        "starts_response_period": True,
        "evidence_refs": ["service-receipt:043", "document:service-set:043"],
    }


def _evidence_package(kind: str, *, leave_reference: str | None = None) -> dict:
    return {
        "package_kind": kind,
        "package_version": 1,
        "affidavit_deponent": "Evidence Deponent",
        "affidavit_document_ref": "document:affidavit:043",
        "exhibit_document_refs": ["document:exhibit-a:043"],
        "index_document_ref": "document:evidence-index:043",
        "verification": _verification(),
        "relied_on_document_refs": ["document:relied-on:043"],
        "filing_reference": "registry-filing:evidence:043",
        "filed_on": "2026-08-23",
        "service": _service(),
        "leave_or_order_reference": leave_reference,
    }


def _post_action(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
    action_kind: str,
    expected_status: int = 201,
    **details: object,
) -> dict:
    response = client.post(
        _route(docket, proceeding, "opposition-shared-actions"),
        headers=auth_headers(str(bootstrap["access_token"])),
        json=_shared_body(
            bootstrap,
            proceeding,
            action_kind=action_kind,
            **details,
        ),
    )
    assert response.status_code == expected_status, response.text
    return response.json()


def _skip_to(
    client: TestClient,
    *,
    bootstrap: dict,
    docket: dict,
    proceeding: dict,
    to_stage: str,
) -> dict:
    return _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage=to_stage,
        transition_kind="skipped",
        authority_reference="registry-direction:043",
        authorized_confirmation="Approved by responsible IP counsel.",
        effective_at="2026-08-26T12:30:00+05:30",
    )["proceeding"]


def _hearing(client: TestClient, *, bootstrap: dict, docket: dict) -> dict:
    response = client.post(
        "/api/ip/hearings",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "docket_id": docket["id"],
            "hearing_on": "2026-10-20",
            "forum_name": "Trade Marks Registry Delhi",
            "purpose": "Opposition final hearing",
            "status": "scheduled",
            "time_status": "session",
            "session_label": "Morning board",
            "timezone": "Asia/Kolkata",
            "hearing_mode": "hybrid",
            "attendee_membership_ids": [bootstrap["membership"]["id"]],
            "responsible_membership_id": bootstrap["membership"]["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _hearing_preparation(bootstrap: dict, hearing: dict, *, notes: str | None = None) -> dict:
    return {
        "shared_hearing_id": hearing["id"],
        "checklist_items": ["Paper book checked", "Authorities paginated"],
        "issues": ["Likelihood of confusion", "Prior use"],
        "evidence_document_refs": ["document:evidence-bundle:043"],
        "authority_refs": ["case:authority:043"],
        "written_submission_document_refs": ["document:submissions:043"],
        "attendance_membership_ids": [bootstrap["membership"]["id"]],
        "cause_list_source": "registry-cause-list:2026-10-20",
        "post_hearing_notes": notes,
    }


def test_shared_action_schema_rejects_ambiguous_or_unverifiable_records() -> None:
    bootstrap = {"membership": {"id": "membership:043"}}
    proceeding = {"version": 2}
    valid = _shared_body(
        bootstrap,
        proceeding,
        action_kind="evidence_package_recorded",
        evidence_package=_evidence_package("rule_46"),
    )

    missing_detail = deepcopy(valid)
    missing_detail.pop("evidence_package")
    with pytest.raises(ValidationError, match="requires evidence_package"):
        IpOppositionSharedActionRequest.model_validate(missing_detail)

    unrelated = deepcopy(valid)
    unrelated["order_details"] = {
        "operative_result": "Opposition allowed for all challenged goods.",
        "affected_application_id": "application:043",
        "affected_proceeding_id": "proceeding:043",
        "appeal_review": "pending",
        "order_document_ref": "document:order:043",
    }
    with pytest.raises(ValidationError, match="unrelated detail fields"):
        IpOppositionSharedActionRequest.model_validate(unrelated)

    no_timezone = deepcopy(valid)
    no_timezone["effective_at"] = "2026-08-23T12:30:00"
    with pytest.raises(ValidationError, match="must include a timezone"):
        IpOppositionSharedActionRequest.model_validate(no_timezone)

    direct_registry = deepcopy(valid)
    direct_registry["source"] = "registry"
    with pytest.raises(ValidationError):
        IpOppositionSharedActionRequest.model_validate(direct_registry)

    further = deepcopy(valid)
    further["evidence_package"] = _evidence_package("further_evidence")
    with pytest.raises(ValidationError, match="leave or order reference"):
        IpOppositionSharedActionRequest.model_validate(further)

    uncertain_scope = _shared_body(
        bootstrap,
        proceeding,
        action_kind="scope_review_recorded",
        scope_review={
            "revision": 1,
            "source_scope_certainty": "missing",
            "decisions": [
                {
                    "application_scope_id": "scope:048",
                    "challenged_segment": "Software",
                    "status": "challenged",
                }
            ],
        },
    )
    with pytest.raises(ValidationError, match="requires source confirmation"):
        IpOppositionSharedActionRequest.model_validate(uncertain_scope)

    nonappearance = _shared_body(
        bootstrap,
        proceeding,
        action_kind="attendance_recorded",
        attendance={
            "shared_hearing_id": "hearing:048",
            "appearance_status": "nonappearance",
            "attendance_source_ref": "cause-list:048",
            "applicable_rule_version": "tm-rules-2017@2026-08-24",
        },
    )
    with pytest.raises(ValidationError, match="Nonappearance requires"):
        IpOppositionSharedActionRequest.model_validate(nonappearance)


def test_specialized_opposition_paths_preserve_scope_and_require_explicit_review(
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
    factory = get_session_factory()
    with factory() as session:
        application = session.get(TrademarkApplication, proceeding["application_id"])
        assert application is not None
        canonical_asset_id = application.asset_id
        session.add(
            TrademarkApplicationScope(
                company_id=bootstrap["company"]["id"],
                application_id=proceeding["application_id"],
                class_number=42,
                specification="Software design and legal technology services",
                effective_from=date(2026, 8, 23),
                source="registry:class-42:048",
            )
        )
        session.commit()

    related_application = _application(
        client,
        headers,
        docket["id"],
        canonical_asset_id,
    )
    workflow_response = client.get(
        _route(docket, proceeding, "opposition-shared-workflow"),
        headers=headers,
    )
    assert workflow_response.status_code == 200, workflow_response.text
    workflow = workflow_response.json()
    scopes = workflow["application_scopes"]
    assert {row["class_number"] for row in scopes} == {9, 42}
    scope_by_class = {row["class_number"]: row for row in scopes}

    scope_workflow = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="scope_review_recorded",
        scope_review={
            "revision": 1,
            "source_scope_certainty": "partial",
            "source_confirmation_reference": "registry-source-pdf:048",
            "related_application_id": related_application["id"],
            "amendment_or_division_reference": "registry-division:048",
            "decisions": [
                {
                    "application_scope_id": scope_by_class[9]["id"],
                    "challenged_segment": "Downloadable software",
                    "status": "withdrawn",
                },
                {
                    "application_scope_id": scope_by_class[42]["id"],
                    "challenged_segment": "Legal technology services",
                    "status": "continuing",
                },
            ],
        },
    )
    scope_event = scope_workflow["shared_actions"][-1]
    assert scope_event["payload_json"]["scope_review"]["preserve_unlisted_scopes"] is True
    assert {row["status"] for row in scope_event["payload_json"]["scope_review"]["decisions"]} == {
        "withdrawn",
        "continuing",
    }

    invalid_scope = client.post(
        _route(docket, proceeding, "opposition-shared-actions"),
        headers=headers,
        json=_shared_body(
            bootstrap,
            proceeding,
            action_kind="scope_review_recorded",
            scope_review={
                "revision": 2,
                "source_scope_certainty": "certain",
                "decisions": [
                    {
                        "application_scope_id": "not-a-current-scope",
                        "challenged_segment": "All goods",
                        "status": "challenged",
                    }
                ],
            },
        ),
    )
    assert invalid_scope.status_code == 409, invalid_scope.text
    assert "ip_opposition_scope_not_current" in invalid_scope.text

    missing_translation = _skip_to(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        to_stage="applicant_evidence_filed",
    )
    foreign_package = _evidence_package("rule_46")
    foreign_package["foreign_language_document_refs"] = ["document:marathi-exhibit:048"]
    blocked_package = client.post(
        _route(docket, missing_translation, "opposition-shared-actions"),
        headers=headers,
        json=_shared_body(
            bootstrap,
            missing_translation,
            action_kind="evidence_package_recorded",
            evidence_package=foreign_package,
        ),
    )
    assert blocked_package.status_code == 409, blocked_package.text
    assert "ip_opposition_attested_translation_required" in blocked_package.text

    _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=missing_translation,
        action_kind="translation_recorded",
        translation={
            "source_document_ref": "document:marathi-exhibit:048",
            "source_document_sha256": "a" * 64,
            "source_language": "Marathi",
            "translated_document_ref": "document:english-translation:048",
            "translated_document_sha256": "b" * 64,
            "translated_language": "English",
            "translator_name": "Asha Kulkarni",
            "translator_credential": "Court-approved translator credential 048",
            "attested_on": "2026-08-24",
            "attestation_reference": "notary-attestation:048",
            "service": _service(),
        },
    )
    package_workflow = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=missing_translation,
        action_kind="evidence_package_recorded",
        evidence_package=foreign_package,
    )
    assert package_workflow["shared_actions"][-1]["payload_json"]["evidence_package"][
        "foreign_language_document_refs"
    ] == ["document:marathi-exhibit:048"]

    _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=missing_translation,
        action_kind="security_for_costs_recorded",
        security_for_costs={
            "direction_reference": "registry-direction:security:048",
            "directed_on": "2026-08-24",
            "amount_minor": 500000,
            "enhancement_amount_minor": 100000,
            "due_on": "2026-09-10",
            "payment_status": "paid",
            "paid_on": "2026-09-01",
            "payment_reference": "bank-proof:048",
            "consequence_candidate": "Proceeding may be stayed after counsel confirmation.",
            "applicable_rule_version": "tm-rules-2017@2026-08-24",
        },
    )
    _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=missing_translation,
        action_kind="madrid_designation_link_recorded",
        madrid_designation={
            "application_id": proceeding["application_id"],
            "international_registration_number": "IR-1848001",
            "wipo_reference": "WIPO-MADRID-048",
            "india_designation_identifier": "DIND-048-2026",
            "designation_status": "opposition pending in India",
            "lifecycle_source_reference": "wipo-status-extract:048",
        },
    )

    proceeding = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=missing_translation["id"],
        version=missing_translation["version"],
        to_stage="hearing_pending",
        effective_at="2026-09-15T12:30:00+05:30",
        acknowledged_exception_codes=["backdated_recalculation_review_required"],
    )["proceeding"]
    hearing = _hearing(client, bootstrap=bootstrap, docket=docket)
    proceeding = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="hearing_scheduled",
        effective_at="2026-09-16T12:30:00+05:30",
        acknowledged_exception_codes=["backdated_recalculation_review_required"],
    )["proceeding"]

    _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="hearing_notice_recorded",
        hearing_notice={
            "shared_hearing_id": hearing["id"],
            "notice_received_on": "2026-09-20",
            "notice_document_ref": "registry-hearing-notice:048",
            "minimum_notice_days": 30,
            "notice_status": "sufficient",
            "applicable_rule_version": "tm-rules-2017@2026-08-24",
            "confirmation_reference": "counsel-review:notice:048",
        },
    )
    _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="adjournment_recorded",
        adjournment={
            "shared_hearing_id": hearing["id"],
            "requested_on": "2026-09-25",
            "request_form_ref": "tm-m-adjournment:048",
            "request_reason": "Lead witness has a documented medical conflict.",
            "fee_status": "paid",
            "fee_amount_minor": 90000,
            "fee_evidence_ref": "registry-fee-receipt:048",
            "prior_adjournment_count": 0,
            "allowed_count_candidate": 2,
            "applicable_rule_version": "tm-rules-2017@2026-08-24",
            "policy_confirmation_reference": "counsel-policy-review:048",
            "outcome": "granted",
        },
    )
    _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="written_arguments_recorded",
        written_arguments={
            "shared_hearing_id": hearing["id"],
            "filed_on": "2026-10-18",
            "filing_reference": "registry-written-arguments:048",
            "document_refs": ["document:written-arguments:048"],
            "service": _service(),
        },
    )
    completed = client.patch(
        f"/api/ip/hearings/{hearing['id']}",
        headers=headers,
        json={
            "docket_id": docket["id"],
            "status": "completed",
            "outcome_note": "Opponent did not appear; consequence requires review.",
        },
    )
    assert completed.status_code == 200, completed.text
    attendance_workflow = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="attendance_recorded",
        attendance={
            "shared_hearing_id": hearing["id"],
            "appearance_status": "nonappearance",
            "attendance_source_ref": "registry-cause-list:048",
            "nonappearance_consequence_candidate": "Proceed ex parte if the Registry so directs.",
            "applicable_rule_version": "tm-rules-2017@2026-08-24",
            "consequence_confirmation_reference": "counsel-nonappearance-review:048",
        },
    )
    assert (
        attendance_workflow["shared_actions"][-1]["payload_json"]["attendance"]["appearance_status"]
        == "nonappearance"
    )

    outcome = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="withdrawn",
        transition_kind="skipped",
        authority_reference="registry-withdrawal-order:048",
        authorized_confirmation="Withdrawal reviewed by responsible IP counsel.",
        effective_at="2026-10-21T12:30:00+05:30",
    )
    disposition = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=outcome["proceeding"],
        action_kind="disposition_review_recorded",
        disposition_review={
            "trigger_event_id": outcome["event"]["id"],
            "outcome_kind": "withdrawal",
            "affected_application_scope_ids": [scope_by_class[9]["id"]],
            "recommended_application_disposition": (
                "Review class 9 only; class 42 remains unaffected by this withdrawal."
            ),
            "review_status": "confirmed",
            "review_reference": "counsel-disposition-review:048",
        },
    )
    review_payload = disposition["shared_actions"][-1]["payload_json"]["disposition_review"]
    assert review_payload["no_automatic_application_update"] is True
    assert review_payload["affected_application_scope_ids"] == [scope_by_class[9]["id"]]


def test_deadline_extension_is_atomic_and_preserves_canonical_history(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _opponent_fixture(client)
    workspace = _profile(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    deadline = _propose_and_confirm(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        workflow_stage="notice_filing_due",
        trigger_event_id=workspace["profile_event"]["id"],
    )
    responsibilities = [
        {
            "membership_id": row["membership_id"],
            "role": row["role"],
            "accepted": True,
            "escalation_policy": row["escalation_policy"],
        }
        for row in deadline["responsibilities"]
    ]
    extension = {
        "deadline_id": deadline["id"],
        "expected_deadline_version": deadline["version"],
        "new_result_on": "2026-10-30",
        "responsibilities": responsibilities,
        "reminder_offsets_days": [7, 1, 0],
    }

    stale = _shared_body(
        bootstrap,
        proceeding,
        action_kind="deadline_extended",
        deadline_extension=extension,
    )
    stale["expected_lifecycle_version"] = 99
    failed = client.post(
        _route(docket, proceeding, "opposition-shared-actions"),
        headers=auth_headers(str(bootstrap["access_token"])),
        json=stale,
    )
    assert failed.status_code == 409, failed.text

    with get_session_factory()() as session:
        rows = list(session.scalars(select(IpDeadline).where(IpDeadline.docket_id == docket["id"])))
        assert [(row.id, row.state) for row in rows] == [(deadline["id"], "confirmed")]

    result = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="deadline_extended",
        deadline_extension=extension,
    )
    assert len(result["active_deadlines"]) == 1
    replacement = result["active_deadlines"][0]
    assert replacement["id"] != deadline["id"]
    assert replacement["supersedes_deadline_id"] == deadline["id"]
    assert replacement["result_on"] == "2026-10-30"
    event = result["shared_actions"][0]
    assert event["resulting_deadline_refs_json"] == [replacement["id"]]

    with get_session_factory()() as session:
        original = session.get(IpDeadline, deadline["id"])
        assert original is not None
        assert original.state == "superseded"


def test_evidence_packages_enforce_side_stage_leave_and_versioning(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    proceeding = _skip_to(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        to_stage="applicant_evidence_due",
    )

    wrong_side = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="evidence_package_recorded",
        expected_status=409,
        evidence_package=_evidence_package("rule_45"),
    )
    assert "represented side" in wrong_side["detail"]

    result = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="evidence_package_recorded",
        evidence_package=_evidence_package("rule_46"),
    )
    assert result["next_required_action"] == "complete_role_workflow"

    duplicate = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="evidence_package_recorded",
        expected_status=409,
        evidence_package=_evidence_package("rule_46"),
    )
    assert "already recorded" in duplicate["detail"]

    leave_reference = "registry-order:further-evidence:043"
    blocked = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="evidence_package_recorded",
        expected_status=409,
        evidence_package=_evidence_package(
            "further_evidence",
            leave_reference=leave_reference,
        ),
    )
    assert "matching leave or order" in blocked["detail"]

    _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="further_evidence_leave_recorded",
        further_evidence_leave={
            "leave_or_order_reference": leave_reference,
            "permitted_scope": "Rebuttal records limited to the registry direction.",
            "granted_on": "2026-08-23",
        },
    )
    accepted = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="evidence_package_recorded",
        evidence_package=_evidence_package(
            "further_evidence",
            leave_reference=leave_reference,
        ),
    )
    assert len(accepted["shared_actions"]) == 3


def test_hearing_order_and_appeal_use_shared_records_and_gate_stages(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _fixture(client)
    _complete_workspace(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
    )
    proceeding = _skip_to(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        to_stage="hearing_pending",
    )
    hearing = _hearing(client, bootstrap=bootstrap, docket=docket)
    proceeding = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="hearing_scheduled",
        effective_at="2026-10-21T12:30:00+05:30",
        acknowledged_exception_codes=["backdated_recalculation_review_required"],
    )["proceeding"]

    blocked = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/stage",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "expected_lifecycle_version": 0,
            "expected_proceeding_version": proceeding["version"],
            "to_stage": "reserved_for_order",
            "transition_kind": "normal",
            "source": "manual",
            "source_reference": "registry:hearing:043",
            "effective_at": "2026-10-22T12:30:00+05:30",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Hearing concluded and order was reserved.",
            "evidence_refs": ["registry:cause-list:043"],
            "acknowledged_exception_codes": ["backdated_recalculation_review_required"],
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert "hearing preparation" in blocked.text.lower()

    prepared = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="hearing_preparation_recorded",
        effective_at="2026-10-22T13:30:00+05:30",
        hearing_preparation=_hearing_preparation(bootstrap, hearing),
    )
    assert prepared["next_required_action"] == "await_hearing"
    completed = client.patch(
        f"/api/ip/hearings/{hearing['id']}",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "docket_id": docket["id"],
            "status": "completed",
            "outcome_note": "Arguments concluded; order reserved.",
        },
    )
    assert completed.status_code == 200, completed.text
    after_hearing = client.get(
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}/opposition-shared-workflow",
        headers=auth_headers(str(bootstrap["access_token"])),
    )
    assert after_hearing.status_code == 200, after_hearing.text
    assert after_hearing.json()["next_required_action"] == "record_post_hearing_note"
    noted = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="post_hearing_note_recorded",
        effective_at="2026-10-23T12:30:00+05:30",
        hearing_preparation=_hearing_preparation(
            bootstrap,
            hearing,
            notes="Registry heard both parties and reserved the matter for order.",
        ),
    )
    assert noted["next_required_action"] == "advance_to_order"
    proceeding = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="reserved_for_order",
        effective_at="2026-10-24T12:30:00+05:30",
        acknowledged_exception_codes=["backdated_recalculation_review_required"],
    )["proceeding"]

    order_result = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="order_recorded",
        effective_at="2026-10-25T12:30:00+05:30",
        order_details={
            "operative_result": "Opposition allowed for the challenged goods and services.",
            "affected_application_id": proceeding["application_id"],
            "affected_proceeding_id": proceeding["id"],
            "costs_and_directions": ["Applicant to bear registry costs."],
            "compliance_directions": [
                {
                    "direction": "File the compliance report with the Registry.",
                    "due_on": "2026-11-20",
                }
            ],
            "appeal_review": "required",
            "order_document_ref": "document:opposition-order:043",
        },
    )
    order_event = order_result["shared_actions"][-1]
    proceeding = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="decided",
        effective_at="2026-10-26T12:30:00+05:30",
        acknowledged_exception_codes=["backdated_recalculation_review_required"],
    )["proceeding"]

    appeal = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "application_id": proceeding["application_id"],
            "proceeding_kind": "appeal",
            "side": "respondent",
            "office": "High Court of Delhi",
            "jurisdiction": "IN",
            "stage": "filed",
            "origin_kind": "registry_event",
        },
    )
    assert appeal.status_code == 201, appeal.text
    appeal = appeal.json()
    identifier = client.post(
        f"/api/ip/dockets/{docket['id']}/identifiers",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={
            "identifier_kind": "appeal",
            "raw_value": "C.A.(COMM.IPD-TM) 43/2026",
            "office": "High Court of Delhi",
            "jurisdiction": "IN",
            "source": "court-filing:043",
            "effective_from": "2026-11-01",
            "is_primary": True,
            "proceeding_id": appeal["id"],
        },
    )
    assert identifier.status_code == 201, identifier.text
    proceeding = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="appeal_pending",
        effective_at="2026-10-27T12:30:00+05:30",
        acknowledged_exception_codes=["backdated_recalculation_review_required"],
    )["proceeding"]
    linked = _post_action(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding=proceeding,
        action_kind="appeal_linked",
        effective_at="2026-10-28T12:30:00+05:30",
        appeal_link={
            "target_kind": "appeal_proceeding",
            "target_id": appeal["id"],
            "appeal_identifier": identifier.json()["identifier"]["raw_value"],
            "order_event_id": order_event["id"],
        },
    )
    assert linked["shared_actions"][-1]["payload_json"]["appeal_link"]["target_id"] == appeal["id"]
    proceeding = _stage(
        client,
        bootstrap=bootstrap,
        docket=docket,
        proceeding_id=proceeding["id"],
        version=proceeding["version"],
        to_stage="appealed",
        effective_at="2026-10-29T12:30:00+05:30",
        acknowledged_exception_codes=["backdated_recalculation_review_required"],
    )["proceeding"]
    assert proceeding["stage"] == "appealed"

    outsider_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "IPLF 043 Outsider LLP",
            "company_slug": "iplf-043-outsider",
            "company_type": "law_firm",
            "owner_full_name": "Outside Counsel",
            "owner_email": "iplf-043-outsider@example.com",
            "owner_password": "OutsiderPass123!",
        },
    )
    assert outsider_response.status_code == 200, outsider_response.text
    outsider = outsider_response.json()
    hidden = client.get(
        _route(docket, proceeding, "opposition-shared-workflow"),
        headers=auth_headers(str(outsider["access_token"])),
    )
    assert hidden.status_code == 404
