from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AuditEvent,
    IpIdentifier,
    IpPartyAndRole,
    IpPatentProceedingDetail,
    IpPatentProceedingEvent,
    MatterAccessGrant,
)
from caseops_api.db.session import get_session_factory
from tests.test_ip_patent_applications import BASE, _closed, _create
from tests.test_ip_patent_prosecution import _fixture, _save

# These endpoint templates are exercised through _save and the direct reads
# below. Keep the concrete paths visible to the route-coverage audit.
ROUTE_COVERAGE_PATHS = (
    "/api/ip/patents/applications/{application_id}/proceedings",
    "/api/ip/patents/applications/{application_id}/proceedings/{proceeding_id}",
    "/api/ip/patents/applications/{application_id}/proceedings/{proceeding_id}/preview",
    "/api/ip/patents/applications/{application_id}/proceedings/{proceeding_id}/transitions",
)


def _intake(work, **changes):
    return {
        "expected_version": 1,
        "expected_lifecycle_version": 0,
        "expected_work_sequence": 0,
        "reason": "Record the received synthetic opposition notice.",
        "source": work["source"],
        "received_on": "2026-09-10",
        "effective_on": "2026-09-10",
        "title": "Pre-grant opposition by Example Research",
        "counterparty": "Example Research",
        "side": "applicant",
        "source_pending_identifier_allocation": True,
        **changes,
    }


def _transition(record, **changes):
    return {
        "expected_version": 1,
        "expected_lifecycle_version": 0,
        "expected_work_sequence": record["latest"]["sequence"],
        "expected_proceeding_version": record["version"],
        "source": record["latest"]["source"],
        "received_on": "2026-09-10",
        "effective_on": "2026-09-10",
        "reason": "Record the reviewed opposition stage source.",
        "to_stage": "response_preparation",
        **changes,
    }


def _preview(client, headers, app, record, raw):
    result = _save(client, headers, app, f"proceedings/{record['id']}/preview", raw)
    assert result.status_code == 200, result.text
    return {
        **raw,
        "preview_sha256": result.json()["preview_sha256"],
        "acknowledged_exception_codes": result.json()["required_acknowledgements"],
    }


def _advance(client, headers, app, record, **changes):
    raw = _preview(client, headers, app, record, _transition(record, **changes))
    result = _save(client, headers, app, f"proceedings/{record['id']}/transitions", raw)
    assert result.status_code == 201, result.text
    return result.json()


def test_pregrant_proceeding_notice_response_hearing_decision_keeps_application_and_sibling(client):
    bootstrap, headers, family, app, work = _fixture(client)
    sibling = _create(
        client,
        headers,
        {
            "family_id": family["id"],
            "expected_family_version": family["version"],
            "expected_family_lifecycle_version": family["lifecycle_version"],
            "facts": {**app["facts"], "office": "USPTO"},
        },
    )
    assert sibling.status_code == 201, sibling.text
    sibling_before = sibling.json()
    raw = _intake(work)
    key = str(uuid4())
    created = _save(client, headers, app, "proceedings", raw, key)
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["id"] != app["id"] and record["stage"] == "notice_recorded"
    assert record["latest"]["proceeding_number"] is None
    assert _save(client, headers, app, "proceedings", raw, key).json() == record
    history_url = f"{BASE}/{app['id']}/proceedings/{record['id']}"
    intake = client.get(history_url, headers=headers).json()["events"][0]
    record = _advance(client, headers, app, record, proceeding_number="SYN-PGO-2026-001")
    manifest = _save(
        client,
        headers,
        app,
        "evidence",
        {
            **work,
            "expected_work_sequence": 2,
            "document_kind": "response",
            "documents": [{"document_kind": "response", "source": work["source"]}],
        },
    )
    assert manifest.status_code == 201, manifest.text
    record = _advance(
        client,
        headers,
        app,
        record,
        expected_work_sequence=3,
        to_stage="response_filed",
        evidence_id=manifest.json()["id"],
    )
    assert record["latest"]["evidence_id"] == manifest.json()["id"]
    assert record["latest"]["proceeding_number"] == "SYN-PGO-2026-001"
    record = _advance(client, headers, app, record, to_stage="hearing_recorded")
    record = _advance(
        client,
        headers,
        app,
        record,
        to_stage="decided",
        outcome="Opposition rejected in the supplied synthetic decision.",
    )
    assert not record["operational"] and record["allowed_stages"] == []
    history = client.get(history_url, headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["events"][0] == intake
    assert [row["after_stage"] for row in history.json()["events"]] == [
        "notice_recorded",
        "response_preparation",
        "response_filed",
        "hearing_recorded",
        "decided",
    ]
    assert (
        client.get(f"{BASE}/{app['id']}", headers=headers).json()["prosecution_phase"]
        == app["prosecution_phase"]
    )
    assert client.get(f"{BASE}/{sibling_before['id']}", headers=headers).json() == sibling_before
    assert (
        _save(
            client, headers, app, f"proceedings/{record['id']}/preview", _transition(record)
        ).status_code
        == 409
    )
    with get_session_factory()() as session:
        number = session.scalar(
            select(IpIdentifier).where(IpIdentifier.proceeding_id == record["id"])
        )
        assert number.raw_value == "SYN-PGO-2026-001" and number.application_id is None
        party = session.scalar(
            select(IpPartyAndRole).where(IpPartyAndRole.proceeding_id == record["id"])
        )
        assert party.party_name == raw["counterparty"] and party.role_kind == "opponent"
        assert party.source == f"document-version:{work['source']['document_version_id']}"
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.company_id == bootstrap["company"]["id"],
                    AuditEvent.action.in_(
                        ["ip_patent_proceeding.created", "ip_patent_proceeding.transitioned"]
                    ),
                )
            )
            == 5
        )


