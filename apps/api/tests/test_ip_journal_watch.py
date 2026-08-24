from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select

from caseops_api.db.models import (
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
    NotificationDeliveryIntent,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_watch import (
    IpJournalIngestRequest,
    IpJournalPublicationCreate,
    IpWatchProfileCreateRequest,
)
from caseops_api.services import ip_watch as ip_watch_service
from caseops_api.services.ip_watch import run_journal_watch_scheduler
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket


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
    select_count = sum(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert select_count <= 24

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
