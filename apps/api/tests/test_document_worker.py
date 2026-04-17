from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    ContractAttachment,
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingTargetType,
    MatterAttachment,
    MatterCourtSyncJob,
    MatterCourtSyncJobStatus,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.court_sync_jobs import (
    drain_matter_court_sync_jobs,
    recover_stale_matter_court_sync_jobs,
)
from caseops_api.services.document_jobs import (
    drain_document_processing_jobs,
    enqueue_scheduled_document_reprocessing,
    recover_stale_document_processing_jobs,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def test_recover_stale_processing_jobs_requeues_stuck_work(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Stale queue recovery",
            "matter_code": "WORKER-2026-001",
            "practice_area": "Litigation",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("worker.txt", b"Initial worker content", "text/plain")},
    )
    attachment_id = upload_response.json()["id"]

    session_factory = get_session_factory()
    with session_factory() as session:
        attachment = session.scalar(
            select(MatterAttachment).where(MatterAttachment.id == attachment_id)
        )
        assert attachment is not None
        stale_job = DocumentProcessingJob(
            company_id=attachment.matter.company_id,
            requested_by_membership_id=attachment.uploaded_by_membership_id,
            target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
            attachment_id=attachment.id,
            action=DocumentProcessingAction.RETRY,
            status=DocumentProcessingJobStatus.PROCESSING,
            attempt_count=1,
            queued_at=utcnow() - timedelta(minutes=30),
            started_at=utcnow() - timedelta(minutes=20),
        )
        session.add(stale_job)
        session.commit()
        stale_job_id = stale_job.id

    recovered = recover_stale_document_processing_jobs(stale_after_minutes=5)
    assert recovered >= 1

    with session_factory() as session:
        job = session.scalar(
            select(DocumentProcessingJob).where(DocumentProcessingJob.id == stale_job_id)
        )
        assert job is not None
        assert job.status == DocumentProcessingJobStatus.QUEUED
        assert job.started_at is None


def test_scheduled_reprocessing_retry_can_be_drained_by_worker(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_pdf_text",
        lambda path: "",
    )
    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_scanned_pdf_text",
        lambda path: "",
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Scheduled retry matter",
            "matter_code": "WORKER-2026-002",
            "practice_area": "Litigation",
            "forum_level": "lower_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    upload_response = client.post(
        f"/api/matters/{matter_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("scheduled.pdf", b"%PDF fake bytes", "application/pdf")},
    )
    attachment_id = upload_response.json()["id"]

    monkeypatch.setattr(
        "caseops_api.services.document_processing._extract_scanned_pdf_text",
        lambda path: "Recovered OCR text for the scheduled worker retry.",
    )

    queued = enqueue_scheduled_document_reprocessing(
        limit=10,
        retry_after_hours=0,
        reindex_after_hours=999999,
    )
    assert queued >= 1

    processed = drain_document_processing_jobs(limit=10)
    assert processed >= 1

    session_factory = get_session_factory()
    with session_factory() as session:
        attachment = session.scalar(
            select(MatterAttachment).where(MatterAttachment.id == attachment_id)
        )
        assert attachment is not None
        assert attachment.processing_status == "indexed"
        assert attachment.extracted_char_count > 0


def test_scheduled_reprocessing_can_queue_contract_reindex(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    contract_response = client.post(
        "/api/contracts/",
        headers=auth_headers(token),
        json={
            "title": "Scheduled contract reindex",
            "contract_code": "WORKER-CTR-2026-001",
            "contract_type": "MSA",
            "status": "under_review",
        },
    )
    contract_id = contract_response.json()["id"]

    upload_response = client.post(
        f"/api/contracts/{contract_id}/attachments",
        headers=auth_headers(token),
        files={"file": ("contract.txt", b"Termination clause and pricing schedule.", "text/plain")},
    )
    attachment_id = upload_response.json()["id"]

    session_factory = get_session_factory()
    with session_factory() as session:
        attachment = session.scalar(
            select(ContractAttachment).where(ContractAttachment.id == attachment_id)
        )
        assert attachment is not None
        attachment.processed_at = utcnow() - timedelta(days=10)
        session.add(attachment)
        session.commit()

    queued = enqueue_scheduled_document_reprocessing(
        limit=10,
        retry_after_hours=999999,
        reindex_after_hours=0,
    )
    assert queued >= 1

    with session_factory() as session:
        latest_job = session.scalar(
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.target_type
                == DocumentProcessingTargetType.CONTRACT_ATTACHMENT,
                DocumentProcessingJob.attachment_id == attachment_id,
                DocumentProcessingJob.action == DocumentProcessingAction.REINDEX,
            )
            .order_by(DocumentProcessingJob.queued_at.desc())
        )
        assert latest_job is not None
        assert latest_job.status == DocumentProcessingJobStatus.QUEUED


def test_live_court_sync_jobs_can_be_recovered_and_drained(
    client: TestClient,
    monkeypatch,
) -> None:
    def fake_fetch_text(url: str) -> tuple[str, str]:
        if "cause-lists/cause-list" in url:
            return (
                """
                <html>
                  <body>
                    <div>1 ADVANCE CAUSE LIST 17-04-2026</div>
                    <a href="/files/2026-04/cause-list/advance.pdf">Download</a>
                  </body>
                </html>
                """,
                url,
            )
        return (
            """
            <html>
              <body>
                <a href="/judgments/latest-judgment.pdf">
                  North Arc Projects vs State Judgment date 16.04.2026
                </a>
              </body>
            </html>
            """,
            url,
        )

    monkeypatch.setattr("caseops_api.services.court_sync_sources._fetch_text", fake_fetch_text)
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._fetch_bytes",
        lambda url: (
            b"%PDF fake bytes",
            "https://delhihighcourt.nic.in/files/2026-04/cause-list/advance.pdf",
        ),
    )
    monkeypatch.setattr(
        "caseops_api.services.court_sync_sources._extract_pdf_text_from_bytes",
        lambda data: (
            "North Arc Projects vs State before Justice Mehta in Court No. 32 "
            "Item 18 on 2026-04-17."
        ),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "North Arc Projects vs State",
            "matter_code": "WORKER-COURT-2026-001",
            "client_name": "North Arc Projects",
            "opposing_party": "State",
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "status": "active",
            "court_name": "Delhi High Court",
            "judge_name": "Justice Mehta",
        },
    )
    matter_id = matter_response.json()["id"]

    pull_response = client.post(
        f"/api/matters/{matter_id}/court-sync/pull",
        headers=auth_headers(token),
        json={"source": "delhi_high_court_live", "source_reference": "North Arc Projects"},
    )
    job_id = pull_response.json()["id"]

    session_factory = get_session_factory()
    with session_factory() as session:
        job = session.scalar(select(MatterCourtSyncJob).where(MatterCourtSyncJob.id == job_id))
        assert job is not None
        job.status = MatterCourtSyncJobStatus.PROCESSING
        job.started_at = utcnow() - timedelta(minutes=20)
        session.add(job)
        session.commit()

    recovered = recover_stale_matter_court_sync_jobs(stale_after_minutes=5)
    assert recovered >= 1

    processed = drain_matter_court_sync_jobs(limit=5)
    assert processed >= 1

    with session_factory() as session:
        job = session.scalar(select(MatterCourtSyncJob).where(MatterCourtSyncJob.id == job_id))
        assert job is not None
        assert job.status == MatterCourtSyncJobStatus.COMPLETED
        assert job.imported_cause_list_count >= 1