def test_pregrant_contract_stale_duplicate_preview_and_source_fail_closed(client):
    _, headers, _, app, work = _fixture(client)
    raw = _intake(work)
    for changes in (
        {"proceeding_kind": "patent_post_grant_opposition"},
        {"source_pending_identifier_allocation": False},
        {"proceeding_number": "***", "source_pending_identifier_allocation": False},
    ):
        assert _save(client, headers, app, "proceedings", {**raw, **changes}).status_code == 422
    forged = deepcopy(raw)
    forged["source"]["content_sha256"] = "0" * 64
    assert _save(client, headers, app, "proceedings", forged).status_code == 409
    response = _save(
        client,
        headers,
        app,
        "proceedings",
        {**raw, "proceeding_number": "SYN-PGO-002", "source_pending_identifier_allocation": False},
    )
    assert response.status_code == 201, response.text
    record = response.json()
    assert _save(client, headers, app, "proceedings", raw).status_code == 409
    assert (
        _save(
            client,
            headers,
            app,
            "proceedings",
            {
                **raw,
                "expected_work_sequence": 1,
                "proceeding_number": "SYN-PGO-002",
                "source_pending_identifier_allocation": False,
            },
        ).status_code
        == 409
    )
    path = f"proceedings/{record['id']}"
    stage = _transition(record)
    assert _save(client, headers, app, f"{path}/transitions", stage).status_code == 409
    previewed = _preview(client, headers, app, record, stage)
    assert (
        _save(
            client,
            headers,
            app,
            f"{path}/transitions",
            {**previewed, "reason": "Changed after preview."},
        ).status_code
        == 409
    )
    assert (
        _save(
            client, headers, app, f"{path}/preview", {**stage, "proceeding_number": "ANOTHER"}
        ).status_code
        == 409
    )
    record = _advance(client, headers, app, record)
    assert _save(client, headers, app, f"{path}/transitions", previewed).status_code == 409
    exceptional = _transition(
        record,
        to_stage="decided",
        outcome="Synthetic decision received early.",
        effective_on="2026-09-09",
        exceptional_transition_reason="Decision issued without a recorded hearing.",
    )
    previewed = _preview(client, headers, app, record, exceptional)
    assert set(previewed["acknowledged_exception_codes"]) == {
        "backdated_source_review",
        "exceptional_stage_review",
    }
    assert (
        _save(
            client,
            headers,
            app,
            f"{path}/transitions",
            {**previewed, "acknowledged_exception_codes": []},
        ).status_code
        == 409
    )
    saved = _save(client, headers, app, f"{path}/transitions", previewed)
    assert saved.status_code == 201, saved.text
    assert saved.json()["latest"]["impact"]["changes_application_phase"] is False
    assert saved.json()["latest"]["impact"]["changes_deadlines"] is False


