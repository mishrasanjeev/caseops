"""Real IP HTTP response snapshots around independent PostgreSQL worker commits."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.api.routes import ip_operations
from caseops_api.db.models import (
    BillingSubscription,
    DocumentProcessingJob,
    IpDocketRecord,
    IpDocumentVersion,
)
from caseops_api.services import document_jobs, ip_document_workflow
from tests.processing_snapshot_barriers import wait_for_processing_barrier
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_document_workflow import _upload

pytestmark = pytest.mark.postgres
BODY = ("Controlled offline IP snapshot content. " * 80)[:2838] + "X"
PREVIOUS_BODY = b"Earlier retained high quality source version and searchable facts. " * 30 + b"X"
QUALITY_REASON = "OCR/extraction quality is below the legal-use threshold."


def _seed(client, engine, monkeypatch):
    actor = bootstrap_company(client)
    headers = auth_headers(str(actor["access_token"]))
    headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    company_id = str(actor["company"]["id"])
    # Only this fresh isolated tenant gets a nonbillable manual entitlement.
    with Session(engine) as session:
        subscription = session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.company_id == company_id,
                BillingSubscription.status.in_(["active", "trialing", "grace", "manual_active"]),
            )
        )
        if subscription is None:
            subscription = BillingSubscription(company_id=company_id, segment="law_firm")
            session.add(subscription)
        subscription.status = "manual_active"
        subscription.source = "manual"
        subscription.externally_billable = False
        subscription.entitlement_overrides_json = {
            **(subscription.entitlement_overrides_json or {}),
            "ip_workspace": True,
        }
        session.commit()
    seeded = client.post("/api/ip/document-taxonomy/seed", headers=headers)
    assert seeded.status_code == 200, seeded.text
    with Session(engine) as session:
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Isolated native document snapshot",
            status="draft",
            created_by_membership_id=str(actor["membership"]["id"]),
        )
        session.add(docket)
        session.commit()
        docket_id = docket.id
    dispatched = []

    def capture_dispatch(*, session, background_tasks, job_id):
        del background_tasks
        assert session.get_bind().url.database == engine.url.database
        dispatched.append(job_id)

    monkeypatch.setattr(ip_operations, "dispatch_document_processing_job", capture_dispatch)
    return SimpleNamespace(
        headers=headers, docket_id=docket_id, dispatched=dispatched, company_id=company_id
    )


def _get(client, fixture, document_id):
    response = client.get(f"/api/ip/documents/{document_id}", headers=fixture.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _version(document, version_id):
    return next(row for row in document["versions"] if row["id"] == version_id)


def _snapshot(version):
    return {
        key: version[key]
        for key in (
            "id",
            "version",
            "processing_status",
            "sha256_hex",
            "extracted_char_count",
            "extraction_error",
            "ocr_quality_score",
            "low_ocr_quality",
            "ai_eligible",
            "latest_processing_job",
        )
    }


def _policy(client, fixture, document_id):
    response = client.get(f"/api/ip/documents/{document_id}/policy", headers=fixture.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _assert_positive(client, fixture, document_id, version_id):
    document = _get(client, fixture, document_id)
    version = _version(document, version_id)
    assert version["processing_status"] == "indexed"
    assert version["ocr_quality_score"] >= 0.65 and version["low_ocr_quality"] is False
    assert version["ai_eligible"] is True
    policy = _policy(client, fixture, document_id)
    assert policy["ai_retrieval_allowed"] is True and policy["reasons"] == []
    assert all(
        policy[key] is True
        for key in (
            "portal_share_allowed",
            "export_allowed",
            "notification_content_allowed",
        )
    )
    authorized = client.post(
        f"/api/ip/documents/{document_id}/authorize-action",
        headers=fixture.headers,
        json={"action": "ai_retrieval"},
    )
    assert authorized.status_code == 200, authorized.text
    return {
        "version_id": version_id,
        "policy": policy,
        "confidentiality": document["confidentiality"],
        "is_privileged": document["is_privileged"],
    }


def _complete_worker(engine, version_id, job_id, content):
    with Session(engine) as probe:
        job = probe.get(DocumentProcessingJob, job_id)
        assert job.attachment_id == version_id and job.target_type == "ip_document_version"
        assert job.status == "queued" and job.no_paid_providers is True
        worker_probe_pid = probe.scalar(text("SELECT pg_backend_pid()"))
    assert document_jobs.run_document_processing_job(job_id) is True
    with Session(engine) as check:
        version = check.get(IpDocumentVersion, version_id)
        job = check.get(DocumentProcessingJob, job_id)
        assert version.processing_status == "indexed"
        assert version.extracted_text == content.decode("ascii")
        assert version.extracted_char_count == len(content)
        assert version.sha256_hex == sha256(content).hexdigest()
        assert version.ocr_quality_score is not None
        assert (job.status, job.processed_char_count, job.error_message, job.attempt_count) == (
            "completed",
            len(content),
            None,
            1,
        )
        assert job.no_paid_providers is True
        return {
            "worker_probe_pid": worker_probe_pid,
            "worker_committed": True,
            "stored_quality": version.ocr_quality_score,
            "stored_count": len(content),
        }


def _upload_request(client, fixture, content):
    return _upload(
        client,
        fixture.headers,
        filename="snapshot.txt",
        content=content,
        docket_id=fixture.docket_id,
    )


def _new_version_request(client, fixture, document_id, content):
    return client.post(
        f"/api/ip/documents/{document_id}/new-version",
        headers=fixture.headers,
        data={
            "metadata_json": json.dumps(
                {
                    "expected_current_version": 1,
                    "client_code": "ACME",
                    "asset_type": "Trademark",
                    "mark": "ASTER",
                    "jurisdiction": "IN",
                    "application_no": "12345",
                    "document_date": "2026-08-09",
                }
            )
        },
        files={"upload": ("second-snapshot.txt", content, "text/plain")},
    )


def _prepare_previous(client, engine, fixture):
    created = _upload_request(client, fixture, PREVIOUS_BODY)
    document = created["document"]
    version = document["versions"][0]
    _complete_worker(engine, version["id"], created["processing_job"]["id"], PREVIOUS_BODY)
    positive = _assert_positive(client, fixture, document["id"], version["id"])
    fixture.dispatched.clear()
    return document["id"], positive


def _emit(record_property, label, evidence):
    print(label + " " + json.dumps(evidence), flush=True)
    record_property(label.lower(), json.dumps(evidence))


@pytest.mark.parametrize(
    ("generation", "content"),
    [
        pytest.param(1, BODY.encode("ascii"), id="first-normal"),
        pytest.param(2, BODY.encode("ascii"), id="second-normal"),
        pytest.param(2, b"x", id="second-sparse-positive-to-low"),
    ],
)
def test_http_ip_version_job_snapshot_and_fresh_quality(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    record_property,
    generation,
    content,
):
    client, engine = isolated_postgres_client, http_pg_engine
    fixture = _seed(client, engine, monkeypatch)
    positive = None
    if generation == 2:
        document_id, positive = _prepare_previous(client, engine, fixture)
        response = _new_version_request(client, fixture, document_id, content)
        assert response.status_code == 200, response.text
        created = response.json()
    else:
        created = _upload_request(client, fixture, content)
        document_id = created["document"]["id"]
    job_id = created["processing_job"]["id"]
    version_id = created["processing_job"]["attachment_id"]
    before_document = _get(client, fixture, document_id)
    before = _snapshot(_version(before_document, version_id))
    assert before["processing_status"] == "pending" and before["extracted_char_count"] == 0
    assert before["ocr_quality_score"] is None
    entered, release = Event(), Event()
    boundary = {}
    original = ip_document_workflow.load_latest_processing_jobs

    def paused(session, *, company_id, target_type, attachment_ids):
        assert company_id == fixture.company_id
        if version_id in attachment_ids and not entered.is_set():
            cached = next(
                row
                for row in session.identity_map.values()
                if isinstance(row, IpDocumentVersion) and row.id == version_id
            )
            boundary["cached_source"] = [
                cached.processing_status,
                cached.extracted_char_count,
                cached.ocr_quality_score,
            ]
            boundary["reader_pid"] = session.scalar(text("SELECT pg_backend_pid()"))
            boundary["isolation"] = session.scalar(text("SHOW transaction_isolation"))
            assert boundary["cached_source"] == ["pending", 0, None]
            assert boundary["isolation"] == "read committed"
            entered.set()
            assert release.wait(20), "IP GET worker commit barrier was not released"
        return original(
            session,
            company_id=company_id,
            target_type=target_type,
            attachment_ids=attachment_ids,
        )

    monkeypatch.setattr(ip_document_workflow, "load_latest_processing_jobs", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_get, client, fixture, document_id)
        try:
            wait_for_processing_barrier(
                entered, pending, "IP GET did not materialize the target version"
            )
            boundary.update(_complete_worker(engine, version_id, job_id, content))
            assert boundary["reader_pid"] != boundary["worker_probe_pid"]
        finally:
            release.set()
        raced_document = pending.result(20)
    monkeypatch.setattr(ip_document_workflow, "load_latest_processing_jobs", original)
    fresh_document = _get(client, fixture, document_id)
    raced = _snapshot(_version(raced_document, version_id))
    fresh = _snapshot(_version(fresh_document, version_id))
    assert raced == fresh
    assert raced["id"] == version_id and raced["version"] == generation
    assert raced["processing_status"] == "indexed"
    assert raced["extracted_char_count"] == len(content)
    assert raced["latest_processing_job"]["id"] == job_id
    assert raced["latest_processing_job"]["status"] == "completed"
    assert raced["ocr_quality_score"] == boundary["stored_quality"]
    policy = _policy(client, fixture, document_id)
    if content == b"x":
        assert positive is not None and positive["policy"]["ai_retrieval_allowed"] is True
        assert raced["ocr_quality_score"] < 0.65 and raced["low_ocr_quality"] is True
        assert raced["ai_eligible"] is False
        assert fresh_document["confidentiality"] == positive["confidentiality"] == "internal"
        assert fresh_document["is_privileged"] == positive["is_privileged"] is False
        assert policy == {
            **positive["policy"],
            "ai_retrieval_allowed": False,
            "reasons": [QUALITY_REASON],
        }
        denied = client.post(
            f"/api/ip/documents/{document_id}/authorize-action",
            headers=fixture.headers,
            json={"action": "ai_retrieval"},
        )
        assert denied.status_code == 403, denied.text
        problem = denied.json()
        assert problem["status"] == 403 and problem["code"] == "ip_document_policy_denied"
        assert problem["action"] == "ai_retrieval" and problem["reasons"] == [QUALITY_REASON]
        assert isinstance(problem["detail"], str)
        assert denied.headers["content-type"].startswith("application/problem+json")
    else:
        assert len(content) == 2839
        assert raced["ocr_quality_score"] >= 0.65 and raced["ai_eligible"] is True
    for previous in before_document["versions"]:
        if previous["id"] != version_id:
            assert _version(raced_document, previous["id"]) == previous
    _emit(
        record_property,
        "IP_CONTROLLED_SNAPSHOT",
        {
            "before": before,
            "raced": raced,
            "fresh": fresh,
            "boundary": boundary,
            "positive_predecessor": positive,
            "final_policy": policy,
            "original_production_tuple_field": "unknown; no production-cause attribution",
        },
    )


@pytest.mark.parametrize("operation", ["upload", "new_version"])
def test_http_ip_upload_receipts_remain_one_frozen_version_snapshot(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    record_property,
    operation,
):
    client, engine = isolated_postgres_client, http_pg_engine
    fixture = _seed(client, engine, monkeypatch)
    document_id = None
    if operation == "new_version":
        document_id, _ = _prepare_previous(client, engine, fixture)
    entered, release = Event(), Event()
    boundary = {}
    original = ip_document_workflow._serialize_document

    def paused(session, *, context, document):
        record = original(session, context=context, document=document)
        version = next(row for row in record.versions if row.version == record.current_version)
        assert version.latest_processing_job is not None
        assert version.processing_status == "pending" and version.extracted_char_count == 0
        assert version.latest_processing_job.status == "queued"
        if operation == "new_version":
            # Keep real DTO rows intact but make positional selection incorrect.
            record = record.model_copy(update={"versions": list(reversed(record.versions))})
            assert record.versions[0].id != version.id
        boundary["frozen_document"] = record.model_dump(mode="json")
        boundary["version_id"] = version.id
        boundary["admitted_job_id"] = version.latest_processing_job.id
        boundary["reader_pid"] = session.scalar(text("SELECT pg_backend_pid()"))
        entered.set()
        assert release.wait(20), "IP response DTO barrier was not released"
        return record

    monkeypatch.setattr(ip_document_workflow, "_serialize_document", paused)

    def request():
        if operation == "upload":
            return _upload_request(client, fixture, BODY.encode("ascii"))
        response = _new_version_request(client, fixture, document_id, BODY.encode("ascii"))
        assert response.status_code == 200, response.text
        return response.json()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(request)
        try:
            wait_for_processing_barrier(
                entered, pending, "IP upload did not return its version DTO"
            )
            boundary.update(
                _complete_worker(
                    engine,
                    boundary["version_id"],
                    boundary["admitted_job_id"],
                    BODY.encode("ascii"),
                )
            )
            assert boundary["reader_pid"] != boundary["worker_probe_pid"]
        finally:
            release.set()
        result = pending.result(20)
    monkeypatch.setattr(ip_document_workflow, "_serialize_document", original)
    version_id, job_id = boundary["version_id"], boundary["admitted_job_id"]
    nested = _version(result["document"], version_id)
    assert result["document"] == boundary["frozen_document"]
    assert result["processing_job"] == nested["latest_processing_job"]
    assert result["processing_job"]["id"] == job_id
    assert result["processing_job"]["attachment_id"] == version_id
    assert result["processing_job"]["status"] == "queued"
    assert fixture.dispatched == [job_id]
    fresh = _version(_get(client, fixture, result["document"]["id"]), version_id)
    assert fresh["processing_status"] == "indexed" and fresh["extracted_char_count"] == 2839
    assert fresh["latest_processing_job"]["id"] == job_id
    assert fresh["latest_processing_job"]["status"] == "completed"
    _emit(
        record_property,
        "IP_FROZEN_RESPONSE_SNAPSHOT",
        {
            "operation": operation,
            "boundary": boundary,
            "returned_version": nested,
            "returned_top_job": result["processing_job"],
            "dispatched_job_ids": fixture.dispatched,
            "fresh_version": fresh,
        },
    )


@pytest.mark.parametrize("operation", ["upload", "new_version"])
def test_http_ip_upload_missing_exact_version_fails_closed_without_dispatch(
    isolated_postgres_client,
    http_pg_engine,
    monkeypatch,
    record_property,
    operation,
):
    client, engine = isolated_postgres_client, http_pg_engine
    fixture = _seed(client, engine, monkeypatch)
    document_id = None
    if operation == "new_version":
        document_id, _ = _prepare_previous(client, engine, fixture)
    observed = {}
    original = ip_document_workflow._serialize_document

    def omit_current(session, *, context, document):
        record = original(session, context=context, document=document)
        version = next(row for row in record.versions if row.version == record.current_version)
        observed.update(
            document_id=record.id, version_id=version.id, job_id=version.latest_processing_job.id
        )
        return record.model_copy(
            update={
                "versions": [row for row in record.versions if row.id != version.id],
            }
        )

    monkeypatch.setattr(ip_document_workflow, "_serialize_document", omit_current)
    if operation == "upload":
        response = client.post(
            "/api/ip/documents/upload",
            headers=fixture.headers,
            data={
                "metadata_json": json.dumps(
                    {
                        "taxonomy_key": "evidence",
                        "title": "Native missing-version seam",
                        "client_code": "ACME",
                        "asset_type": "Trademark",
                        "mark": "ASTER",
                        "jurisdiction": "IN",
                        "application_no": "12345",
                        "document_date": "2026-08-09",
                        "links": [{"target_type": "docket", "target_id": fixture.docket_id}],
                    }
                )
            },
            files={"upload": ("missing-exact-version.txt", BODY.encode("ascii"), "text/plain")},
        )
    else:
        response = _new_version_request(client, fixture, document_id, BODY.encode("ascii"))
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Document processing state changed. Reload this workspace."
    assert fixture.dispatched == []
    with Session(engine) as check:
        source = check.get(IpDocumentVersion, observed["version_id"])
        job = check.get(DocumentProcessingJob, observed["job_id"])
        assert source.processing_status == "pending" and source.extracted_char_count == 0
        assert job.status == "queued" and job.no_paid_providers is True
        assert job.attachment_id == source.id and job.company_id == source.company_id
    _emit(
        record_property,
        "IP_MISSING_EXACT_VERSION",
        {
            "operation": operation,
            "persisted": observed,
            "status": response.status_code,
            "dispatched_job_ids": fixture.dispatched,
        },
    )
