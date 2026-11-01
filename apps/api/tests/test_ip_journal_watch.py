from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select

from caseops_api.db.models import (
    CompanyMembership,
    DomainOutboxEvent,
    IpDocketEvent,
    IpDocketRecord,
    IpJournalIngestionRun,
    IpJournalPublication,
    IpMatterLink,
    IpProceeding,
    IpWatchHandoff,
    IpWatchHit,
    IpWatchProfile,
    Matter,
    MatterDeadline,
    MatterTask,
    MembershipRole,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_watch import (
    IpJournalIngestRequest,
    IpJournalPublicationCreate,
    IpWatchHandoffRequest,
    IpWatchProfileCreateRequest,
)
from caseops_api.services import ip_watch as ip_watch_service
from caseops_api.services.ip_watch import run_journal_watch_scheduler
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket, _particulars


def _fixture(client: TestClient, title: str = "ASTER") -> tuple[dict, dict, dict, dict]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    docket = _docket(client, headers, title)
    asset = _asset(client, headers, docket["id"], title)
    application = _application(client, headers, docket["id"], asset["id"])
    return bootstrap, headers, docket, application


def _profile(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket_id: str,
    recipient_id: str,
    max_cost: int = 1000,
) -> dict:
    response = client.post(
        "/api/ip/watch/profiles",
        headers=headers,
        json={
            "docket_id": docket_id,
            "name": "ASTER word, phonetic and class watch",
            "word_terms": ["ASTER"],
            "phonetic_terms": ["ASTER"],
            "device_references": ["https://evidence.example/aster-device.png"],
            "class_numbers": [9, 42],
            "proprietor_terms": ["Aster Legal"],
            "jurisdictions": ["IN"],
            "frequency": "publication",
            "recipient_membership_ids": [recipient_id],
            "max_cost_minor_per_period": max_cost,
            "cost_currency": "INR",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _publication(
    *,
    application_id: str,
    application_number: str = "TM-9876543",
    source_status: str = "available",
    publication_kind: str = "advertisement",
    supersedes_publication_id: str | None = None,
    correction_reason: str | None = None,
    journal_number: str = "TMJ-2248",
    journal_date: str = "2026-08-21",
    source_retrieved_at: str = "2026-08-21T06:00:00Z",
) -> dict:
    return {
        "application_id": application_id,
        "journal_number": journal_number,
        "journal_date": journal_date,
        "publication_kind": publication_kind,
        "application_number": application_number,
        "mark_text": "ASTER PRIME",
        "device_reference": "https://evidence.example/aster-prime.png",
        "proprietor_name": "Aster Legal Technologies",
        "office": "IP India",
        "jurisdiction": "IN",
        "class_numbers": [9, 42],
        "goods_services": {
            "9": ["downloadable legal software"],
            "42": ["software as a service"],
        },
        "publication_scope": {
            "scope_kind": "partial",
            "published_classes": [9, 42],
        },
        "source_url": "https://ipindia.gov.in/journal/2248/page/412",
        "source_page": "412",
        "source_status": source_status,
        "source_retrieved_at": source_retrieved_at,
        "parser_version": "manual-journal-v1",
        "attribution": {"publisher": "IP India", "capture_method": "manual"},
        "raw_evidence": {
            "journal_heading": "Trade Marks Journal No. 2248",
            "device_similarity": {"method": "ai", "score": 0.84},
        },
        "supersedes_publication_id": supersedes_publication_id,
        "correction_reason": correction_reason,
    }


def _ingest(
    client: TestClient,
    *,
    headers: dict[str, str],
    key: str,
    publication: dict,
    cost_minor: int = 10,
) -> dict:
    response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": key,
            "provider_key": "ipindia-journal-manual",
            "external_call": False,
            "cost_minor": cost_minor,
            "currency": "INR",
            "publications": [publication],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "docket_id": "docket-1",
                "name": "Empty watch",
                "frequency": "daily",
                "recipient_membership_ids": ["member-1"],
            },
            "at least one criterion",
        ),
        (
            {
                "journal_number": "2248",
                "journal_date": "2026-08-21",
                "application_number": "TM-1",
                "mark_text": "ASTER",
                "office": "IP India",
                "jurisdiction": "IN",
                "class_numbers": [46],
                "source_url": "https://ipindia.gov.in/journal/2248",
                "source_status": "available",
                "parser_version": "manual-v1",
            },
            "between 1 and 45",
        ),
    ],
)
def test_watch_contracts_reject_incomplete_or_invalid_scope(payload: dict, message: str) -> None:
    model = IpWatchProfileCreateRequest if "docket_id" in payload else IpJournalPublicationCreate
    with pytest.raises(ValidationError, match=message):
        model.model_validate(payload)


def test_watch_contracts_reject_unsafe_profile_publication_and_handoff_inputs() -> None:
    profile = {
        "docket_id": "docket-1",
        "name": "ASTER watch",
        "word_terms": ["ASTER"],
        "frequency": "daily",
        "recipient_membership_ids": ["member-1"],
    }
    publication = {
        "journal_number": "2248",
        "journal_date": "2026-08-21",
        "application_number": "TM-1",
        "mark_text": "ASTER",
        "office": "IP India",
        "jurisdiction": "IN",
        "class_numbers": [9],
        "source_url": "https://ipindia.gov.in/journal/2248",
        "source_status": "available",
        "parser_version": "manual-v1",
    }
    invalid_contracts = [
        (
            IpWatchProfileCreateRequest,
            profile | {"class_numbers": [0]},
            "between 1 and 45",
        ),
        (
            IpWatchProfileCreateRequest,
            profile | {"recipient_membership_ids": ["member-1", "member-1"]},
            "recipients must be unique",
        ),
        (
            IpWatchProfileCreateRequest,
            profile | {"device_references": ["file:///untrusted-device.png"]},
            "must use HTTP or HTTPS",
        ),
        (
            IpJournalPublicationCreate,
            publication | {"mark_text": None},
            "requires a word mark or device reference",
        ),
        (
            IpJournalPublicationCreate,
            publication | {"source_url": "file:///untrusted-journal.pdf"},
            "source URL must use HTTP or HTTPS",
        ),
        (
            IpJournalPublicationCreate,
            publication | {"device_reference": "file:///untrusted-device.png"},
            "Device reference must use HTTP or HTTPS",
        ),
        (
            IpJournalPublicationCreate,
            publication | {"class_numbers": [9, 9]},
            "Publication classes must be unique",
        ),
        (
            IpJournalPublicationCreate,
            publication | {"goods_services": {"42": ["Legal services"]}},
            "scope must belong to a published class",
        ),
        (
            IpJournalPublicationCreate,
            publication | {"publication_kind": "correction"},
            "requires predecessor and reason",
        ),
        (
            IpJournalPublicationCreate,
            publication | {"source_retrieved_at": "2026-08-24T10:00:00"},
            "must include a timezone",
        ),
        (
            IpWatchHandoffRequest,
            {"handoff_kind": "task"},
            "requires a title",
        ),
        (
            IpWatchHandoffRequest,
            {"handoff_kind": "deadline", "title": "Confirm limitation"},
            "requires a due date",
        ),
        (
            IpWatchHandoffRequest,
            {"handoff_kind": "enforcement_matter", "title": "Open enforcement review"},
            "requires a matter code",
        ),
    ]

    for model, payload, message in invalid_contracts:
        with pytest.raises(ValidationError, match=message):
            model.model_validate(payload)


