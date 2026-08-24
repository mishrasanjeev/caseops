from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError

from caseops_api.db.models import (
    IpDocketEvent,
    IpRegistryDiff,
    IpRegistryLink,
    IpRegistrySnapshot,
    IpRegistrySyncAttempt,
    IpTrackedCaseLink,
    TrackedCase,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_registry import (
    IpRegistryDiffResolveRequest,
    IpRegistryLinkCreateRequest,
    IpRegistryManualSnapshotRequest,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _application, _asset, _docket, _particulars


def _valid_link_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "application_id": "application-1",
        "provider_key": "ipindia-registry",
        "office": "IP India",
        "jurisdiction": "IN",
        "identifier_kind": "application",
        "raw_identifier": "TM-1234567",
        "source_url": "https://ipindia.gov.in/registry/TM-1234567",
        "match_confidence": "0.96",
        "capability_version": "manual-evidence-v1",
    }
    payload.update(overrides)
    return payload


def _valid_snapshot_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "expected_link_version": 1,
        "idempotency_key": "snapshot-validation-1",
        "source_url": "https://ipindia.gov.in/registry/TM-1234567",
        "source_retrieved_at": datetime(2026, 8, 24, 8, 30, tzinfo=UTC),
        "parser_version": "manual-normalizer-v1",
        "raw_snapshot": {"status": "registered"},
        "normalized_snapshot": {"status": "registered"},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            _valid_link_request(application_id=None),
            "Choose exactly one application or proceeding target",
        ),
        (
            _valid_link_request(source_url="ftp://ipindia.gov.in/TM-1234567"),
            "Registry source URL must use HTTP or HTTPS",
        ),
    ],
)
def test_registry_link_request_rejects_ambiguous_target_or_unsafe_url(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        IpRegistryLinkCreateRequest.model_validate(payload)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"source_url": "file:///tmp/registry.json"},
            "Registry source URL must use HTTP or HTTPS",
        ),
        (
            {"source_retrieved_at": datetime(2026, 8, 24, 8, 30)},
            "Source retrieval time must include a timezone",
        ),
        (
            {"raw_snapshot": {}},
            "Raw and normalized snapshots must both contain evidence",
        ),
        (
            {"supersedes_snapshot_id": "snapshot-1"},
            "A corrected snapshot requires both predecessor and reason",
        ),
    ],
)
def test_manual_snapshot_request_rejects_unverifiable_evidence(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        IpRegistryManualSnapshotRequest.model_validate(_valid_snapshot_request(**overrides))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"expected_version": 1, "decision": "map", "reason": "Map registry field."},
            "Mapping requires a canonical field path",
        ),
        (
            {"expected_version": 1, "decision": "accept", "reason": "Accept source fact."},
            "Acceptance requires effective time and responsible member",
        ),
        (
            {
                "expected_version": 1,
                "decision": "accept",
                "reason": "Accept source fact.",
                "effective_at": datetime(2026, 8, 24, 8, 30),
                "responsible_membership_id": "membership-1",
            },
            "Accepted effective time must include a timezone",
        ),
    ],
)
def test_registry_diff_decision_requires_complete_review_evidence(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        IpRegistryDiffResolveRequest.model_validate(payload)


def _registry_link(
    client: TestClient,
    headers: dict[str, str],
    *,
    docket: dict,
    application: dict,
) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket['id']}/registry-links",
        headers=headers,
        json={
            "application_id": application["id"],
            "provider_key": "ipindia-registry",
            "office": "IP India",
            "jurisdiction": "IN",
            "identifier_kind": "application",
            "raw_identifier": "TM / 1234567 / 2026",
            "source_url": "https://ipindia.gov.in/registry/TM-1234567-2026",
            "match_confidence": "0.9600",
            "match_evidence": {
                "identifier": "TM-1234567-2026",
                "office": "IP India",
            },
            "terms_version": None,
            "capability_version": "manual-evidence-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _confirmed_application_link(
    client: TestClient,
) -> tuple[dict, dict[str, str], dict, dict, dict]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    docket = _docket(client, headers, "REGISTRY RECONCILIATION")
    asset = _asset(client, headers, docket["id"], "REGISTRY RECONCILIATION")
    application = _application(client, headers, docket["id"], asset["id"])
    link = _registry_link(
        client,
        headers,
        docket=docket,
        application=application,
    )
    confirm = client.post(
        f"/api/ip/registry-links/{link['id']}/match-decision",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "confirm",
            "reason": "Application number, office and jurisdiction match the source.",
        },
    )
    assert confirm.status_code == 200, confirm.text
    return bootstrap, headers, docket, application, confirm.json()