def test_pregrant_closure_reopen_does_not_resurrect_proceeding_or_allow_replay(client):
    _, headers, _, app, work = _fixture(client)
    raw, key = _intake(work), str(uuid4())
    created = _save(client, headers, app, "proceedings", raw, key)
    assert created.status_code == 201, created.text
    record = created.json()
    path = f"{BASE}/{app['id']}/proceedings/{record['id']}"
    retained = client.get(path, headers=headers).json()["events"]
    _closed(client, headers, app["docket_id"])
    closed = client.get(path, headers=headers)
    assert closed.status_code == 200 and not closed.json()["proceeding"]["operational"]
    assert closed.json()["events"] == retained
    assert _save(client, headers, app, "proceedings", raw, key).status_code == 404
    reopened = client.post(
        f"/api/ip/dockets/{app['docket_id']}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Explicit sourced reopening for a different application action.",
            "outcome": "reopened",
            "source": "lawyer_review",
            "evidence_ref": "test:pregrant-reopen",
            "linked_matter_handling": "reviewed",
        },
    )
    assert reopened.status_code in {200, 201}, reopened.text
    assert _save(client, headers, app, "proceedings", raw, key).status_code == 409
    assert not client.get(path, headers=headers).json()["proceeding"]["operational"]
    assert (
        _save(
            client,
            headers,
            app,
            f"proceedings/{record['id']}/preview",
            _transition(record, expected_lifecycle_version=2),
        ).status_code
        == 409
    )


def test_pregrant_sealed_history_current_acl_and_cross_application(client):
    bootstrap, headers, family, app, work = _fixture(client)
    saved = _save(client, headers, app, "proceedings", _intake(work))
    assert saved.status_code == 201, saved.text
    record = saved.json()
    other = _create(
        client,
        headers,
        {
            "family_id": family["id"],
            "expected_family_version": family["version"],
            "expected_family_lifecycle_version": family["lifecycle_version"],
            "facts": {**app["facts"], "office": "USPTO"},
        },
    )
    assert other.status_code == 201, other.text
    assert _save(client, headers, other.json(), "proceedings", _intake(work)).status_code == 409
    assert (
        client.get(
            f"{BASE}/{other.json()['id']}/proceedings/{record['id']}", headers=headers
        ).status_code
        == 404
    )
    with get_session_factory()() as session:
        for table in (
            IpPatentProceedingDetail.__tablename__,
            IpPatentProceedingEvent.__tablename__,
        ):
            with pytest.raises(IntegrityError):
                session.execute(text(f"DELETE FROM {table}"))
            session.rollback()
        grants = list(
            session.scalars(
                select(MatterAccessGrant).where(
                    MatterAccessGrant.membership_id == bootstrap["membership"]["id"]
                )
            )
        )
        for grant in grants:
            session.delete(grant)
        session.commit()
    assert (
        client.get(f"{BASE}/{app['id']}/proceedings/{record['id']}", headers=headers).status_code
        == 404
    )
    assert client.get(f"{BASE}/{app['id']}/proceedings", headers=headers).status_code == 404


def test_pregrant_response_manifest_is_current_exact_and_application_scoped(client):
    _, headers, _, app, work = _fixture(client)
    created = _save(client, headers, app, "proceedings", _intake(work))
    assert created.status_code == 201, created.text
    record = _advance(client, headers, app, created.json())
    path = f"proceedings/{record['id']}/preview"
    assert (
        _save(
            client, headers, app, path, _transition(record, to_stage="response_filed")
        ).status_code
        == 422
    )
    manifest = _save(client, headers, app, "evidence", {**work, "expected_work_sequence": 2})
    assert manifest.status_code == 201, manifest.text
    first = manifest.json()
    raw = _transition(
        record, expected_work_sequence=3, to_stage="response_filed", evidence_id=first["id"]
    )
    previewed = _preview(client, headers, app, record, raw)
    amended = _save(
        client,
        headers,
        app,
        "evidence",
        {
            **work,
            "expected_work_sequence": 3,
            "predecessor_id": first["id"],
            "title": "Corrected response package",
        },
    )
    assert amended.status_code == 201, amended.text
    assert (
        _save(
            client, headers, app, f"proceedings/{record['id']}/transitions", previewed
        ).status_code
        == 409
    )
    assert (
        _save(client, headers, app, path, {**raw, "expected_work_sequence": 4}).status_code == 409
    )
    saved = _advance(
        client,
        headers,
        app,
        record,
        expected_work_sequence=4,
        to_stage="response_filed",
        evidence_id=amended.json()["id"],
    )
    assert saved["latest"]["evidence_id"] == amended.json()["id"]
    assert saved["latest"]["source"] == work["source"]


