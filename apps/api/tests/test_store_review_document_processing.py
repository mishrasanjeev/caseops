from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_HEADER,
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
)
from caseops_api.core.settings import Settings, get_settings
from caseops_api.db.models import DocumentProcessingJob, MatterAttachment
from caseops_api.db.session import get_session_factory
from caseops_api.services import document_dispatch, embeddings, virus_scan
from caseops_api.services.document_jobs import run_document_processing_job
from tests.test_auth_company import auth_headers

REVIEW_COMPANY_SETTING = "CASEOPS_STORE_REVIEW_DOCUMENT_NO_PAID_COMPANY_ID"
CLEAN = b"Synthetic source file for store review. No client data."


def _tenant_matter(client: TestClient, slug: str) -> tuple[str, dict[str, str], str]:
    created = client.post("/api/bootstrap/company", json={
        "company_name": "Synthetic document test",
        "company_slug": slug,
        "company_type": "law_firm",
        "owner_full_name": "Synthetic owner",
        "owner_email": f"{slug}@example.com",
        "owner_password": "CaseOpsFixture123!",
    })
    assert created.status_code == 200, created.text
    owner = created.json()
    headers = auth_headers(owner["access_token"])
    matter = client.post("/api/matters/", headers=headers, json={
        "title": "Synthetic review matter",
        "matter_code": "REVIEW-001",
        "practice_area": "Commercial advisory",
        "forum_level": "advisory",
        "status": "intake",
    })
    assert matter.status_code == 200, matter.text
    return owner["company"]["id"], headers, matter.json()["id"]


def _upload(client, matter_id, headers, content=CLEAN):
    return client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=headers,
        data={"expected_lifecycle_version": "0"},
        files={"file": ("sample.txt", content, "text/plain")},
    )


@pytest.mark.parametrize(
    ("configure", "use_review_company", "marked", "expected"),
    [
        pytest.param(True, True, False, True, id="review-company-unmarked"),
        pytest.param(True, False, False, False, id="different-qa-company-unmarked"),
        pytest.param(True, False, True, True, id="ordinary-company-marked"),
        pytest.param(False, True, False, False, id="disabled-by-default"),
    ],
)
def test_matter_upload_persists_review_provider_isolation(
    client, monkeypatch, configure, use_review_company, marked, expected,
):
    review = _tenant_matter(client, "store-review-qa")
    ordinary = _tenant_matter(client, "different-store-review-qa")
    company_id, headers, matter_id = review if use_review_company else ordinary
    outside_matter_id = ordinary[2] if use_review_company else review[2]
    if marked:
        headers = {**headers, NO_PAID_PROVIDERS_HEADER: NO_PAID_PROVIDERS_VALUE}

    scanned = []
    wakes = []
    would_construct_voyage = []

    def scan(path):
        content = Path(path).read_bytes()
        scanned.append(content)
        if content == b"Synthetic rejected scan result":
            return virus_scan.ScanResult("infected", "TestSignature")
        return virus_scan.ScanResult("clean", None)

    async def wake(**kwargs):
        wakes.append(kwargs["job"])
        return True

    def offline_voyage(*, model, dimensions, **_):
        would_construct_voyage.append(model)
        return embeddings.MockProvider(model=model, dimensions=dimensions)

    with monkeypatch.context() as env:
        env.setenv("CASEOPS_DOCUMENT_PROCESSING_DISPATCH_MODE", "cloud_run_job")
        env.setenv("CASEOPS_GCP_PROJECT_ID", "caseops-test-fixture")
        env.setenv("CASEOPS_CLAMAV_REQUIRED", "true")
        env.setenv("CASEOPS_EMBEDDING_PROVIDER", "voyage")
        env.setenv("CASEOPS_EMBEDDING_MODEL", "voyage-4-large")
        env.setenv("CASEOPS_EMBEDDING_API_KEY", "offline-test")
        if configure:
            env.setenv(REVIEW_COMPANY_SETTING, review[0])
        else:
            env.delenv(REVIEW_COMPANY_SETTING, raising=False)
        env.setattr(virus_scan, "scan_file_for_viruses", scan)
        env.setattr(document_dispatch, "_wake_cloud_run_queue", wake)
        env.setattr(embeddings, "VoyageProvider", offline_voyage)
        get_settings.cache_clear()
        try:
            outside = _upload(client, outside_matter_id, headers)
            assert outside.status_code == 404
            infected = b"Synthetic rejected scan result"
            rejected = _upload(client, matter_id, headers, infected)
            assert rejected.status_code == 400
            assert "TestSignature" in rejected.json()["detail"]
            admitted = _upload(client, matter_id, headers)
            assert admitted.status_code == 200, admitted.text
            attachment = admitted.json()
            assert attachment["processing_status"] == "pending"
            original_job_id = attachment["latest_job"]["id"]
            assert attachment["latest_job"]["status"] == "queued"
            assert scanned == [infected, CLEAN]
            assert wakes == ["caseops-document-processing"]

            factory = get_session_factory()
            with factory() as check:
                jobs = check.scalars(select(DocumentProcessingJob)).all()
                assert [(job.id, job.company_id, job.no_paid_providers) for job in jobs] == [
                    (original_job_id, company_id, expected),
                ]

            # A retry is a separate admission through the real route and needs
            # its own receipt. No inline background worker has run yet.
            retry = client.post(
                f"/api/matters/{matter_id}/attachments/{attachment['id']}/retry",
                headers=headers,
            )
            assert retry.status_code == 200, retry.text
            retry_job_id = retry.json()["latest_job"]["id"]
            assert retry_job_id != original_job_id
            assert retry.json()["latest_job"]["action"] == "retry"
            assert wakes == ["caseops-document-processing", "caseops-document-processing"]
            with factory() as check:
                retry_job = check.get(DocumentProcessingJob, retry_job_id)
                assert retry_job.company_id == company_id
                assert retry_job.no_paid_providers is expected

            # A fresh worker needs the committed bit, even when its environment
            # does not carry the API's exact company setting or request marker.
            env.delenv(REVIEW_COMPANY_SETTING, raising=False)
            get_settings.cache_clear()
            assert not paid_providers_blocked_for_request()
            for job_id in (original_job_id, retry_job_id):
                processed = run_document_processing_job(job_id)
                assert processed
                assert not paid_providers_blocked_for_request()

            assert would_construct_voyage == ([] if expected else ["voyage-4-large"] * 2)
            with factory() as check:
                saved = check.get(MatterAttachment, attachment["id"])
                assert saved.processing_status == "indexed"
                assert [chunk.embedding_model for chunk in saved.chunks] == [
                    "caseops-automated-test-embed" if expected else "voyage-4-large",
                ]
                for job_id in (original_job_id, retry_job_id):
                    job = check.get(DocumentProcessingJob, job_id)
                    assert (job.status, job.attempt_count, job.no_paid_providers) == (
                        "completed", 1, expected,
                    )
            download = client.get(
                f"/api/matters/{matter_id}/attachments/{attachment['id']}/download",
                headers=headers,
            )
            assert download.status_code == 200
            assert download.content == CLEAN
            assert download.headers["cache-control"] == "private, no-store, max-age=0"
        finally:
            get_settings.cache_clear()


def test_store_review_document_scope_refuses_an_invalid_company_uuid(monkeypatch):
    monkeypatch.setenv(REVIEW_COMPANY_SETTING, "store-review-qa")
    with pytest.raises(ValidationError, match="store_review_document_no_paid_company_id"):
        Settings(_env_file=None)