def test_iplf_uj_21_normal_watch_review_and_canonical_handoffs(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, application = _fixture(client)
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    result = _ingest(
        client,
        headers=headers,
        key="watch-ingestion-normal-0001",
        publication=_publication(application_id=application["id"]),
    )
    assert result["run"]["status"] == "succeeded"
    assert result["run"]["publications_created"] == 1
    assert result["run"]["hits_created"] == 1
    hit = result["hits"][0]
    assert hit["profile_id"] == profile["id"]
    assert hit["classes_goods_json"]["scope"]["scope_kind"] == "partial"
    assert hit["similarity_evidence_json"]["word"][0]["score"] > 0.6
    assert hit["similarity_evidence_json"]["class_overlap"] == [9, 42]
    assert hit["ai_advisory"] is True
    assert "advisory" in hit["advisory_notice"].lower()
    assert hit["source_url"].startswith("https://ipindia.gov.in/")

    review = client.post(
        f"/api/ip/watch/hits/{hit['id']}/disposition",
        headers=headers,
        json={
            "expected_version": hit["version"],
            "disposition": "relevant",
            "reason": "Official journal confirms an overlapping mark and class scope.",
            "source_confirmed": True,
        },
    )
    assert review.status_code == 200, review.text
    reviewed = review.json()
    assert reviewed["deadline_confirmation_state"] == "confirmed"
    assert reviewed["reviewer_decision_json"]["ai_was_advisory"] is True

    task = client.post(
        f"/api/ip/watch/hits/{hit['id']}/handoffs",
        headers=headers,
        json={
            "handoff_kind": "task",
            "title": "Review ASTER PRIME opposition",
            "due_on": "2026-09-01",
            "assignee_membership_id": bootstrap["membership"]["id"],
            "notes": "Confirm client appetite and grounds.",
        },
    )
    assert task.status_code == 201, task.text
    task_handoff = task.json()
    assert task_handoff["target_type"] == "matter_task"
    assert task_handoff["source_snapshot_json"]["source_url"] == hit["source_url"]
    assert task_handoff["reviewer_decision_json"]["disposition"] == "relevant"

    deadline = client.post(
        f"/api/ip/watch/hits/{hit['id']}/handoffs",
        headers=headers,
        json={
            "handoff_kind": "deadline",
            "title": "Confirm opposition limitation",
            "due_on": "2026-09-20",
            "assignee_membership_id": bootstrap["membership"]["id"],
        },
    )
    assert deadline.status_code == 201, deadline.text
    assert deadline.json()["target_type"] == "matter_deadline"

    opposition = client.post(
        f"/api/ip/watch/hits/{hit['id']}/handoffs",
        headers=headers,
        json={
            "handoff_kind": "opposition",
            "application_id": application["id"],
            "represented_side": "opponent",
        },
    )
    assert opposition.status_code == 201, opposition.text
    assert opposition.json()["target_type"] == "ip_proceeding"

    report = client.post(
        f"/api/ip/watch/hits/{hit['id']}/handoffs",
        headers=headers,
        json={
            "handoff_kind": "client_report_item",
            "assignee_membership_id": bootstrap["membership"]["id"],
        },
    )
    assert report.status_code == 201, report.text
    assert report.json()["target_type"] == "ip_docket_event"

    enforcement = client.post(
        f"/api/ip/watch/hits/{hit['id']}/handoffs",
        headers=headers,
        json={
            "handoff_kind": "enforcement_matter",
            "title": "ASTER PRIME enforcement review",
            "matter_code": "IP-ENF-ASTER-001",
            "assignee_membership_id": bootstrap["membership"]["id"],
            "notes": "Preserve the confirmed journal source and attorney decision.",
        },
    )
    assert enforcement.status_code == 201, enforcement.text
    assert enforcement.json()["target_type"] == "matter"

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        assert session.get(MatterTask, task_handoff["target_id"]).ip_docket_id == docket["id"]
        assert (
            session.get(MatterDeadline, deadline.json()["target_id"]).ip_docket_id == docket["id"]
        )
        proceeding = session.get(IpProceeding, opposition.json()["target_id"])
        assert proceeding is not None and proceeding.origin_kind == "watch_hit"
        enforcement_matter = session.get(Matter, enforcement.json()["target_id"])
        assert enforcement_matter is not None
        assert enforcement_matter.forum_level == "advisory"
        outbox = session.scalar(
            select(DomainOutboxEvent).where(
                DomainOutboxEvent.company_id == bootstrap["company"]["id"],
                DomainOutboxEvent.event_key == f"ip-watch-hit:{hit['id']}:1",
            )
        )
        assert outbox is not None
        assert "notification-intent-adapter" in outbox.expected_consumers_json
        intent = session.scalar(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == bootstrap["company"]["id"],
                NotificationDeliveryIntent.source_type == "ip_watch_hit",
                NotificationDeliveryIntent.source_id == hit["id"],
                NotificationDeliveryIntent.recipient_membership_id == bootstrap["membership"]["id"],
            )
        )
        assert intent is not None
        assert str(intent.status) == "delivered"
        assert (
            session.scalar(
                select(IpDocketEvent).where(
                    IpDocketEvent.company_id == bootstrap["company"]["id"],
                    IpDocketEvent.payload_json["watch_hit_id"].as_string() == hit["id"],
                )
            )
            is not None
        )