def _snapshot_payload(
    *,
    link_version: int,
    idempotency_key: str,
    normalized_snapshot: dict,
    supersedes_snapshot_id: str | None = None,
    correction_reason: str | None = None,
) -> dict:
    return {
        "expected_link_version": link_version,
        "idempotency_key": idempotency_key,
        "source_url": "https://ipindia.gov.in/registry/TM-1234567-2026",
        "source_retrieved_at": "2026-08-24T08:30:00Z",
        "parser_version": "manual-normalizer-v1",
        "schema_version": 1,
        "attribution": {
            "publisher": "IP India",
            "capture_method": "manual",
        },
        "raw_snapshot": {"register_record": normalized_snapshot},
        "normalized_snapshot": normalized_snapshot,
        "supersedes_snapshot_id": supersedes_snapshot_id,
        "correction_reason": correction_reason,
    }


def test_registry_snapshot_reconciliation_and_no_change_history(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap, headers, docket, _, link = _confirmed_application_link(client)
    normalized = {
        "office": "IP India",
        "jurisdiction": "IN",
        "status": "registered",
        "mark_name": "REGISTRY RECONCILIATION",
        "renewal_date": "2036-08-24",
        "parties": [],
    }
    payload = _snapshot_payload(
        link_version=link["version"],
        idempotency_key="registry-snapshot-0001",
        normalized_snapshot=normalized,
    )
    created = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json=payload,
    )
    assert created.status_code == 201, created.text
    result = created.json()
    assert result["attempt"]["external_call"] is False
    assert result["attempt"]["status"] == "succeeded"
    assert result["link"]["freshness_status"] == "current"
    assert result["no_change"] is False
    by_path = {row["field_path"]: row for row in result["diffs"]}
    assert by_path["/mark_name"]["risk_level"] == "low"
    assert by_path["/mark_name"]["change_kind"] == "added"
    assert by_path["/status"]["risk_level"] == "high"
    assert by_path["/status"]["change_kind"] == "changed"
    assert by_path["/identifiers"]["change_kind"] == "removed"
    assert by_path["/renewal_date"]["deadline_recalculation_state"] == "required"

    replay = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["attempt"]["id"] == result["attempt"]["id"]
    assert replay.json()["snapshot"]["id"] == result["snapshot"]["id"]
    conflicting_replay = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json=payload | {"normalized_snapshot": normalized | {"status": "refused"}},
    )
    assert conflicting_replay.status_code == 409
    assert "different registry request" in conflicting_replay.text

    accepted = client.post(
        f"/api/ip/registry-diffs/{by_path['/mark_name']['id']}/resolve",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "accept",
            "reason": "The mark name is verified against the captured register record.",
            "effective_at": "2026-08-24T08:30:00Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["resolution_status"] == "accepted"
    assert accepted.json()["emitted_event_id"] is not None

    removed = client.post(
        f"/api/ip/registry-diffs/{by_path['/identifiers']['id']}/resolve",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "accept",
            "reason": "The empty local identifier placeholder is absent from the register.",
            "effective_at": "2026-08-24T08:30:00Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
        },
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["change_kind"] == "removed"

    malformed_mapping = client.post(
        f"/api/ip/registry-diffs/{by_path['/status']['id']}/resolve",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "map",
            "reason": "A canonical mapping must use an explicit JSON pointer.",
            "mapped_field_path": "status",
        },
    )
    assert malformed_mapping.status_code == 422
    assert "non-root JSON pointer" in malformed_mapping.text

    mapped = client.post(
        f"/api/ip/registry-diffs/{by_path['/status']['id']}/resolve",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "map",
            "reason": "Map provider status to the canonical application status field.",
            "mapped_field_path": "/status",
        },
    )
    assert mapped.status_code == 200, mapped.text
    assert mapped.json()["resolution_status"] == "mapped"

    monkeypatch.setattr(
        "caseops_api.services.ip_registry.membership_has_capability",
        lambda *_args, **_kwargs: False,
    )
    unauthorized_high_risk_acceptance = client.post(
        f"/api/ip/registry-diffs/{by_path['/status']['id']}/resolve",
        headers=headers,
        json={
            "expected_version": 2,
            "decision": "accept",
            "reason": "Attempt high-risk acceptance without the approval capability.",
            "effective_at": "2026-08-24T08:30:00Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
        },
    )
    assert unauthorized_high_risk_acceptance.status_code == 403

    deferred = client.post(
        f"/api/ip/registry-diffs/{by_path['/renewal_date']['id']}/resolve",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "defer",
            "reason": "Await lawyer review of the applicable renewal rule version.",
        },
    )
    assert deferred.status_code == 200, deferred.text
    assert deferred.json()["resolution_status"] == "deferred"

    workspace = client.get(
        f"/api/ip/registry-links?docket_id={docket['id']}",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    [current] = workspace.json()
    accepted_state = current["link"]["accepted_state_json"]
    assert accepted_state["mark_name"] == "REGISTRY RECONCILIATION"
    assert "identifiers" not in accepted_state

    no_change = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json=_snapshot_payload(
            link_version=current["link"]["version"],
            idempotency_key="registry-no-change-0002",
            normalized_snapshot=accepted_state,
        ),
    )
    assert no_change.status_code == 201, no_change.text
    assert no_change.json()["no_change"] is True
    assert no_change.json()["attempt"]["status"] == "no_change"
    assert no_change.json()["diffs"] == []

    with get_session_factory()() as session:
        events = list(
            session.scalars(
                select(IpDocketEvent)
                .where(IpDocketEvent.docket_id == docket["id"])
                .order_by(IpDocketEvent.sequence)
            ).all()
        )
        assert [(row.event_kind, row.candidate_status) for row in events] == [
            ("registry_change", "candidate"),
            ("registry_change", "reconciled"),
            ("registry_change", "candidate"),
            ("registry_change", "reconciled"),
        ]
        assert events[1].reconciles_event_id == events[0].id
        assert events[3].reconciles_event_id == events[2].id
        assert session.scalar(select(func.count()).select_from(IpRegistrySyncAttempt)) == 2


