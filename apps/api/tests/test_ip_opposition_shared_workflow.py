from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import IpDeadline
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_oppositions import IpOppositionSharedActionRequest
from tests.test_auth_company import auth_headers
from tests.test_ip_opposition_applicant_workflow import _fixture, _stage
from tests.test_ip_opposition_foundation import _complete_workspace
from tests.test_ip_opposition_opponent_workflow import (
    _fixture as _opponent_fixture,
)
from tests.test_ip_opposition_opponent_workflow import _profile, _propose_and_confirm

SHARED_WORKFLOW_PATH = "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opposition-shared-workflow"  # noqa: E501
SHARED_ACTIONS_PATH = "/api/ip/dockets/{docket_id}/proceedings/{proceeding_id}/opposition-shared-actions"  # noqa: E501


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def test_shared_opposition_routes_are_published_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "get" in paths[SHARED_WORKFLOW_PATH]
    assert "post" in paths[SHARED_ACTIONS_PATH]


def _route(docket: dict, proceeding: dict, suffix: str) -> str:
    return (
        f"/api/ip/dockets/{docket['id']}/proceedings/"
        f"{proceeding['id']}/{suffix}"
    )


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
        "acknowledged_exception_codes": [
            "backdated_recalculation_review_required"
        ],
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
        effective_at="2026-08-24T12:30:00+05:30",
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
        rows = list(
            session.scalars(
                select(IpDeadline).where(IpDeadline.docket_id == docket["id"])
            )
        )
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
            "acknowledged_exception_codes": [
                "backdated_recalculation_review_required"
            ],
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
        f"/api/ip/dockets/{docket['id']}/proceedings/{proceeding['id']}"
        "/opposition-shared-workflow",
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
    assert linked["shared_actions"][-1]["payload_json"]["appeal_link"]["target_id"] == appeal[
        "id"
    ]
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