def test_watch_handoff_target_and_evidence_link_are_atomic_and_retryable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap, headers, docket, application = _fixture(client, "ORBIT")
    _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    result = _ingest(
        client,
        headers=headers,
        key="watch-ingestion-atomic-0001",
        publication=_publication(
            application_id=application["id"],
            application_number="TM-ATOMIC-001",
        ),
    )
    hit = result["hits"][0]
    review = client.post(
        f"/api/ip/watch/hits/{hit['id']}/disposition",
        headers=headers,
        json={
            "expected_version": hit["version"],
            "disposition": "relevant",
            "reason": "Official journal evidence was confirmed for the atomicity test.",
            "source_confirmed": True,
        },
    )
    assert review.status_code == 200, review.text

    original_record = ip_watch_service.record_from_context

    def fail_final_handoff_audit(*args: object, **kwargs: object) -> object:
        if kwargs.get("action") == "ip_watch.handoff_completed":
            raise RuntimeError("simulated final handoff failure")
        return original_record(*args, **kwargs)

    monkeypatch.setattr(
        ip_watch_service,
        "record_from_context",
        fail_final_handoff_audit,
    )
    payload = {
        "handoff_kind": "enforcement_matter",
        "title": "ORBIT enforcement rollback proof",
        "matter_code": "IP-ENF-ATOMIC-001",
        "assignee_membership_id": bootstrap["membership"]["id"],
    }
    with pytest.raises(RuntimeError, match="simulated final handoff failure"):
        client.post(
            f"/api/ip/watch/hits/{hit['id']}/handoffs",
            headers=headers,
            json=payload,
        )

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        assert (
            session.scalar(select(IpWatchHandoff).where(IpWatchHandoff.hit_id == hit["id"])) is None
        )
        assert (
            session.scalar(select(Matter).where(Matter.matter_code == payload["matter_code"]))
            is None
        )
        assert (
            session.scalar(select(IpMatterLink).where(IpMatterLink.docket_id == docket["id"]))
            is None
        )

    monkeypatch.setattr(ip_watch_service, "record_from_context", original_record)
    retry = client.post(
        f"/api/ip/watch/hits/{hit['id']}/handoffs",
        headers=headers,
        json=payload,
    )
    assert retry.status_code == 201, retry.text
    with SessionLocal() as session:
        assert (
            len(
                list(
                    session.scalars(
                        select(IpWatchHandoff).where(IpWatchHandoff.hit_id == hit["id"])
                    )
                )
            )
            == 1
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(Matter).where(Matter.matter_code == payload["matter_code"])
                    )
                )
            )
            == 1
        )


def test_iplf_uj_21_exceptions_source_duplicate_cost_and_tenant_scope(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, application = _fixture(client)
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
        max_cost=5,
    )
    paused = _ingest(
        client,
        headers=headers,
        key="watch-cost-paused-0001",
        publication=_publication(application_id=application["id"]),
        cost_minor=10,
    )
    assert paused["run"]["status"] == "paused_cost_quota"
    assert paused["hits"] == []
    workspace = client.get("/api/ip/watch", headers=headers)
    assert workspace.status_code == 200
    paused_profile = next(
        item for item in workspace.json()["profiles"] if item["id"] == profile["id"]
    )
    assert paused_profile["poll_status"] == "paused_cost_quota"
    assert "quota" in paused_profile["pause_reason"].lower()

    resumed = client.post(
        f"/api/ip/watch/profiles/{profile['id']}/status",
        headers=headers,
        json={
            "expected_version": paused_profile["version"],
            "poll_status": "active",
            "reason": "Approved manual source review has no provider cost.",
        },
    )
    assert resumed.status_code == 200, resumed.text
    unavailable = _ingest(
        client,
        headers=headers,
        key="watch-unavailable-0001",
        publication=_publication(
            application_id=application["id"],
            application_number="TM-UNAVAILABLE",
            source_status="unavailable",
            journal_number="TMJ-2249",
        ),
        cost_minor=0,
    )
    hit = unavailable["hits"][0]
    blocked = client.post(
        f"/api/ip/watch/hits/{hit['id']}/disposition",
        headers=headers,
        json={
            "expected_version": hit["version"],
            "disposition": "not_relevant",
            "reason": "Attempting a source-dependent final review.",
            "source_confirmed": False,
        },
    )
    assert blocked.status_code == 422
    assert "official source" in blocked.text
    reviewing = client.post(
        f"/api/ip/watch/hits/{hit['id']}/disposition",
        headers=headers,
        json={
            "expected_version": hit["version"],
            "disposition": "reviewing",
            "reason": "Official journal source is temporarily unavailable.",
            "source_confirmed": False,
        },
    )
    assert reviewing.status_code == 200

    replay = _ingest(
        client,
        headers=headers,
        key="watch-unavailable-0001",
        publication=_publication(
            application_id=application["id"],
            application_number="TM-UNAVAILABLE",
            source_status="unavailable",
            journal_number="TMJ-2249",
        ),
        cost_minor=0,
    )
    assert replay["idempotent_replay"] is True
    assert replay["publications"][0]["id"] == unavailable["publications"][0]["id"]
    assert replay["hits"][0]["id"] == unavailable["hits"][0]["id"]
    conflict_payload = _publication(
        application_id=application["id"],
        application_number="TM-DIFFERENT",
        source_status="unavailable",
        journal_number="TMJ-2250",
    )
    conflict = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": "watch-unavailable-0001",
            "provider_key": "ipindia-journal-manual",
            "external_call": False,
            "cost_minor": 0,
            "currency": "INR",
            "publications": [conflict_payload],
        },
    )
    assert conflict.status_code == 409
    assert "different journal payload" in conflict.text
    second_run = _ingest(
        client,
        headers=headers,
        key="watch-unavailable-0002",
        publication=_publication(
            application_id=application["id"],
            application_number="TM-UNAVAILABLE",
            source_status="unavailable",
            journal_number="TMJ-2249",
        ),
        cost_minor=0,
    )
    assert second_run["run"]["duplicate_hits"] == 1
    assert second_run["hits"] == []
    assert second_run["publications"][0]["id"] == unavailable["publications"][0]["id"]

    other_tenant = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Beacon IP Partners",
            "company_slug": "beacon-ip-watch",
            "company_type": "law_firm",
            "owner_full_name": "Beacon Owner",
            "owner_email": "owner@beaconip.example",
            "owner_password": "BeaconWatch123!",
        },
    )
    assert other_tenant.status_code == 200, other_tenant.text
    isolated = client.get(
        "/api/ip/watch",
        headers=auth_headers(other_tenant.json()["access_token"]),
    )
    assert isolated.status_code == 200, isolated.text
    assert isolated.json() == {
        "profiles": [],
        "hits": [],
        "publications": [],
        "ingestion_runs": [],
        "handoffs": [],
        "intake_profile_count": 0,
    }


