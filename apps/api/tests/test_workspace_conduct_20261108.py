"""MOB-39-CONDUCT-01/02. Real authenticated native note and upload fences."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from caseops_api.core.automated_test_context import NO_PAID_PROVIDERS_HEADER
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    DocumentProcessingJob,
    MatterAttachment,
    MatterNote,
    WorkspaceConductAcceptance,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import (
    document_dispatch,
    embeddings,
    matters,
    virus_scan,
    workspace_conduct,
)
from caseops_api.services.document_jobs import run_document_processing_job
from tests.test_native_auth_20261024 import _browser, _device, _headers

PATH = "/api/account/workspace-conduct"
VERSION = "2026-11-08"
POLICY = "https://caseops.ai/workspace-use"
CONTENT = b"Synthetic CaseOps review document."


def _matter(client, headers):
    response = client.post("/api/matters/", headers=headers, json={
        "title": "Synthetic conduct test matter",
        "matter_code": "CONDUCT-01",
        "practice_area": "Commercial advisory",
        "forum_level": "advisory",
        "status": "intake",
    })
    assert response.status_code == 200, response.text
    return response.json()


def _upload(client, headers, matter_id, version, content=CONTENT):
    return client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=headers,
        data={"expected_lifecycle_version": str(version)},
        files={"file": ("conduct-fixture.txt", content, "text/plain")},
    )


def _note(client, headers, matter_id, version, body="Synthetic native note"):
    return client.post(
        f"/api/matters/{matter_id}/notes", headers=headers,
        json={"body": body, "expected_lifecycle_version": version},
    )


def _accept(client, headers, version=VERSION):
    return client.post(f"{PATH}/accept", headers=headers, json={"version": version})


def test_native_upload_and_web_reprocessing_skip_external_embedding_provider(client, monkeypatch):
    _, browser = _browser(client)
    native = _headers(_device(client, browser))
    matter = _matter(client, browser)
    matter_id, version = matter["id"], matter["lifecycle_version"]
    seen = []
    mock = embeddings.MockProvider()

    def provider():
        seen.append("embedding-entry")
        return mock

    monkeypatch.setattr(embeddings, "build_provider", provider)
    assert _accept(client, native).status_code == 200
    native_file = _upload(client, native, matter_id, version)
    assert native_file.status_code == 200, native_file.text
    native_id = native_file.json()["id"]
    assert seen == [], "native upload invoked the configured embedding provider"
    for action in ("retry", "reindex"):
        result = client.post(
            f"/api/matters/{matter_id}/attachments/{native_id}/{action}", headers=browser,
        )
        assert result.status_code == 200, result.text
        assert seen == [], f"browser {action} invoked the provider for a native upload"
    download = client.get(
        f"/api/matters/{matter_id}/attachments/{native_id}/download", headers=native,
    )
    assert download.status_code == 200 and download.content == CONTENT

    web_file = _upload(
        client, browser, matter_id, version, content=b"Separate synthetic web content.",
    )
    assert web_file.status_code == 200, web_file.text
    assert seen == ["embedding-entry"]
    with get_session_factory()() as session:
        native_row = session.get(MatterAttachment, native_id)
        assert native_row.native_local_processing_only is True
        web_row = session.get(MatterAttachment, web_file.json()["id"])
        assert web_row.native_local_processing_only is False
        assert native_row.extracted_text == CONTENT.decode()
        assert [chunk.content for chunk in native_row.chunks] == [CONTENT.decode()]
        jobs = session.scalars(
            select(DocumentProcessingJob).where(DocumentProcessingJob.attachment_id == native_id),
        ).all()
        assert len(jobs) == 3 and all(job.no_paid_providers for job in jobs)
        assert {job.status for job in jobs} == {"completed"}


def test_store_review_workspace_composes_with_native_document_processing(client, monkeypatch):
    auth, browser = _browser(client)
    native = _headers(_device(client, browser))
    del client.headers[NO_PAID_PROVIDERS_HEADER]
    del client.headers["X-CaseOps-Client"]
    del browser[NO_PAID_PROVIDERS_HEADER]
    accepted = _accept(client, native)
    assert accepted.status_code == 200, accepted.text
    matter = _matter(client, browser)
    matter_id, version = matter["id"], matter["lifecycle_version"]

    review_setting = "CASEOPS_STORE_REVIEW_DOCUMENT_NO_PAID_COMPANY_ID"
    monkeypatch.setenv(review_setting, auth["company"]["id"])
    monkeypatch.setenv("CASEOPS_DOCUMENT_PROCESSING_DISPATCH_MODE", "cloud_run_job")
    monkeypatch.setenv("CASEOPS_GCP_PROJECT_ID", "caseops-test-fixture")
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "voyage")
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "offline-test")
    get_settings.cache_clear()
    paid_constructions = []

    def offline_voyage(*, model, dimensions, **_):
        paid_constructions.append(model)
        return embeddings.MockProvider(model=model, dimensions=dimensions)

    async def wake(**_):
        return True

    monkeypatch.setattr(embeddings, "VoyageProvider", offline_voyage)
    monkeypatch.setattr(document_dispatch, "_wake_cloud_run_queue", wake)
    queued = {}
    for is_native, headers, content in (
        (True, native, CONTENT),
        (False, browser, b"Synthetic unmarked browser review document."),
    ):
        uploaded = _upload(client, headers, matter_id, version, content)
        assert uploaded.status_code == 200, uploaded.text
        attachment = uploaded.json()
        attachment_id = attachment["id"]
        jobs = [attachment["latest_job"]["id"]]
        for action in ("retry", "reindex"):
            response = client.post(
                f"/api/matters/{matter_id}/attachments/{attachment_id}/{action}", headers=browser,
            )
            assert response.status_code == 200, response.text
            job = response.json()["latest_job"]
            assert job["action"] == action and job["status"] == "queued"
            jobs.append(job["id"])
        assert len(set(jobs)) == 3
        queued[attachment_id] = is_native, content, jobs

    monkeypatch.delenv(review_setting)
    get_settings.cache_clear()
    factory = get_session_factory()
    for attachment_id, (is_native, content, jobs) in queued.items():
        for job_id in jobs:
            processed = run_document_processing_job(job_id)
            assert processed
        with factory() as session:
            attachment = session.get(MatterAttachment, attachment_id)
            assert attachment.native_local_processing_only is is_native
            assert attachment.processing_status == "indexed"
            assert [chunk.content for chunk in attachment.chunks] == [content.decode()]
            assert [chunk.embedding_model for chunk in attachment.chunks] == [
                None if is_native else "caseops-automated-test-embed",
            ]
            for job_id in jobs:
                job = session.get(DocumentProcessingJob, job_id)
                assert (job.status, job.attempt_count, job.no_paid_providers) == (
                    "completed", 1, True,
                )
    assert paid_constructions == []


def test_native_note_and_upload_require_current_rules_and_preserve_web_scanner(client, monkeypatch):
    auth, browser = _browser(client)
    device = _device(client, browser)
    native = _headers(device)
    matter = _matter(client, browser)
    matter_id, version = matter["id"], matter["lifecycle_version"]
    retained = []

    def scan(path):
        data = Path(path).read_bytes()
        retained.append(data)
        return (
            virus_scan.ScanResult("infected", "SyntheticSignature")
            if data == b"synthetic denied" else virus_scan.ScanResult("clean", None)
        )

    monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
    with get_session_factory()() as session:
        session.add(WorkspaceConductAcceptance(
            company_id=auth["company"]["id"], membership_id=auth["membership"]["id"],
            version="2026-11-07", accepted_at=datetime.now(UTC),
        ))
        session.commit()

    before = client.get(PATH, headers=native)
    assert before.status_code == 200 and before.headers["cache-control"] == "no-store"
    assert before.json() == {"version": VERSION, "policy_url": POLICY, "accepted_at": None}
    read = client.get(f"/api/matters/{matter_id}/workspace", headers=native)
    assert read.status_code == 200 and read.json()["matter"]["id"] == matter_id
    stale = _accept(client, native, version="2026-11-07")
    assert stale.status_code == 409
    assert stale.json()["type"] == "workspace_conduct_version_changed"
    forged = client.post(
        f"{PATH}/accept", headers=native, json={"version": VERSION, "company_id": matter_id},
    )
    assert forged.status_code == 422
    assert _accept(client, browser).status_code == 403

    for response in (_note(client, native, matter_id, version),
                     _upload(client, native, matter_id, version)):
        assert response.status_code == 403
        assert response.json()["type"] == "workspace_conduct_acceptance_required"
    assert retained == []
    with get_session_factory()() as session:
        assert session.scalars(select(MatterNote)).all() == []
        assert session.scalars(select(MatterAttachment)).all() == []
        assert session.scalars(select(DocumentProcessingJob)).all() == []
        assert [row.version for row in session.scalars(select(WorkspaceConductAcceptance))] == [
            "2026-11-07",
        ]

    legacy = _note(client, browser, matter_id, version, body="Existing web note")
    assert legacy.status_code == 200, legacy.text
    web_upload = _upload(client, browser, matter_id, version)
    assert web_upload.status_code == 200, web_upload.text
    receipt = _accept(client, native)
    assert receipt.status_code == 200, receipt.text
    assert receipt.headers["cache-control"] == "no-store"
    assert receipt.json()["accepted_at"].endswith("Z")
    assert _accept(client, native).content == receipt.content
    assert client.get(PATH, headers=native).content == receipt.content
    stale_note = _note(client, native, matter_id, version + 1)
    assert stale_note.status_code == 409
    created = _note(client, native, matter_id, version)
    assert created.status_code == 200
    assert created.json()["author_membership_id"] == auth["membership"]["id"]

    blocked_scan = _upload(client, native, matter_id, version, content=b"synthetic denied")
    assert blocked_scan.status_code == 400 and "SyntheticSignature" in blocked_scan.json()["detail"]
    file_response = _upload(client, native, matter_id, version)
    assert file_response.status_code == 200, file_response.text
    attachment = file_response.json()
    assert attachment["uploaded_by_membership_id"] == auth["membership"]["id"]
    download = client.get(
        f"/api/matters/{matter_id}/attachments/{attachment['id']}/download", headers=native,
    )
    assert download.status_code == 200 and download.content == CONTENT
    assert retained == [CONTENT, b"synthetic denied", CONTENT]
    with get_session_factory()() as session:
        receipts = session.scalars(select(WorkspaceConductAcceptance)).all()
        assert {row.version for row in receipts} == {VERSION, "2026-11-07"}
        assert len(receipts) == 2
        assert len(session.scalars(select(MatterAttachment)).all()) == 2


def test_receipt_is_bound_to_authenticated_membership_and_tenant(client):
    auth, browser = _browser(client)
    owner = _headers(_device(client, browser))
    receipt = _accept(client, owner)
    assert receipt.status_code == 200
    new_member = client.post("/api/companies/current/users", headers=browser, json={
        "full_name": "Synthetic second member", "email": "conduct-member@example.com",
        "password": "ConductMember123!", "role": "member",
    })
    assert new_member.status_code == 200, new_member.text
    logged_in = client.post("/api/auth/login", json={
        "company_slug": auth["company"]["slug"],
        "email": "conduct-member@example.com", "password": "ConductMember123!",
    })
    assert logged_in.status_code == 200, logged_in.text
    csrf = client.cookies.get("caseops_csrf")
    client.cookies.clear()
    other = _headers(_device(client, {
        "Cookie": f"caseops_session={logged_in.json()['access_token']}; caseops_csrf={csrf}",
        "X-CSRF-Token": csrf,
    }))
    assert client.get(PATH, headers=other).json()["accepted_at"] is None

    # Parent tenant + membership mismatch is rejected by the migrated schema,
    # independently of application authorization and model-created DDL.
    foreign = client.post("/api/bootstrap/company", json={
        "company_name": "Synthetic second workspace", "company_slug": "other-conduct-qa",
        "company_type": "law_firm", "owner_full_name": "Synthetic owner",
        "owner_email": "other-conduct-qa@example.com", "owner_password": "OtherConduct123!",
    })
    assert foreign.status_code == 200
    client.cookies.clear()
    with get_session_factory()() as session:
        session.add(WorkspaceConductAcceptance(
            company_id=foreign.json()["company"]["id"], membership_id=auth["membership"]["id"],
            version=VERSION, accepted_at=datetime.now(UTC),
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
    assert _accept(client, other).status_code == 200
    with get_session_factory()() as session:
        rows = session.scalars(select(WorkspaceConductAcceptance)).all()
        assert {row.membership_id for row in rows} == {
            auth["membership"]["id"], new_member.json()["membership_id"],
        }


def test_acceptance_rechecks_membership_cutoff_after_request_authentication(client, monkeypatch):
    auth, browser = _browser(client)
    device = _device(client, browser)
    original = workspace_conduct.accept_current

    def stale(session, *, context, version):
        with get_session_factory()() as concurrent:
            row = concurrent.get(CompanyMembership, auth["membership"]["id"])
            row.sessions_valid_after = datetime.now(UTC)
            concurrent.commit()
        return original(session, context=context, version=version)

    monkeypatch.setattr(workspace_conduct, "accept_current", stale)
    denied = _accept(client, _headers(device))
    assert denied.status_code == 401, denied.text
    with get_session_factory()() as session:
        assert session.scalars(select(WorkspaceConductAcceptance)).all() == []


def test_upload_rechecks_native_membership_after_storage_and_cleans_owned_copy(client, monkeypatch):
    auth, browser = _browser(client)
    native = _headers(_device(client, browser))
    matter = _matter(client, browser)
    assert _accept(client, native).status_code == 200
    original_persist = matters.persist_matter_attachment
    original_delete = matters.delete_stored_document
    stored = []
    removed = []

    def persist(**kwargs):
        admitted = original_persist(**kwargs)
        stored.append(admitted.storage_key)
        with get_session_factory()() as concurrent:
            row = concurrent.get(CompanyMembership, auth["membership"]["id"])
            row.sessions_valid_after = datetime.now(UTC)
            concurrent.commit()
        return admitted

    def delete(storage_key):
        original_delete(storage_key)
        removed.append(storage_key)

    monkeypatch.setattr(matters, "persist_matter_attachment", persist)
    monkeypatch.setattr(matters, "delete_stored_document", delete)
    denied = _upload(client, native, matter["id"], matter["lifecycle_version"])
    assert denied.status_code == 401, denied.text
    assert len(stored) == 1 and removed == stored
    with get_session_factory()() as session:
        assert session.scalars(select(MatterAttachment)).all() == []
        assert session.scalars(select(DocumentProcessingJob)).all() == []