def test_registry_failure_preserves_last_good_state_and_snapshots_are_immutable(
    client: TestClient,
) -> None:
    _, headers, _, _, link = _confirmed_application_link(client)
    first = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json=_snapshot_payload(
            link_version=link["version"],
            idempotency_key="registry-baseline-0001",
            normalized_snapshot=link["accepted_state_json"],
        ),
    )
    assert first.status_code == 201, first.text
    baseline = first.json()
    assert baseline["no_change"] is True

    failed = client.post(
        f"/api/ip/registry-links/{link['id']}/failures",
        headers=headers,
        json={
            "expected_link_version": baseline["link"]["version"],
            "idempotency_key": "registry-failure-0002",
            "response_class": "authentication",
            "error": "Authorization: Bearer top-secret-token provider rejected request",
            "external_call": False,
            "source_retrieved_at": "2026-08-24T08:45:00Z",
        },
    )
    assert failed.status_code == 201, failed.text
    failure = failed.json()
    assert failure["attempt"]["status"] == "failed"
    assert failure["attempt"]["metadata_json"]["legal_state_changed"] is False
    assert "top-secret-token" not in (failure["attempt"]["error_redacted"] or "")
    assert failure["link"]["last_snapshot_id"] == baseline["snapshot"]["id"]
    assert failure["link"]["last_normalized_hash"] == baseline["link"][
        "last_normalized_hash"
    ]
    assert failure["link"]["last_successful_at"] == baseline["link"][
        "last_successful_at"
    ]

    fabricated_external_call = client.post(
        f"/api/ip/registry-links/{link['id']}/failures",
        headers=headers,
        json={
            "expected_link_version": failure["link"]["version"],
            "idempotency_key": "registry-external-claim-0003",
            "response_class": "provider_outage",
            "error": "Claimed provider request failed.",
            "external_call": True,
        },
    )
    assert fabricated_external_call.status_code == 422
    assert "blocked adapter" in fabricated_external_call.text

    correction = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json=_snapshot_payload(
            link_version=failure["link"]["version"],
            idempotency_key="registry-correction-0004",
            normalized_snapshot=link["accepted_state_json"] | {"note": "corrected capture"},
            supersedes_snapshot_id=baseline["snapshot"]["id"],
            correction_reason="The first capture omitted the registry note field.",
        ),
    )
    assert correction.status_code == 201, correction.text
    assert correction.json()["snapshot"]["supersedes_snapshot_id"] == baseline[
        "snapshot"
    ]["id"]

    forked_correction = client.post(
        f"/api/ip/registry-links/{link['id']}/snapshots/manual",
        headers=headers,
        json=_snapshot_payload(
            link_version=correction.json()["link"]["version"],
            idempotency_key="registry-correction-fork-0005",
            normalized_snapshot=link["accepted_state_json"] | {"note": "forked capture"},
            supersedes_snapshot_id=baseline["snapshot"]["id"],
            correction_reason="A second successor must not fork immutable lineage.",
        ),
    )
    assert forked_correction.status_code == 409
    assert "already has a correction successor" in forked_correction.text

    retired = client.post(
        f"/api/ip/registry-links/{link['id']}/match-decision",
        headers=headers,
        json={
            "expected_version": correction.json()["link"]["version"],
            "decision": "retire",
            "reason": "This registry identity is no longer an active reconciliation target.",
        },
    )
    assert retired.status_code == 200, retired.text
    retired_attempt = client.post(
        f"/api/ip/registry-links/{link['id']}/failures",
        headers=headers,
        json={
            "expected_link_version": retired.json()["version"],
            "idempotency_key": "registry-retired-attempt-0006",
            "response_class": "unknown",
            "error": "No new attempt may be attached after retirement.",
            "external_call": False,
        },
    )
    assert retired_attempt.status_code == 409
    assert "retired registry link" in retired_attempt.text

    with get_session_factory()() as session:
        with pytest.raises(DatabaseError):
            session.execute(
                text(
                    "UPDATE ip_registry_snapshots SET parser_version = 'tampered' "
                    "WHERE id = :snapshot_id"
                ),
                {"snapshot_id": baseline["snapshot"]["id"]},
            )
            session.commit()
        session.rollback()
        with pytest.raises(DatabaseError):
            session.execute(
                text("DELETE FROM ip_registry_snapshots WHERE id = :snapshot_id"),
                {"snapshot_id": baseline["snapshot"]["id"]},
            )
            session.commit()