def test_iplf_uj_33_correction_scope_and_delayed_ingestion(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, application = _fixture(client)
    _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    original = _ingest(
        client,
        headers=headers,
        key="watch-original-0001",
        publication=_publication(application_id=application["id"]),
    )
    old_hit = original["hits"][0]
    reviewed = client.post(
        f"/api/ip/watch/hits/{old_hit['id']}/disposition",
        headers=headers,
        json={
            "expected_version": old_hit["version"],
            "disposition": "relevant",
            "reason": "Original publication verified from official journal.",
            "source_confirmed": True,
        },
    ).json()
    correction = _ingest(
        client,
        headers=headers,
        key="watch-correction-0001",
        publication=_publication(
            application_id=application["id"],
            publication_kind="readvertisement",
            supersedes_publication_id=original["publications"][0]["id"],
            correction_reason="Goods scope corrected and application re-advertised.",
            journal_number="TMJ-2252",
            journal_date="2026-08-24",
            source_retrieved_at="2026-09-01T10:00:00Z",
        ),
    )
    new_hit = correction["hits"][0]
    assert new_hit["duplicate_of_hit_id"] == old_hit["id"]
    assert new_hit["stale_source_alert"] is True
    assert correction["run"]["stale_source_alert"] is True
    workspace = client.get("/api/ip/watch", headers=headers).json()
    unchanged_old = next(item for item in workspace["hits"] if item["id"] == old_hit["id"])
    assert unchanged_old["deadline_confirmation_state"] == "confirmed"
    confirmed = client.post(
        f"/api/ip/watch/hits/{new_hit['id']}/disposition",
        headers=headers,
        json={
            "expected_version": new_hit["version"],
            "disposition": "relevant",
            "reason": "Re-advertisement and corrected class scope verified from source.",
            "source_confirmed": True,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    workspace = client.get("/api/ip/watch", headers=headers).json()
    superseded_old = next(item for item in workspace["hits"] if item["id"] == old_hit["id"])
    assert superseded_old["deadline_confirmation_state"] == "superseded"
    assert confirmed.json()["deadline_confirmation_state"] == "confirmed"
    assert reviewed["classes_goods_json"]["scope"]["published_classes"] == [9, 42]


def test_journal_publication_is_immutable_and_handoff_retains_decision(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, application = _fixture(client)
    _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    result = _ingest(
        client,
        headers=headers,
        key="watch-immutable-0001",
        publication=_publication(application_id=application["id"]),
    )
    publication_id = result["publications"][0]["id"]
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        publication = session.get(IpJournalPublication, publication_id)
        assert publication is not None
        publication.mark_text = "REWRITTEN"
        with pytest.raises(Exception, match="append-only"):
            session.commit()
        session.rollback()
        assert (
            session.scalar(select(IpWatchHit).where(IpWatchHit.publication_id == publication_id))
            is not None
        )
        assert (
            session.scalar(select(IpWatchHandoff).where(IpWatchHandoff.hit_id == "missing")) is None
        )


def test_journal_watch_scheduler_is_durable_and_fail_closed(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, _ = _fixture(client)
    manual = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    external = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    SessionLocal = get_session_factory()
    scheduled_at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    with SessionLocal() as session:
        external_profile = session.get(IpWatchProfile, external["id"])
        assert external_profile is not None
        external_profile.provider_key = "unlicensed-journal-provider"
        external_profile.next_poll_at = scheduled_at
        manual_profile = session.get(IpWatchProfile, manual["id"])
        assert manual_profile is not None
        manual_profile.next_poll_at = scheduled_at
        session.commit()
        result = run_journal_watch_scheduler(session, now=scheduled_at)
        assert result.due_profiles == 2
        assert result.checked_profiles == 1
        assert result.provider_paused_profiles == 1
        assert result.external_calls == 0
        session.refresh(external_profile)
        assert external_profile.poll_status == "paused"
        assert "activation" in external_profile.pause_reason.lower()
        runs = list(
            session.scalars(
                select(IpJournalIngestionRun).where(
                    IpJournalIngestionRun.company_id == bootstrap["company"]["id"]
                )
            )
        )
        assert {row.status for row in runs} == {"succeeded", "failed"}
        assert all(row.external_call is False for row in runs)


def test_device_similarity_requires_affirmative_reference_bound_evidence(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, application = _fixture(client, "DEVICE")
    profile_response = client.post(
        "/api/ip/watch/profiles",
        headers=headers,
        json={
            "docket_id": docket["id"],
            "name": "DEVICE reference watch",
            "device_references": ["https://evidence.example/registered-device.png"],
            "frequency": "daily",
            "recipient_membership_ids": [bootstrap["membership"]["id"]],
            "cost_currency": "INR",
        },
    )
    assert profile_response.status_code == 201, profile_response.text
    low_score = _publication(
        application_id=application["id"],
        application_number="TM-DEVICE-LOW",
        journal_number="TMJ-DEVICE-LOW",
    )
    low_score["mark_text"] = None
    low_score["device_reference"] = "https://evidence.example/candidate-device.png"
    low_score["class_numbers"] = [9]
    low_score["goods_services"] = {"9": ["software"]}
    # The scope may only cover published classes (BUG-014 contract).
    low_score["publication_scope"] = {"scope_kind": "partial", "published_classes": [9]}
    low_score["raw_evidence"]["device_similarity"] = {"method": "ai", "score": 0.01}
    rejected_match = _ingest(
        client,
        headers=headers,
        key="watch-device-negative-0001",
        publication=low_score,
        cost_minor=0,
    )
    assert rejected_match["hits"] == []

    confirmed = _publication(
        application_id=application["id"],
        application_number="TM-DEVICE-CONFIRMED",
        journal_number="TMJ-DEVICE-CONFIRMED",
    )
    confirmed["mark_text"] = None
    confirmed["device_reference"] = "https://evidence.example/candidate-device.png"
    confirmed["class_numbers"] = [9]
    confirmed["goods_services"] = {"9": ["software"]}
    confirmed["publication_scope"] = {"scope_kind": "partial", "published_classes": [9]}
    confirmed["raw_evidence"]["device_similarity"] = {
        "method": "ai",
        "score": 0.94,
        "matched": True,
        "profile_reference": "https://evidence.example/registered-device.png",
        "candidate_reference": "https://evidence.example/candidate-device.png",
    }
    accepted_match = _ingest(
        client,
        headers=headers,
        key="watch-device-confirmed-0001",
        publication=confirmed,
        cost_minor=0,
    )
    assert len(accepted_match["hits"]) == 1
    assert accepted_match["hits"][0]["similarity_evidence_json"]["device"]["matched"] is True
    assert accepted_match["hits"][0]["ai_advisory"] is True


def test_ingestion_rejects_cross_currency_charging_without_partial_writes(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, application = _fixture(client, "CURRENCY")
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": "watch-currency-mismatch-0001",
            "provider_key": "ipindia-journal-manual",
            "external_call": False,
            "cost_minor": 10,
            "currency": "USD",
            "publications": [_publication(application_id=application["id"])],
        },
    )
    assert response.status_code == 422, response.text
    assert "currency" in response.text.lower()
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        persisted = session.get(IpWatchProfile, profile["id"])
        assert persisted is not None and persisted.spent_cost_minor_in_period == 0
        assert (
            session.scalar(
                select(IpJournalIngestionRun).where(
                    IpJournalIngestionRun.idempotency_key == "watch-currency-mismatch-0001"
                )
            )
            is None
        )


def test_quota_resets_at_period_boundary_and_terminal_dockets_never_run(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "PERIOD")
    profile = _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
        max_cost=100,
    )
    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        row = session.get(IpWatchProfile, profile["id"])
        assert row is not None
        row.frequency = "daily"
        row.spent_cost_minor_in_period = 100
        row.last_polled_at = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)
        row.next_poll_at = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
        row.poll_status = "paused_cost_quota"
        row.pause_reason = "Prior UTC-day quota exhausted."
        session.commit()
        result = run_journal_watch_scheduler(session, now=datetime(2026, 8, 24, 12, 0, tzinfo=UTC))
        assert result.due_profiles == 1
        assert result.checked_profiles == 1
        session.refresh(row)
        assert row.poll_status == "active"
        assert row.pause_reason is None
        assert row.spent_cost_minor_in_period == 0

        docket_row = session.get(IpDocketRecord, docket["id"])
        assert docket_row is not None
        docket_row.status = "archived"
        docket_row.is_active = False
        docket_row.archived_by_matter_disposal = True
        row.next_poll_at = datetime(2026, 8, 25, 0, 0, tzinfo=UTC)
        run_count = len(
            list(
                session.scalars(
                    select(IpJournalIngestionRun).where(
                        IpJournalIngestionRun.company_id == bootstrap["company"]["id"]
                    )
                )
            )
        )
        session.commit()
        terminal_result = run_journal_watch_scheduler(
            session, now=datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
        )
        assert terminal_result.due_profiles == 0
        assert (
            len(
                list(
                    session.scalars(
                        select(IpJournalIngestionRun).where(
                            IpJournalIngestionRun.company_id == bootstrap["company"]["id"]
                        )
                    )
                )
            )
            == run_count
        )


def test_ingestion_is_bounded_and_batches_profile_publication_lookups(
    client: TestClient,
) -> None:
    with pytest.raises(ValidationError, match="at most 50"):
        IpJournalIngestRequest.model_validate(
            {
                "idempotency_key": "watch-over-limit-0001",
                "provider_key": "manual-journal",
                "publications": [{}] * 51,
            }
        )

    bootstrap, headers, docket, application = _fixture(client, "BATCH")
    for index in range(2):
        response = client.post(
            "/api/ip/watch/profiles",
            headers=headers,
            json={
                "docket_id": docket["id"],
                "name": f"No-match profile {index}",
                "word_terms": [f"UNRELATED-{index}"],
                "class_numbers": [1],
                "frequency": "daily",
                "recipient_membership_ids": [bootstrap["membership"]["id"]],
                "cost_currency": "INR",
            },
        )
        assert response.status_code == 201, response.text
    publications = [
        _publication(
            application_id=application["id"],
            application_number=f"TM-BATCH-{index}",
            journal_number=f"TMJ-BATCH-{index}",
        )
        for index in range(2)
    ]
    statements: list[str] = []

    def capture_statement(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement)

    SessionLocal = get_session_factory()
    with SessionLocal() as session:
        assert session.bind is not None
        event.listen(session.bind, "before_cursor_execute", capture_statement)
        try:
            response = client.post(
                "/api/ip/watch/journal-ingestions",
                headers=headers,
                json={
                    "idempotency_key": "watch-batched-ingestion-0001",
                    "provider_key": "ipindia-journal-manual",
                    "external_call": False,
                    "cost_minor": 0,
                    "currency": "INR",
                    "publications": publications,
                },
            )
        finally:
            event.remove(session.bind, "before_cursor_execute", capture_statement)
    assert response.status_code == 201, response.text
    assert response.json()["hits"] == []
    assert len(statements) <= 24, statements

    _profile(
        client,
        headers=headers,
        docket_id=docket["id"],
        recipient_id=bootstrap["membership"]["id"],
    )
    duplicate_item = _publication(
        application_id=application["id"],
        application_number="TM-BATCH-DUPLICATE",
        journal_number="TMJ-BATCH-DUPLICATE",
    )
    duplicate_response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": "watch-same-payload-duplicate-0001",
            "provider_key": "ipindia-journal-manual",
            "external_call": False,
            "cost_minor": 0,
            "currency": "INR",
            "publications": [duplicate_item, duplicate_item],
        },
    )
    assert duplicate_response.status_code == 201, duplicate_response.text
    duplicate_body = duplicate_response.json()
    assert duplicate_body["run"]["publications_seen"] == 2
    assert duplicate_body["run"]["publications_created"] == 1
    assert len(duplicate_body["publications"]) == 1
    assert len(duplicate_body["hits"]) == 1


# BUG-014 (Ram 2026-10-30): a lawyer's journal capture failed with a 422 that
# blamed nothing ("List should have at least 1 item ...; Input should be a valid
# list") or leaked a parser error, and an empty "{}" was accepted as evidence.


def _manual_capture(**overrides: object) -> dict:
    """The payload the web intake form builds from lawyer inputs."""

    return {
        "application_id": None,
        "journal_number": "2187",
        "journal_date": "2026-10-27",
        "publication_kind": "advertisement",
        "application_number": "BUG014-CAPTURE-1",
        "mark_text": "ZQXV CAPTURE",
        "device_reference": None,
        "proprietor_name": None,
        "office": "IP India",
        "jurisdiction": "IN",
        "class_numbers": [45],
        "goods_services": {"45": ["Legal services"]},
        "publication_scope": {"scope_kind": "full"},
        "source_url": "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal",
        "source_page": "45",
        "source_status": "available",
        "source_retrieved_at": None,
        "parser_version": "manual-journal-v1",
        "attribution": {"publisher": "IP India", "capture_method": "manual"},
        "raw_evidence": {
            "extract_text": "Journal 2187 page 45: ZQXV CAPTURE, class 45, legal services.",
            "capture_method": "manual",
        },
        "supersedes_publication_id": None,
        "correction_reason": None,
    } | overrides


def _errors(payload: dict) -> list[dict]:
    with pytest.raises(ValidationError) as caught:
        IpJournalPublicationCreate.model_validate(payload)
    return caught.value.errors()


def test_bug_014_lawyer_capture_shape_is_accepted() -> None:
    model = IpJournalPublicationCreate.model_validate(_manual_capture())
    assert model.class_numbers == [45]
    assert model.goods_services == {"45": ["Legal services"]}
    assert model.raw_evidence["extract_text"].startswith("Journal 2187")


def test_bug_014_web_form_payloads_satisfy_the_api_contract() -> None:
    # apps/web/lib/ip/journal-capture.test.ts asserts the intake form builds
    # exactly these payloads, so the web form and this contract cannot drift.
    fixture = Path(__file__).parent / "fixtures" / "journal_capture_web_payloads.json"
    payloads = json.loads(fixture.read_text(encoding="utf-8"))
    assert len(payloads) == 2
    for payload in payloads:
        IpJournalPublicationCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("overrides", "loc", "fragment"),
    [
        ({"class_numbers": []}, ("class_numbers",), "at least 1 item"),
        ({"class_numbers": [46]}, ("class_numbers",), "between 1 and 45"),
        ({"class_numbers": [45, 45]}, ("class_numbers",), "list each Nice class once"),
        (
            {"goods_services": {"Class 45": ["Legal services"]}},
            ("goods_services",),
            "Nice class number from 1 to 45",
        ),
        (
            {"goods_services": {"30": ["Biscuits"]}},
            ("goods_services",),
            "Class 30 is not a published class",
        ),
        ({"goods_services": {"45": ["  "]}}, ("goods_services",), "blank entries"),
        ({"goods_services": {"45": "Legal services"}}, ("goods_services", "45"), "valid list"),
        (
            {"publication_scope": {"scope_kind": "partial", "published_classes": [30]}},
            ("publication_scope",),
            "only cover classes it publishes",
        ),
        ({"publication_scope": {"scope_kind": "some"}}, ("publication_scope",), "full or partial"),
        ({"raw_evidence": {}}, ("raw_evidence",), "Capture the source evidence"),
        (
            {"raw_evidence": {"capture_method": "manual", "extract_text": "   "}},
            ("raw_evidence",),
            "Capture the source evidence",
        ),
        ({"source_url": "ftp://journal.example"}, ("source_url",), "HTTP or HTTPS"),
    ],
)
def test_bug_014_each_journal_failure_is_anchored_to_its_field(
    overrides: dict, loc: tuple[str, ...], fragment: str
) -> None:
    errors = _errors(_manual_capture(**overrides))
    assert [error["loc"] for error in errors] == [loc]
    assert fragment in errors[0]["msg"]
    assert "invalid literal" not in errors[0]["msg"]


