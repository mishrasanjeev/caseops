from copy import deepcopy
from datetime import UTC, datetime
from typing import get_args
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AuditEvent,
    IpPatentEvidenceVersion,
    IpPatentProsecutionEvent,
    MatterAccessGrant,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_patent_prosecution import PatentDocumentKind, PatentEventKind
from tests.test_ip_patent_applications import BASE, _closed, _create, _setup

# These endpoint templates are exercised through _save and the direct reads
# below. Keep the concrete paths visible to the route-coverage audit.
ROUTE_COVERAGE_PATHS = (
    "/api/ip/patents/applications/{application_id}/evidence",
    "/api/ip/patents/applications/{application_id}/evidence/{evidence_id}",
    "/api/ip/patents/applications/{application_id}/prosecution",
    "/api/ip/patents/applications/{application_id}/prosecution/{event_id}",
    "/api/ip/patents/applications/{application_id}/prosecution/preview",
)


def _fixture(client):
    bootstrap, headers, family, payload = _setup(client)
    headers = {**headers, "X-CaseOps-Automated-Test": "no-paid-providers"}
    response = _create(client, headers, payload)
    assert response.status_code == 201, response.text
    application = response.json()
    pin = payload["facts"]["source"]
    work = {
        "expected_version": 1,
        "expected_lifecycle_version": 0,
        "expected_work_sequence": 0,
        "reason": "Prepare exact synthetic test documents, not official legal content.",
        "title": "Response filing package",
        "document_kind": "filing_package",
        "source": pin,
        "documents": [{"document_kind": "claims", "source": pin}],
    }
    return bootstrap, headers, family, application, work


def _save(client, headers, application, path, raw, key=None):
    return client.post(
        f"{BASE}/{application['id']}/{path}",
        headers={**headers, "Idempotency-Key": key or str(uuid4())},
        json=raw,
    )


def _event(
    application,
    source,
    *,
    sequence=0,
    event_kind="filing_preparation",
    phase="disclosure",
    evidence_id=None,
    day="2026-09-07",
):
    return {
        "expected_version": application["version"],
        "expected_lifecycle_version": application["lifecycle_version"],
        "expected_work_sequence": sequence,
        "reason": "Record an independently reviewed sourced fact.",
        "event_kind": event_kind,
        "expected_phase": phase,
        "received_on": day,
        "effective_on": day,
        "source": source,
        "evidence_id": evidence_id,
    }


def _previewed(client, headers, application, raw):
    response = _save(client, headers, application, "prosecution/preview", raw)
    assert response.status_code == 200, response.text
    return {
        **raw,
        "preview_sha256": response.json()["preview_sha256"],
        "acknowledged_exception_codes": response.json()["required_acknowledgements"],
    }


def test_patent_manifest_filing_and_new_edition_retain_exact_receipt_history(client):
    _, headers, family, app, work = _fixture(client)
    family_before = client.get(f"/api/ip/patents/families/{family['id']}", headers=headers).json()
    saved = _save(client, headers, app, "evidence", work)
    assert saved.status_code == 201, saved.text
    edition = saved.json()
    manifest_before = client.get(
        f"{BASE}/{app['id']}/evidence/{edition['id']}", headers=headers
    ).json()
    event = _event(app, work["source"], sequence=1, event_kind="filing", evidence_id=edition["id"])
    posted = _save(client, headers, app, "prosecution", _previewed(client, headers, app, event))
    assert posted.status_code == 201, posted.text
    assert posted.json()["after_phase"] == "filed"
    assert posted.json()["impact"]["changes_deadlines"] is False
    event_before = client.get(
        f"{BASE}/{app['id']}/prosecution/{posted.json()['id']}", headers=headers
    ).json()
    second = _save(
        client,
        headers,
        app,
        "evidence",
        {
            **work,
            "expected_work_sequence": 2,
            "predecessor_id": edition["id"],
            "title": "Amended package",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["edition"] == 2 and second.json()["root_id"] == edition["id"]
    assert client.get(f"{BASE}/{app['id']}/evidence/{edition['id']}", headers=headers).json() == {
        **manifest_before,
        "is_current": False,
    }
    assert (
        client.get(f"{BASE}/{app['id']}/prosecution/{posted.json()['id']}", headers=headers).json()
        == event_before
    )
    assert (
        client.get(f"/api/ip/patents/families/{family['id']}", headers=headers).json()
        == family_before
    )
    assert client.get(f"{BASE}/{app['id']}", headers=headers).json()["prosecution_phase"] == "filed"
    assert (
        client.get(f"{BASE}/{app['id']}/prosecution", headers=headers).json()["work_sequence"] == 3
    )


def test_patent_work_idempotency_stale_commands_and_source_hash_fail_closed(client):
    _, headers, _, app, work = _fixture(client)
    key = str(uuid4())
    first = _save(client, headers, app, "evidence", work, key)
    assert first.status_code == 201, first.text
    assert _save(client, headers, app, "evidence", work, key).json() == first.json()
    assert _save(client, headers, app, "evidence", work).status_code == 409
    assert (
        _save(
            client, headers, app, "evidence", {**work, "title": "Conflicting command"}, key
        ).status_code
        == 409
    )
    wrong = deepcopy(work)
    wrong["expected_work_sequence"] = 1
    wrong["documents"][0]["source"]["content_sha256"] = "0" * 64
    assert _save(client, headers, app, "evidence", wrong).status_code == 409
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPatentEvidenceVersion)) == 1


