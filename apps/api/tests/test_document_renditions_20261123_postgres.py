"""OCR & Translate on real PostgreSQL (EH-OCRT-02; FT-105, FT-109, NFT-025).

Proves the migration's partial unique index and that rendition jobs satisfy the
document execution-protocol trigger, which SQLite does not enforce.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from caseops_api.core.settings import get_settings
from caseops_api.db.document_rendition_models import MatterAttachmentRendition
from caseops_api.db.models import DocumentProcessingJob, MatterAttachment
from caseops_api.db.session import get_session_factory
from caseops_api.services import document_rendition_pipeline as pipeline
from caseops_api.services.document_jobs import run_document_processing_job
from caseops_api.services.google_translation import GoogleTranslationClient
from caseops_api.services.sarvam_document_ai import SarvamDocumentClient
from tests.test_document_renditions_20261123 import (
    HINDI_PAGE,
    FakeGoogle,
    FakeSarvam,
    _base,
    _latest,
    _pdf,
    _setup,
    _start,
    _upload,
    _verify_costs,
    _versions,
)
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture
def pg_providers(isolated_postgres_client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CASEOPS_OCR_PROVIDER", "none")
    monkeypatch.setenv("CASEOPS_SARVAM_DOCUMENT_AI_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_SARVAM_API_KEY", "test-sarvam-key")
    monkeypatch.setenv("CASEOPS_GOOGLE_TRANSLATION_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_GOOGLE_TRANSLATION_PROJECT_ID", "caseops-test")
    get_settings.cache_clear()
    sarvam, google = FakeSarvam(), FakeGoogle()
    monkeypatch.setattr(pipeline, "sarvam_client", lambda: (SarvamDocumentClient(
        api_key="test-sarvam-key", base_url="https://api.sarvam.ai", timeout_seconds=5,
        http=httpx.Client(transport=httpx.MockTransport(sarvam.handler)),
    ), True))
    monkeypatch.setattr(pipeline, "translation_client", lambda: (GoogleTranslationClient(
        project_id="caseops-test", location="us-central1",
        base_url="https://translate.googleapis.com", timeout_seconds=5,
        http=httpx.Client(transport=httpx.MockTransport(google.handler)),
        token_provider=lambda: "test-token",
    ), True))
    monkeypatch.setattr(pipeline, "_sleep", lambda _seconds: None)
    yield isolated_postgres_client, sarvam, google
    get_settings.cache_clear()


def test_ocr_then_translation_completes_under_the_execution_protocol(pg_providers) -> None:
    client, sarvam, google = pg_providers
    _verify_costs()
    _, token, matter_id = _setup(client, "PG-OCR-1")
    attachment_id = _upload(
        client, token, matter_id, "order.pdf", _pdf([HINDI_PAGE, None, HINDI_PAGE]),
    )
    assert _start(client, token, matter_id, attachment_id, "hi", "en").status_code == 202
    listing = _versions(client, token, matter_id, attachment_id)
    ocr, translation = _latest(listing, "ocr"), _latest(listing, "translation")
    assert ocr["status"] == "ocr_completed", (ocr["error_code"], ocr["error_message"])
    assert translation["status"] == "translation_completed", translation["error_code"]
    assert [item["pages"] for item in sarvam.submissions] == [1]
    assert google.requests
    with get_session_factory()() as session:
        jobs = session.scalars(select(DocumentProcessingJob).where(
            DocumentProcessingJob.target_type.in_(
                ["matter_attachment_ocr", "matter_attachment_translation"]
            ),
        )).all()
    assert sorted((job.target_type, job.status) for job in jobs) == [
        ("matter_attachment_ocr", "completed"),
        ("matter_attachment_translation", "completed"),
    ]
    pdf = client.get(
        f"{_base(matter_id, attachment_id)}/{translation['id']}/download",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_resume_job_completes_under_the_execution_protocol(
    pg_providers, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, sarvam, _ = pg_providers
    _verify_costs()
    monkeypatch.setenv("CASEOPS_SARVAM_JOB_MAX_WAIT_SECONDS", "1")
    get_settings.cache_clear()
    ticks = iter([0.0, 0.0])
    monkeypatch.setattr(pipeline, "_monotonic", lambda: next(ticks, 100.0))
    sarvam.running_polls = 1_000
    _, token, matter_id = _setup(client, "PG-OCR-2")
    attachment_id = _upload(client, token, matter_id, "scan.pdf", _pdf([None]))
    assert _start(client, token, matter_id, attachment_id, "hi").status_code == 202
    ocr = _latest(_versions(client, token, matter_id, attachment_id), "ocr")
    assert ocr["status"] == "ocr_processing"
    with get_session_factory()() as session:
        follow_up_id = session.get(MatterAttachmentRendition, ocr["id"]).processing_job_id
    sarvam.running_polls = 0
    assert run_document_processing_job(follow_up_id) is True
    assert _latest(_versions(client, token, matter_id, attachment_id), "ocr")["status"] == (
        "ocr_completed"
    )
    assert len(sarvam.submissions) == 1


def test_partial_unique_index_allows_one_open_run_per_kind(pg_providers) -> None:
    client, _, _ = pg_providers
    _, token, matter_id = _setup(client, "PG-OCR-3")
    attachment_id = _upload(client, token, matter_id, "a.pdf", _pdf([None]))
    with get_session_factory()() as session:
        attachment = session.get(MatterAttachment, attachment_id)
        company_id = attachment.matter.company_id

        def row(version: int, status: str) -> MatterAttachmentRendition:
            return MatterAttachmentRendition(
                company_id=company_id, matter_id=matter_id, attachment_id=attachment_id,
                kind="ocr", version=version, status=status, review_status="unreviewed",
                source_language="hi", source_sha256=attachment.sha256_hex,
            )

        session.add(row(1, "queued"))
        session.commit()
        session.add(row(2, "ocr_processing"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        first = session.scalar(select(MatterAttachmentRendition).where(
            MatterAttachmentRendition.attachment_id == attachment_id,
        ))
        first.status = "failed"
        session.commit()
        session.add(row(2, "queued"))
        session.commit()
        session.add(MatterAttachmentRendition(
            company_id=company_id, matter_id=matter_id, attachment_id=attachment_id,
            kind="translation", version=1, status="queued", review_status="unreviewed",
            source_language="hi", source_sha256=attachment.sha256_hex,
        ))
        with pytest.raises(IntegrityError):  # translation needs a source and target
            session.commit()