def test_bug_014_ingest_422_names_the_field_without_parser_text(client: TestClient) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "CAPTURE")
    _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=bootstrap["membership"]["id"]
    )
    response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": "bug014-empty-evidence-0001",
            "provider_key": "ipindia-journal-manual",
            "publications": [
                _manual_capture(
                    raw_evidence={},
                    goods_services={"Class 45": ["Legal services"]},
                )
            ],
        },
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert sorted(tuple(error["loc"]) for error in body["errors"]) == [
        ("body", "publications", 0, "goods_services"),
        ("body", "publications", 0, "raw_evidence"),
    ]
    assert "Publications › Raw evidence: Capture the source evidence" in body["detail"]
    assert "Value error" not in body["detail"]
    assert "invalid literal" not in body["detail"]
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(IpJournalIngestionRun).where(
                    IpJournalIngestionRun.idempotency_key == "bug014-empty-evidence-0001"
                )
            )
            is None
        )


def test_bug_014_capture_without_an_active_profile_is_refused_not_dropped(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "NOPROFILE")
    workspace = client.get("/api/ip/watch", headers=headers).json()
    assert workspace["intake_profile_count"] == 0
    response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": "bug014-no-profile-0001",
            "provider_key": "ipindia-journal-manual",
            "publications": [_manual_capture()],
        },
    )
    assert response.status_code == 409, response.text
    assert "No active watch profile" in response.json()["detail"]
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(IpJournalIngestionRun).where(
                    IpJournalIngestionRun.company_id == bootstrap["company"]["id"]
                )
            )
            is None
        )