def test_patent_backdated_and_exceptional_preview_must_be_acknowledged_and_current(client):
    _, headers, _, app, work = _fixture(client)
    initial = _event(app, work["source"])
    assert _save(client, headers, app, "prosecution", initial).status_code == 409
    first = _save(client, headers, app, "prosecution", _previewed(client, headers, app, initial))
    assert first.status_code == 201, first.text
    raw = _event(
        app,
        work["source"],
        sequence=1,
        phase="filing_preparation",
        event_kind="office_action",
        day="2026-09-06",
    )
    assert _save(client, headers, app, "prosecution/preview", raw).status_code == 409
    raw["exceptional_transition_reason"] = "Previously omitted office action is now evidenced."
    reviewed = _previewed(client, headers, app, raw)
    assert set(reviewed["acknowledged_exception_codes"]) == {
        "backdated_recalculation_review_required",
        "exceptional_transition_review_required",
    }
    missing = {**reviewed, "acknowledged_exception_codes": []}
    assert _save(client, headers, app, "prosecution", missing).status_code == 409
    changed = {**reviewed, "effective_on": "2026-09-05"}
    assert _save(client, headers, app, "prosecution", changed).status_code == 409
    saved = _save(client, headers, app, "prosecution", reviewed)
    assert saved.status_code == 201, saved.text
    assert saved.json()["impact"]["backdated"] is True
    assert saved.json()["after_phase"] == "examination"
    assert (
        saved.json()["impact"]["required_acknowledgements"]
        == reviewed["acknowledged_exception_codes"]
    )


def test_patent_work_closure_reopen_stale_replay_and_second_closure(client):
    _, headers, _, app, work = _fixture(client)
    key = str(uuid4())
    saved = _save(client, headers, app, "evidence", work, key)
    assert saved.status_code == 201, saved.text
    evidence_url = f"{BASE}/{app['id']}/evidence/{saved.json()['id']}"
    before = client.get(evidence_url, headers=headers).json()
    _closed(client, headers, app["docket_id"])
    assert client.get(evidence_url, headers=headers).json() == before
    assert _save(client, headers, app, "evidence", work, key).status_code == 404
    reopened = client.post(
        f"/api/ip/dockets/{app['docket_id']}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Explicitly reopen into intake without restoring old work.",
            "outcome": "reopened",
            "source": "lawyer_review",
            "evidence_ref": "test:patent-explicit-reopen",
            "linked_matter_handling": "reviewed",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert _save(client, headers, app, "evidence", work, key).status_code == 409
    replacement = {
        **work,
        "expected_lifecycle_version": 2,
        "expected_work_sequence": 1,
        "predecessor_id": saved.json()["id"],
        "title": "After reopen",
    }
    assert _save(client, headers, app, "evidence", replacement).status_code == 409
    replacement["predecessor_id"] = None
    assert _save(client, headers, app, "evidence", replacement).status_code == 201
    closed_again = client.post(
        f"/api/ip/dockets/{app['docket_id']}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 2,
            "to_status": "closed",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Close the independent patent for a second time.",
            "outcome": "closed",
            "source": "lawyer_review",
            "evidence_ref": "test:patent-second-close",
            "linked_matter_handling": "reviewed",
        },
    )
    assert closed_again.status_code == 200, closed_again.text
    assert client.get(evidence_url, headers=headers).json() == before