def test_registry_is_tenant_scoped_and_rejects_non_registry_adapter(
    client: TestClient,
) -> None:
    first, first_headers, first_docket, application, link = _confirmed_application_link(client)
    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Registry Tenant B",
            "company_slug": "registry-tenant-b",
            "company_type": "law_firm",
            "owner_full_name": "Registry Tenant B Owner",
            "owner_email": "registry-b@example.com",
            "owner_password": "FixturePass123!",
        },
    )
    assert second.status_code == 200, second.text
    second_headers = auth_headers(str(second.json()["access_token"]))
    assert client.get(
        f"/api/ip/registry-links?docket_id={first_docket['id']}",
        headers=second_headers,
    ).status_code == 404
    assert client.post(
        f"/api/ip/registry-links/{link['id']}/match-decision",
        headers=second_headers,
        json={
            "expected_version": link["version"],
            "decision": "mismatch",
            "reason": "Cross-tenant write must not resolve this record.",
        },
    ).status_code == 404

    rejected = client.post(
        f"/api/ip/dockets/{first_docket['id']}/registry-links",
        headers=first_headers,
        json={
            "application_id": application["id"],
            "provider_key": "ecourtsindia",
            "office": "Delhi High Court",
            "jurisdiction": "IN",
            "identifier_kind": "cnr",
            "raw_identifier": "DLHC010012342026",
            "source_url": "https://services.ecourts.gov.in/",
            "match_confidence": "1.0",
            "match_evidence": {},
            "capability_version": "court-v1",
        },
    )
    assert rejected.status_code == 422
    assert "IP-office adapter" in rejected.text
    assert first["company"]["id"] != second.json()["company"]["id"]