def test_bug_014_zero_hit_capture_is_listed_with_its_evidence(client: TestClient) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "LISTED")
    response = client.post(
        "/api/ip/watch/profiles",
        headers=headers,
        json={
            "docket_id": docket["id"],
            "name": "Unrelated word watch",
            "word_terms": ["UNRELATED"],
            "frequency": "publication",
            "recipient_membership_ids": [bootstrap["membership"]["id"]],
        },
    )
    assert response.status_code == 201, response.text
    assert client.get("/api/ip/watch", headers=headers).json()["intake_profile_count"] == 1
    result = _ingest(
        client,
        headers=headers,
        key="bug014-zero-hit-0001",
        publication=_manual_capture(),
        cost_minor=0,
    )
    assert result["run"]["status"] == "succeeded"
    assert result["hits"] == []
    publication = result["publications"][0]
    assert publication["raw_evidence_json"]["extract_text"].startswith("Journal 2187")

    for scope in ({}, {"docket_id": docket["id"]}):
        workspace = client.get("/api/ip/watch", headers=headers, params=scope)
        assert workspace.status_code == 200, workspace.text
        listed = {item["id"]: item for item in workspace.json()["publications"]}
        assert publication["id"] in listed
        assert listed[publication["id"]]["raw_evidence_json"] == publication["raw_evidence_json"]

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Beacon IP Partners",
            "company_slug": "beacon-ip-capture",
            "company_type": "law_firm",
            "owner_full_name": "Beacon Owner",
            "owner_email": "owner@beacon-capture.example",
            "owner_password": "BeaconWatch123!",
        },
    )
    assert other.status_code == 200, other.text
    isolated = client.get("/api/ip/watch", headers=auth_headers(other.json()["access_token"]))
    assert isolated.status_code == 200, isolated.text
    assert isolated.json()["publications"] == []
    assert isolated.json()["intake_profile_count"] == 0