def test_patent_manifest_and_event_direct_mutation_rejected(client):
    _, headers, _, app, work = _fixture(client)
    assert _save(client, headers, app, "evidence", work).status_code == 201
    raw = _event(app, work["source"], sequence=1)
    assert (
        _save(
            client, headers, app, "prosecution", _previewed(client, headers, app, raw)
        ).status_code
        == 201
    )
    for table in (
        "ip_patent_evidence_versions",
        "ip_patent_evidence_documents",
        "ip_patent_prosecution_events",
    ):
        for command in (f"UPDATE {table} SET company_id = company_id", f"DELETE FROM {table}"):
            with get_session_factory()() as session, pytest.raises(IntegrityError):
                session.execute(text(command))
                session.commit()
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPatentProsecutionEvent)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "ip_patent_prosecution.recorded")
            )
            == 1
        )


def test_patent_work_current_source_access_and_other_application_scope(client):
    bootstrap, headers, family, app, work = _fixture(client)
    saved = _save(client, headers, app, "evidence", work)
    assert saved.status_code == 201, saved.text
    sibling_payload = {
        "family_id": family["id"],
        "expected_family_version": family["version"],
        "expected_family_lifecycle_version": family["lifecycle_version"],
        "facts": {**app["facts"], "office": "Different sourced office"},
    }
    sibling = _create(client, headers, sibling_payload)
    assert sibling.status_code == 201, sibling.text
    raw = _event(
        sibling.json(), work["source"], event_kind="filing", evidence_id=saved.json()["id"]
    )
    assert _save(client, headers, sibling.json(), "prosecution/preview", raw).status_code == 404
    assert (
        client.get(f"{BASE}/{sibling.json()['id']}", headers=headers).json()["prosecution_phase"]
        == "disclosure"
    )
    with get_session_factory()() as session:
        for grant in session.scalars(
            select(MatterAccessGrant).where(
                MatterAccessGrant.membership_id == bootstrap["membership"]["id"]
            )
        ):
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.get(f"{BASE}/{app['id']}/evidence", headers=headers).status_code == 404
    assert (
        _save(client, headers, app, "evidence", {**work, "expected_work_sequence": 1}).status_code
        == 404
    )