def test_pregrant_opponent_withdrawal_has_separate_sourced_outcome(client):
    _, headers, _, app, work = _fixture(client)
    created = _save(client, headers, app, "proceedings", _intake(work, side="opponent"))
    assert created.status_code == 201, created.text
    record = _advance(
        client,
        headers,
        app,
        created.json(),
        to_stage="withdrawn",
        outcome="Opponent withdrew the sourced synthetic opposition.",
    )
    assert record["side"] == "opponent" and not record["operational"]
    assert record["latest"]["outcome"] == "Opponent withdrew the sourced synthetic opposition."
    assert (
        client.get(f"{BASE}/{app['id']}", headers=headers).json()["prosecution_phase"]
        == app["prosecution_phase"]
    )


def test_pregrant_number_does_not_collide_with_a_trademark_proceeding(client):
    from tests.test_ip_record_workflow import _docket

    _, headers, _, app, work = _fixture(client)
    legacy_docket = _docket(client, headers, "Independent trademark opposition")
    legacy = client.post(
        f"/api/ip/dockets/{legacy_docket['id']}/proceedings",
        headers=headers,
        json={
            "proceeding_kind": "opposition",
            "side": "applicant",
            "office": "IP India",
            "jurisdiction": "IN",
            "stage": "draft",
            "opposition_number": {
                "raw_value": "SYN-OPP-001",
                "source": "synthetic-registry-notice",
                "effective_from": "2026-09-10",
                "is_primary": True,
            },
        },
    )
    assert legacy.status_code == 201, legacy.text
    with get_session_factory()() as session:
        old = session.scalar(
            select(IpIdentifier).where(IpIdentifier.proceeding_id == legacy.json()["id"])
        )
        before = (old.id, old.raw_value, old.normalized_value, old.reconciliation_status)
    payload = _intake(
        work, proceeding_number="SYN-OPP-001", source_pending_identifier_allocation=False
    )
    patent = _save(client, headers, app, "proceedings", payload)
    assert patent.status_code == 201, patent.text
    with get_session_factory()() as session:
        patent_number = session.scalar(
            select(IpIdentifier).where(IpIdentifier.proceeding_id == patent.json()["id"])
        )
        assert patent_number.identifier_kind == "patent_pre_grant_opposition"
        patent_number_id = patent_number.id
    duplicate = _save(client, headers, app, "proceedings", {**payload, "expected_work_sequence": 1})
    assert duplicate.status_code == 409 and "patent_proceeding_duplicate_number" in duplicate.text
    with get_session_factory()() as session:
        old = session.get(IpIdentifier, before[0])
        assert (old.id, old.raw_value, old.normalized_value, old.reconciliation_status) == before
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpIdentifier)
                .where(IpIdentifier.raw_value == "SYN-OPP-001")
            )
            == 2
        )
    next_legacy = client.post(
        f"/api/ip/dockets/{legacy_docket['id']}/proceedings",
        headers=headers,
        json={
            "proceeding_kind": "opposition",
            "side": "applicant",
            "office": "IP India",
            "jurisdiction": "IN",
            "stage": "draft",
        },
    )
    assert next_legacy.status_code == 201, next_legacy.text
    candidates = client.post(
        f"/api/ip/dockets/{legacy_docket['id']}/identifiers",
        headers=headers,
        json={
            "identifier_kind": "opposition",
            "raw_value": "SYN-OPP-001",
            "office": "IP India",
            "jurisdiction": "IN",
            "source": "synthetic-registry-notice",
            "effective_from": "2026-09-10",
            "is_primary": True,
            "proceeding_id": next_legacy.json()["id"],
        },
    )
    assert candidates.status_code == 201, candidates.text
    assert [row["id"] for row in candidates.json()["duplicate_candidates"]] == [before[0]]
    assert patent_number_id not in candidates.text