def _colleague(
    client: TestClient, headers: dict[str, str], *, email: str, role: MembershipRole
) -> dict[str, str]:
    created = client.post(
        "/api/companies/current/users",
        headers=headers,
        json={
            "full_name": f"Watch {role.value}",
            "email": email,
            "role": "member",
            "password": "ColleaguePass123!",
        },
    )
    assert created.status_code == 200, created.text
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, str(created.json()["membership_id"]))
        assert membership is not None
        membership.role = role
        session.commit()
    login = client.post(
        "/api/auth/login",
        json={"company_slug": "aster-legal", "email": email, "password": "ColleaguePass123!"},
    )
    assert login.status_code == 200, login.text
    return auth_headers(login.json()["access_token"])


def _word_profile(
    client: TestClient, headers: dict[str, str], *, docket_id: str, word: str, recipient: str
) -> dict:
    response = client.post(
        "/api/ip/watch/profiles",
        headers=headers,
        json={
            "docket_id": docket_id,
            "name": f"{word} word watch",
            "word_terms": [word],
            "frequency": "publication",
            "recipient_membership_ids": [recipient],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _listed(client: TestClient, headers: dict[str, str], **params: str) -> set[str]:
    workspace = client.get("/api/ip/watch", headers=headers, params=params)
    assert workspace.status_code == 200, workspace.text
    return {item["id"] for item in workspace.json()["publications"]}


def _searched(client: TestClient, headers: dict[str, str], q: str | None = None) -> set[str]:
    response = client.get(
        "/api/ip/watch/publications", headers=headers, params={"q": q} if q else {}
    )
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()["publications"]}


def test_bug_014_listed_capture_respects_docket_visibility(client: TestClient) -> None:
    bootstrap, headers, open_docket, _ = _fixture(client, "OPENWATCH")
    owner_id = bootstrap["membership"]["id"]
    restricted = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": "WALLED", "restricted": True, "particulars": _particulars("WALLED")},
    )
    assert restricted.status_code == 201, restricted.text
    walled_docket = restricted.json()["id"]
    walled_asset = _asset(client, headers, walled_docket, "WALLED")
    walled_application = _application(client, headers, walled_docket, walled_asset["id"])
    _word_profile(
        client, headers, docket_id=open_docket["id"], word="OPENMARK", recipient=owner_id
    )
    _word_profile(client, headers, docket_id=walled_docket, word="WALLMARK", recipient=owner_id)

    def capture(key: str, **overrides: object) -> dict:
        return _ingest(
            client, headers=headers, key=key, publication=_manual_capture(**overrides), cost_minor=0
        )

    linked = capture(
        "bug014-walled-0001",
        application_id=walled_application["id"],
        application_number="BUG014-WALLED",
    )["publications"][0]
    open_hit = capture(
        "bug014-openhit-0001", application_number="BUG014-OPENHIT", mark_text="OPENMARK"
    )
    walled_hit = capture(
        "bug014-wallhit-0001",
        application_number="BUG014-WALLHIT",
        mark_text="WALLMARK",
        raw_evidence={"extract_text": "Walled team capture notes.", "capture_method": "manual"},
    )
    zero_hit = capture("bug014-zerohit-0001", application_number="BUG014-ZEROHIT")
    assert len(open_hit["hits"]) == 1
    assert len(walled_hit["hits"]) == 1
    assert zero_hit["hits"] == []
    open_hit_id = open_hit["publications"][0]["id"]
    walled_hit_id = walled_hit["publications"][0]["id"]
    zero_hit_id = zero_hit["publications"][0]["id"]

    partner = _colleague(
        client, headers, email="watch-partner@asterlegal.in", role=MembershipRole.PARTNER
    )
    # A partner outside the wall sees the entry that hit a profile they can
    # see, never the walled team's unlinked capture (with its notes), the
    # walled application's entry, or a colleague's zero-hit capture.
    for seen in (_listed(client, partner), _searched(client, partner)):
        assert open_hit_id in seen
        assert {linked["id"], walled_hit_id, zero_hit_id}.isdisjoint(seen)
    assert _searched(client, partner, "wallmark") == set()
    owner_seen = _listed(client, headers)
    assert {linked["id"], open_hit_id, walled_hit_id, zero_hit_id} <= owner_seen
    assert _searched(client, headers, "BUG014-WALLHIT") == {walled_hit_id}
    # A typed wildcard never widens the search.
    assert _searched(client, headers, "BUG014%HIT") == set()

    admin = _colleague(
        client, headers, email="watch-admin@asterlegal.in", role=MembershipRole.ADMIN
    )
    # Only a visible entry can be corrected; the walled one reads as not found.
    hidden = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=admin,
        json={
            "idempotency_key": "bug014-hidden-correction-0001",
            "provider_key": "ipindia-journal-manual",
            "publications": [
                _manual_capture(
                    application_number="BUG014-WALLHIT",
                    publication_kind="correction",
                    supersedes_publication_id=walled_hit_id,
                    correction_reason="Corrected goods description.",
                )
            ],
        },
    )
    assert hidden.status_code == 404, hidden.text
    own = _ingest(
        client,
        headers=admin,
        key="bug014-admin-own-0001",
        publication=_manual_capture(application_number="BUG014-ADMINOWN"),
        cost_minor=0,
    )["publications"][0]
    assert own["id"] in _listed(client, admin)
    assert own["id"] not in _listed(client, partner)

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Beacon IP Partners",
            "company_slug": "beacon-ip-search",
            "company_type": "law_firm",
            "owner_full_name": "Beacon Owner",
            "owner_email": "owner@beacon-search.example",
            "owner_password": "BeaconWatch123!",
        },
    )
    assert other.status_code == 200, other.text
    assert _searched(client, auth_headers(other.json()["access_token"]), "BUG014") == set()