def test_patent_event_replay_reopen_and_current_access_revocation(client):
    bootstrap, headers, _, app, work = _fixture(client)
    key = str(uuid4())
    raw = _previewed(client, headers, app, _event(app, work["source"]))
    saved = _save(client, headers, app, "prosecution", raw, key)
    assert saved.status_code == 201, saved.text
    original = saved.json()
    event_url = f"{BASE}/{app['id']}/prosecution/{original['id']}"
    replay = _save(client, headers, app, "prosecution", raw, key)
    assert replay.status_code == 201 and replay.json() == original
    assert _save(client, headers, app, "prosecution", raw).status_code == 409
    assert (
        _save(
            client, headers, app, "prosecution", {**raw, "reason": "Changed command."}, key
        ).status_code
        == 409
    )
    _closed(client, headers, app["docket_id"])
    retained = client.get(event_url, headers=headers)
    assert retained.status_code == 200 and retained.json() == original
    assert _save(client, headers, app, "prosecution", raw, key).status_code == 404
    reopened = client.post(
        f"/api/ip/dockets/{app['docket_id']}/lifecycle",
        headers=headers,
        json={
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "effective_at": datetime.now(UTC).isoformat(),
            "reason": "Explicit reopen before a new independently sourced event.",
            "outcome": "reopened",
            "source": "lawyer_review",
            "evidence_ref": "test:patent-event-reopen",
            "linked_matter_handling": "reviewed",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert _save(client, headers, app, "prosecution", raw, key).status_code == 409
    current = client.get(f"{BASE}/{app['id']}", headers=headers).json()
    next_raw = _event(
        current, work["source"], sequence=1, event_kind="office_action", phase="filing_preparation"
    )
    next_raw["exceptional_transition_reason"] = "A separately evidenced office action after reopen."
    next_command = _previewed(client, headers, current, next_raw)
    next_key = str(uuid4())
    next_event = _save(client, headers, current, "prosecution", next_command, next_key)
    assert next_event.status_code == 201, next_event.text
    assert next_event.json()["lifecycle_version"] == 2
    assert client.get(event_url, headers=headers).json() == original
    with get_session_factory()() as session:
        for grant in session.scalars(
            select(MatterAccessGrant).where(
                MatterAccessGrant.company_id == bootstrap["company"]["id"],
                MatterAccessGrant.membership_id == bootstrap["membership"]["id"],
            )
        ):
            grant.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.get(event_url, headers=headers).status_code == 404
    assert client.get(f"{BASE}/{app['id']}/prosecution", headers=headers).status_code == 404
    assert _save(client, headers, current, "prosecution", next_command, next_key).status_code == 404
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(IpPatentProsecutionEvent)) == 2


def test_patent_work_pages_and_manifest_contracts_are_bounded(client):
    _, headers, _, app, work = _fixture(client)
    for sequence in range(3):
        assert (
            _save(
                client,
                headers,
                app,
                "evidence",
                {**work, "expected_work_sequence": sequence, "title": f"Versioned work {sequence}"},
            ).status_code
            == 201
        )
    page = client.get(f"{BASE}/{app['id']}/evidence?limit=2", headers=headers).json()
    assert len(page["records"]) == 2 and page["next_cursor"] == 2
    next_page = client.get(
        f"{BASE}/{app['id']}/evidence?limit=2&cursor=2&snapshot_sequence=3", headers=headers
    )
    assert next_page.status_code == 200 and len(next_page.json()["records"]) == 1
    assert client.get(f"{BASE}/{app['id']}/evidence?cursor=2", headers=headers).status_code == 422
    assert client.get(f"{BASE}/{app['id']}/evidence?limit=101", headers=headers).status_code == 422
    assert (
        client.get(
            f"{BASE}/{app['id']}/evidence?cursor=2&snapshot_sequence=2", headers=headers
        ).status_code
        == 409
    )
    assert (
        _save(
            client, headers, app, "evidence", {**work, "documents": work["documents"] * 2}
        ).status_code
        == 422
    )
    assert (
        _save(
            client, headers, app, "evidence", {**work, "document_kind": "trademark_response"}
        ).status_code
        == 422
    )
    assert (
        _save(
            client,
            headers,
            app,
            "prosecution",
            {**_event(app, work["source"]), "event_kind": "lifecycle_transition"},
        ).status_code
        == 422
    )
    assert (
        _save(
            client,
            headers,
            app,
            "prosecution",
            {**_event(app, work["source"]), "event_kind": "registration"},
        ).status_code
        == 422
    )


def test_every_patent_document_kind_retains_exact_source_and_edition_history(client):
    _, headers, _, app, work = _fixture(client)
    sequence = 0
    for kind in get_args(PatentDocumentKind):
        command = {
            **work,
            "expected_work_sequence": sequence,
            "document_kind": kind,
            "title": f"Original {kind}",
            "documents": [
                {
                    "document_kind": "claims" if kind == "filing_package" else kind,
                    "source": work["source"],
                }
            ],
        }
        key = str(uuid4())
        saved = _save(client, headers, app, "evidence", command, key)
        assert saved.status_code == 201, saved.text
        original = saved.json()
        assert _save(client, headers, app, "evidence", command, key).json() == original
        assert original["document_kind"] == kind
        assert original["source"]["content_sha256"] == work["source"]["content_sha256"]
        sequence += 1
        replaced = _save(
            client,
            headers,
            app,
            "evidence",
            {
                **command,
                "expected_work_sequence": sequence,
                "title": f"Reviewed {kind}",
                "predecessor_id": original["id"],
            },
        )
        assert replaced.status_code == 201, replaced.text
        assert replaced.json()["root_id"] == original["id"]
        assert replaced.json()["predecessor_id"] == original["id"]
        assert replaced.json()["edition"] == 2
        retained = client.get(f"{BASE}/{app['id']}/evidence/{original['id']}", headers=headers)
        assert retained.status_code == 200
        assert retained.json() == {**original, "is_current": False}
        sequence += 1
    page = client.get(f"{BASE}/{app['id']}/evidence?limit=100", headers=headers)
    assert page.status_code == 200 and page.json()["work_sequence"] == sequence
    assert len(page.json()["records"]) == 2 * len(get_args(PatentDocumentKind))


def test_every_admitted_prosecution_event_preserves_sibling_and_audited_history(client):
    bootstrap, headers, family, app, work = _fixture(client)
    sibling = _create(
        client,
        headers,
        {
            "family_id": family["id"],
            "expected_family_version": family["version"],
            "expected_family_lifecycle_version": family["lifecycle_version"],
            "facts": {**app["facts"], "office": "Independent sibling office"},
        },
    )
    assert sibling.status_code == 201, sibling.text
    sibling_url = f"{BASE}/{sibling.json()['id']}"
    sibling_before = client.get(sibling_url, headers=headers).json()
    sibling_history = client.get(f"{sibling_url}/prosecution", headers=headers).json()
    assert sibling_history["records"] == [] and sibling_history["work_sequence"] == 0
    saved = _save(client, headers, app, "evidence", work)
    assert saved.status_code == 201, saved.text
    evidence_id = saved.json()["id"]
    sequence, phase = 1, "disclosure"
    original_events = []
    for kind in get_args(PatentEventKind):
        if kind == "restoration":
            _closed(client, headers, app["docket_id"])
            reopened = client.post(
                f"/api/ip/dockets/{app['docket_id']}/lifecycle",
                headers=headers,
                json={
                    "expected_lifecycle_version": 1,
                    "to_status": "ready",
                    "effective_at": datetime.now(UTC).isoformat(),
                    "reason": "Explicit reopening before a sourced restoration record.",
                    "outcome": "reopened",
                    "source": "lawyer_review",
                    "evidence_ref": "test:admitted-event-restoration",
                    "linked_matter_handling": "reviewed",
                },
            )
            assert reopened.status_code == 200, reopened.text
            app = client.get(f"{BASE}/{app['id']}", headers=headers).json()
        raw = _event(
            app,
            work["source"],
            sequence=sequence,
            event_kind=kind,
            phase=phase,
            evidence_id=evidence_id
            if kind in {"filing", "response", "amendment", "grant"}
            else None,
        )
        if kind == "restoration":
            raw["exceptional_transition_reason"] = (
                "Sourced manual restoration after explicit reopen."
            )
        command = _previewed(client, headers, app, raw)
        key = str(uuid4())
        response = _save(client, headers, app, "prosecution", command, key)
        assert response.status_code == 201, response.text
        event = response.json()
        assert _save(client, headers, app, "prosecution", command, key).json() == event
        assert event["event_kind"] == kind and event["sequence"] == sequence + 1
        assert event["before_phase"] == phase and event["source"] == saved.json()["source"]
        assert event["impact"]["changes_deadlines"] is False
        assert event["impact"]["authoritative_calculation_available"] is False
        original_events.append(event)
        phase, sequence = event["after_phase"], sequence + 1
        current = client.get(f"{BASE}/{app['id']}", headers=headers)
        assert current.status_code == 200 and current.json()["prosecution_phase"] == phase
        assert client.get(sibling_url, headers=headers).json() == sibling_before
        assert client.get(f"{sibling_url}/prosecution", headers=headers).json() == sibling_history
    for event in original_events:
        retained = client.get(f"{BASE}/{app['id']}/prosecution/{event['id']}", headers=headers)
        assert retained.status_code == 200 and retained.json() == event
    with get_session_factory()() as session:
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == bootstrap["company"]["id"],
                    AuditEvent.action == "ip_patent_prosecution.recorded",
                )
            )
        )
        assert {row.target_id for row in audits} == {row["id"] for row in original_events}
        assert len(audits) == len(original_events) == len(get_args(PatentEventKind))