def test_ip_proceeding_references_canonical_tracked_case_without_copying(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-COURT-REF-001")
    docket_response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "COURT REFERENCE",
            "matter_id": matter["id"],
            "restricted": False,
            "particulars": _particulars("COURT REFERENCE"),
        },
    )
    assert docket_response.status_code == 201, docket_response.text
    docket = docket_response.json()
    asset = _asset(client, headers, docket["id"], "COURT REFERENCE")
    application = _application(client, headers, docket["id"], asset["id"])
    proceeding_response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": application["id"],
            "proceeding_kind": "opposition",
            "side": "applicant",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "stage": "draft",
            "origin_kind": "registry_event",
            "source_pending_identifier_allocation": True,
        },
    )
    assert proceeding_response.status_code == 201, proceeding_response.text
    proceeding = proceeding_response.json()
    bookmark = client.post(
        "/api/case-tracking/bookmarks",
        headers=headers,
        json={
            "provider": "ecourtsindia",
            "cnr_number": "DLHC010012342026",
            "case_number": "C.O. (COMM.IPD-TM) 1/2026",
            "court_code": "DLHC",
            "court_name": "Delhi High Court",
            "case_title": "Fixture Applicant LLP v Registrar of Trade Marks",
            "party_names": ["Fixture Applicant LLP", "Registrar of Trade Marks"],
            "current_status": "Pending",
            "current_stage": "Notice",
            "matter_id": matter["id"],
        },
    )
    assert bookmark.status_code == 201, bookmark.text
    tracked_case_id = bookmark.json()["tracked_case"]["id"]

    created = client.post(
        f"/api/ip/dockets/{docket['id']}/tracked-case-references",
        headers=headers,
        json={
            "proceeding_id": proceeding["id"],
            "tracked_case_id": tracked_case_id,
            "purpose": "Opposition appeal tracking",
            "evidence_reference": "matter-bookmark:IP-COURT-REF-001",
        },
    )
    assert created.status_code == 201, created.text
    reference = created.json()
    assert reference["tracked_case_id"] == tracked_case_id
    assert reference["case_title"] == "Fixture Applicant LLP v Registrar of Trade Marks"
    assert reference["update_count"] == 0

    mismatch = client.post(
        f"/api/ip/tracked-case-references/{reference['id']}/decision",
        headers=headers,
        json={
            "expected_version": 1,
            "decision": "mismatch",
            "reason": "The registry proceeding was mapped to the wrong court matter.",
        },
    )
    assert mismatch.status_code == 200, mismatch.text
    assert mismatch.json()["link_status"] == "mismatch"

    with get_session_factory()() as session:
        assert session.scalar(select(TrackedCase).where(TrackedCase.id == tracked_case_id))
        assert session.scalar(
            select(IpTrackedCaseLink).where(IpTrackedCaseLink.id == reference["id"])
        )
        assert session.scalar(select(IpRegistrySnapshot)) is None
        assert session.scalar(select(IpRegistryLink)) is None
        assert session.scalar(select(IpRegistryDiff)) is None