def test_bug_014_recapture_with_different_details_points_to_the_recorded_entry(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "RECAPTURE")
    _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=bootstrap["membership"]["id"]
    )
    first = _ingest(
        client, headers=headers, key="bug014-recapture-0001", publication=_manual_capture()
    )
    same = _ingest(
        client, headers=headers, key="bug014-recapture-0002", publication=_manual_capture()
    )
    assert same["publications"][0]["id"] == first["publications"][0]["id"]
    response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": "bug014-recapture-0003",
            "provider_key": "ipindia-journal-manual",
            "publications": [
                _manual_capture(
                    raw_evidence={
                        "extract_text": "A corrected extract.",
                        "capture_method": "manual",
                    }
                )
            ],
        },
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["type"] == "journal_entry_already_recorded"
    assert body["publication_id"] == first["publications"][0]["id"]
    assert "already recorded" in body["detail"]
    assert "only if the journal itself published one" in body["detail"]


def test_bug_014_recapture_of_a_walled_entry_does_not_reveal_it(client: TestClient) -> None:
    bootstrap, headers, open_docket, _ = _fixture(client, "WALLRECAP")
    owner_id = bootstrap["membership"]["id"]
    restricted = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": "WALLRECAP2", "restricted": True, "particulars": _particulars("WR2")},
    )
    assert restricted.status_code == 201, restricted.text
    _word_profile(client, headers, docket_id=open_docket["id"], word="NOMATCH", recipient=owner_id)
    _word_profile(
        client, headers, docket_id=restricted.json()["id"], word="ZQXV", recipient=owner_id
    )
    walled = _ingest(
        client, headers=headers, key="bug014-wallrecap-0001", publication=_manual_capture()
    )
    assert len(walled["hits"]) == 1
    admin = _colleague(
        client, headers, email="recap-admin@asterlegal.in", role=MembershipRole.ADMIN
    )
    response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=admin,
        json={
            "idempotency_key": "bug014-wallrecap-0002",
            "provider_key": "ipindia-journal-manual",
            "publications": [_manual_capture(mark_text="ZQXV OTHER")],
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["publication_id"] is None


def test_bug_014_correction_identity_error_names_the_application_number(
    client: TestClient,
) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "IDENTITY")
    _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=bootstrap["membership"]["id"]
    )
    original = _ingest(
        client, headers=headers, key="bug014-identity-0001", publication=_manual_capture()
    )["publications"][0]
    response = client.post(
        "/api/ip/watch/journal-ingestions",
        headers=headers,
        json={
            "idempotency_key": "bug014-identity-0002",
            "provider_key": "ipindia-journal-manual",
            "publications": [
                _manual_capture(
                    application_number="BUG014-SOMETHING-ELSE",
                    publication_kind="correction",
                    supersedes_publication_id=original["id"],
                    correction_reason="Corrected goods description.",
                )
            ],
        },
    )
    assert response.status_code == 422, response.text
    errors = response.json()["errors"]
    assert [tuple(error["loc"]) for error in errors] == [
        ("body", "publications", 0, "application_number")
    ]
    assert original["application_number"] in errors[0]["msg"]


def test_bug_014_profile_jurisdictions_use_the_canonical_vocabulary() -> None:
    def profile(jurisdictions: list[str]) -> IpWatchProfileCreateRequest:
        return IpWatchProfileCreateRequest.model_validate(
            {
                "docket_id": "docket-1",
                "name": "Jurisdiction check",
                "word_terms": ["ZQXV"],
                "jurisdictions": jurisdictions,
                "frequency": "daily",
                "recipient_membership_ids": ["member-1"],
            }
        )

    assert profile(["India", "in", " uk ", "EU", "WIPO"]).jurisdictions == ["IN", "GB", "EM", "WO"]
    with pytest.raises(ValidationError) as caught:
        profile(["India", "Narnia"])
    errors = caught.value.errors()
    assert [error["loc"] for error in errors] == [("jurisdictions",)]
    assert '"Narnia" is not a recognised jurisdiction' in errors[0]["msg"]


def test_bug_014_legacy_free_text_jurisdiction_still_matches(client: TestClient) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "LEGACYJUR")
    created = _word_profile(
        client,
        headers,
        docket_id=docket["id"],
        word="ZQXV",
        recipient=bootstrap["membership"]["id"],
    )
    with get_session_factory()() as session:
        stored = session.get(IpWatchProfile, created["id"])
        assert stored is not None
        stored.jurisdictions_json = ["INDIA"]
        session.commit()
    result = _ingest(
        client, headers=headers, key="bug014-legacyjur-0001", publication=_manual_capture()
    )
    assert len(result["hits"]) == 1
    assert result["hits"][0]["similarity_evidence_json"]["jurisdiction_match"] is True


def test_bug_014_hit_snapshot_keeps_the_captured_evidence(client: TestClient) -> None:
    bootstrap, headers, docket, application = _fixture(client, "SNAPSHOT")
    _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=bootstrap["membership"]["id"]
    )
    result = _ingest(
        client,
        headers=headers,
        key="bug014-snapshot-0001",
        publication=_publication(application_id=application["id"]),
    )
    hit = result["hits"][0]
    assert hit["source_snapshot_json"]["raw_evidence"]["journal_heading"] == (
        "Trade Marks Journal No. 2248"
    )


def test_bug_014_profile_with_only_a_jurisdiction_is_refused() -> None:
    # A jurisdiction narrows a match but never makes one: such a profile was
    # saved and silently never matched any journal entry.
    with pytest.raises(ValidationError, match="at least one criterion") as caught:
        IpWatchProfileCreateRequest.model_validate(
            {
                "docket_id": "docket-1",
                "name": "Jurisdiction only",
                "jurisdictions": ["IN"],
                "frequency": "daily",
                "recipient_membership_ids": ["member-1"],
            }
        )
    assert caught.value.errors()[0]["loc"] == ()
    with pytest.raises(ValidationError) as classes:
        IpWatchProfileCreateRequest.model_validate(
            {
                "docket_id": "docket-1",
                "name": "Bad class",
                "class_numbers": [46],
                "frequency": "daily",
                "recipient_membership_ids": ["member-1"],
            }
        )
    assert [error["loc"] for error in classes.value.errors()] == [("class_numbers",)]
