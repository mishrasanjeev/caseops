"""Worker-side OCR and translation for matter attachment renditions.

Runs inside the existing document-processing job (claim, lease fence, stale
recovery). Rules this module keeps:

* The original upload is only read; its bytes are re-hashed and must still
  match the hash recorded when the run was requested.
* PDF pages with a usable text layer are read natively. Only the remaining
  pages go to Sarvam, in batches of at most 20, and are mapped back to their
  original page numbers. Unreadable text is never filled in.
* No database transaction is open during provider I/O. Provider job ids and
  spend holds are committed before polling, so an interrupted run resumes the
  same provider jobs instead of paying again.
* A run is complete only after its output is committed (and, for a
  translation, its PDF is stored and linked). Partial page failure is
  reported page by page and never shown as complete.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.document_rendition_models import (
    ACTIVE_RENDITION_STATUSES,
    MatterAttachmentRendition,
    RenditionKind,
    RenditionStatus,
)
from caseops_api.db.models import (
    AuditActorType,
    BillingSubscription,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    Matter,
    MatterActivity,
    MatterAttachment,
    ProviderCostCategory,
    ProviderSpendReservation,
    utcnow,
)
from caseops_api.db.session import get_session_factory, serialize_sqlite_writer
from caseops_api.services import google_translation, sarvam_document_ai
from caseops_api.services.audit import record_audit
from caseops_api.services.document_jobs import (
    _ClaimLost,
    _fence_attempt,
    _mark_job_failed,
    enqueue_processing_job,
    register_document_target_processor,
)
from caseops_api.services.document_renditions import (
    LANGUAGE_NAMES,
    OCR_TARGET_TYPE,
    TRANSLATION_COST_CATEGORY,
    TRANSLATION_TARGET_TYPE,
    load_pages,
    ocr_provider_unavailable_reason,
    queue_translation,
    source_format,
    translation_project_id,
    translation_unavailable_reason,
)
from caseops_api.services.document_storage import (
    delete_stored_document,
    persist_workspace_attachment,
    resolve_storage_path,
)
from caseops_api.services.legal_translation_checks import (
    batch_segments,
    check_translation,
    missing_details,
    segment_paragraphs,
    split_paragraphs,
)
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
    matter_is_operational,
)
from caseops_api.services.matter_write_fence import lock_matter_private_authority
from caseops_api.services.paid_provider_safety import paid_provider_block_reason
from caseops_api.services.pdf_extraction import pdfium_operation
from caseops_api.services.provider_costs import verified_actual_cost_minor
from caseops_api.services.provider_spend import (
    dispatch_provider_spend,
    release_provider_spend_in_session,
    reserve_provider_spend,
    settle_provider_spend,
)
from caseops_api.services.rendition_pdf import render_translation_pdf
from caseops_api.services.saas_billing import record_usage
from caseops_api.services.storage_governance import (
    StorageQuotaExceeded,
    assert_storage_quota_allows_upload,
)

logger = logging.getLogger(__name__)

NATIVE_MIN_CHARS = 80
SHORT_PAGE_CHARS = 40
MAX_SOURCE_PAGES = 1000
TRANSLATION_REQUEST_CHARS = 4500
TRANSLATION_REQUEST_ITEMS = 128
TRANSLATION_WORK_SECONDS = 600
RATE_LIMIT_BACKOFF_SECONDS = 2.0
BLOCK_TAGS_KEPT = 200

# Indirection points for tests (mock transports, no real sleeping).
_sleep: Callable[[float], None] = time.sleep
_monotonic: Callable[[], float] = time.monotonic


@dataclass(frozen=True, slots=True)
class _JobRef:
    """Plain copy of the claimed job; ORM rows expire on every commit/rollback."""

    id: str
    company_id: str
    requested_by_membership_id: str | None
    no_paid_providers: bool
    target_type: str
    action: str = ""


@dataclass(frozen=True, slots=True)
class _MatterFence:
    """The Matter lifecycle captured when the job started work."""

    company_id: str
    matter_id: str
    lifecycle_version: int


_MATTER_FENCE_KEY = "rendition_matter_fence"


class RenditionFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sarvam_client() -> tuple[sarvam_document_ai.SarvamDocumentClient, bool]:
    """Return the client and whether its transport is a test double."""

    settings = get_settings()
    return (
        sarvam_document_ai.SarvamDocumentClient(
            api_key=settings.sarvam_api_key or "",
            base_url=settings.sarvam_api_base_url,
            timeout_seconds=settings.sarvam_request_timeout_seconds,
        ),
        False,
    )


def translation_client() -> tuple[google_translation.GoogleTranslationClient, bool]:
    settings = get_settings()
    return (
        google_translation.GoogleTranslationClient(
            project_id=translation_project_id() or "",
            location=settings.google_translation_location,
            base_url=settings.google_translation_api_base_url,
            timeout_seconds=settings.google_translation_request_timeout_seconds,
        ),
        False,
    )


# ---------------------------------------------------------------- inspection


def usable_native_text(text: str, *, language: str) -> tuple[bool, str]:
    stripped = (text or "").strip()
    letters = sum(1 for char in stripped if char.isalpha())
    if len(stripped) < NATIVE_MIN_CHARS or letters < NATIVE_MIN_CHARS // 2:
        return False, "no_text_layer"
    bad = sum(
        1 for char in stripped
        if char == "�"
        or 0xE000 <= ord(char) <= 0xF8FF
        or (ord(char) < 32 and char not in "\t\n\r\f")
    )
    if bad > len(stripped) * 0.01:
        return False, "unreliable_text_layer"
    if language in {"hi", "mr"}:
        devanagari = sum(1 for char in stripped if "ऀ" <= char <= "ॿ")
        # Legacy (non-Unicode) Hindi fonts extract as Latin garble; OCR those.
        if devanagari < letters * 0.2:
            return False, "legacy_font_encoding_suspected"
    return True, ""


def inspect_pdf(path: str, *, language: str) -> list[tuple[int, str | None, str]]:
    """Return ``(page, native_text_or_None, reason)`` for every page."""

    import pypdfium2 as pdfium

    with pdfium_operation():
        try:
            document = pdfium.PdfDocument(path)
        except pdfium.PdfiumError as exc:
            if "password" in str(exc).lower():
                raise RenditionFailure(
                    "password_protected",
                    "The PDF is password-protected. Upload an unlocked copy.",
                ) from exc
            raise RenditionFailure(
                "corrupt_pdf", "The PDF could not be opened; it may be damaged.",
            ) from exc
        try:
            count = len(document)
            if count == 0:
                raise RenditionFailure("corrupt_pdf", "The PDF has no pages.")
            if count > MAX_SOURCE_PAGES:
                raise RenditionFailure(
                    "too_many_pages",
                    f"The PDF has {count} pages; OCR & Translate handles up to "
                    f"{MAX_SOURCE_PAGES}.",
                )
            results: list[tuple[int, str | None, str]] = []
            for index in range(count):
                page = document[index]
                try:
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_bounded(errors="ignore")
                    finally:
                        text_page.close()
                except pdfium.PdfiumError:
                    text = ""
                finally:
                    page.close()
                text = text.replace("\r\n", "\n").replace("\r", "\n")
                usable, reason = usable_native_text(text, language=language)
                results.append((index + 1, text.strip() if usable else None, reason))
            return results
        finally:
            document.close()


def build_batch_pdf(path: str, pages: list[int]) -> bytes:
    import pypdfium2 as pdfium

    with pdfium_operation():
        source = pdfium.PdfDocument(path)
        target = pdfium.PdfDocument.new()
        try:
            target.import_pages(source, pages=[page - 1 for page in pages])
            buffer = io.BytesIO()
            target.save(buffer)
            return buffer.getvalue()
        finally:
            target.close()
            source.close()


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_ocr_page(page: dict[str, Any]) -> None:
    """Set status/reasons on an OCR page from its own evidence only."""

    text = page.get("text") or ""
    reasons = [reason for reason in page.get("reasons", []) if reason.startswith("provider_")]
    if not text.strip():
        reasons.append("empty_page")
    elif len(text.strip()) < SHORT_PAGE_CHARS:
        reasons.append("short_text")
    if page.get("low_confidence_blocks"):
        reasons.append("low_confidence")
    if "�" in text:
        reasons.append("unreadable_characters")
    page["reasons"] = reasons
    page["char_count"] = len(text)
    page["status"] = "review" if reasons else "ok"


# ------------------------------------------------------------ persistence


def _set_job_done(
    session: Session, job_id: str, *, status: str, error: str | None = None, chars: int = 0,
) -> None:
    job = session.get(DocumentProcessingJob, job_id)
    if job is None:
        return
    job.status = status
    job.error_message = error
    job.processed_char_count = max(chars, 0)
    job.completed_at = utcnow()
    session.add(job)


def _persist(
    session: Session,
    *,
    rendition_id: str,
    mutate: Callable[[MatterAttachmentRendition], None],
    fence_matter: bool = True,
) -> None:
    """Apply ``mutate`` under the tenant, job-lease and Matter fences, then commit.

    Lock order matches ordinary document jobs: Company authority, the job
    lease, then a shared Matter lifecycle fence. Disposal takes the Matter
    exclusively, so a result can never publish after (or during) disposal or
    a reopen. Recording a failure skips the Matter check (``fence_matter``).
    """

    session.rollback()
    serialize_sqlite_writer(session)
    fence: _MatterFence | None = session.info.get(_MATTER_FENCE_KEY)
    with session.no_autoflush:
        if fence is not None:
            lock_matter_private_authority(session, company_id=fence.company_id)
        _fence_attempt(session)
        if fence is not None and fence_matter:
            _assert_matter_fence(session, fence)
    rendition = session.scalar(
        select(MatterAttachmentRendition)
        .where(MatterAttachmentRendition.id == rendition_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if rendition is None:
        raise RenditionFailure("missing", "The OCR or translation version was deleted.")
    mutate(rendition)
    session.add(rendition)
    session.commit()
    session.expunge_all()


def _assert_matter_fence(session: Session, fence: _MatterFence) -> None:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == fence.matter_id, Matter.company_id == fence.company_id,
        )
    )
    if matter is None:
        raise RenditionFailure("missing_source", "The matter for this document is gone.")
    try:
        matter = assert_operational_matter(
            session, matter=matter, shared_lifecycle_fence=True,
        )
    except MatterNotOperationalError as exc:
        raise RenditionFailure(
            "matter_disposed", "The matter is disposed or inactive; processing stopped.",
        ) from exc
    if matter.lifecycle_version != fence.lifecycle_version:
        raise RenditionFailure(
            "matter_lifecycle_changed",
            "The matter was closed or reopened while this ran; nothing was published. "
            "Retry is available.",
        )


def _budget_session_call(action: Callable[[Session], None]) -> None:
    with get_session_factory()() as budget_session:
        serialize_sqlite_writer(budget_session)
        action(budget_session)
        budget_session.commit()


def _dispatch(reservation_id: str | None, company_id: str) -> None:
    if reservation_id:
        _budget_session_call(
            lambda s: dispatch_provider_spend(
                s, reservation_id=reservation_id, company_id=company_id,
            )
        )


@dataclass(frozen=True, slots=True)
class _Usage:
    """Who and what a settled provider charge is attributed to."""

    company_id: str
    actor_membership_id: str | None
    matter_id: str
    rendition_id: str


def _settle(
    reservation_id: str | None,
    amount: int | None,
    *,
    usage: _Usage,
    provider: str,
    quantity: int,
    unit: str,
) -> None:
    """Settle a hold and publish the same amount as billing usage, atomically.

    Settlement alone does not count against the workspace budget; the budget
    reads ``BillingUsageEvent`` rows, so both are written in one transaction.
    """

    if not reservation_id:
        return

    def act(budget_session: Session) -> None:
        row = budget_session.scalar(
            select(ProviderSpendReservation)
            .where(ProviderSpendReservation.id == reservation_id)
            .with_for_update()
        )
        if row is None or row.status != "reserved":
            return
        cost = row.amount_minor if amount is None else max(0, min(amount, row.amount_minor))
        subscription_id = budget_session.scalar(
            select(BillingSubscription.id)
            .where(BillingSubscription.company_id == usage.company_id)
            .order_by(BillingSubscription.created_at.desc())
            .limit(1)
        )
        ocr = provider == sarvam_document_ai.PROVIDER_KEY
        record_usage(
            budget_session,
            company_id=usage.company_id,
            subscription_id=subscription_id,
            usage_type="document_ocr_pages" if ocr else "document_translation_characters",
            feature_key="document_ocr_translation",
            provider_key=provider,
            quantity=max(quantity, 0),
            unit=unit,
            actor_membership_id=usage.actor_membership_id,
            matter_id=usage.matter_id,
            estimated_cost_minor=cost,
            purpose="document_ocr" if ocr else "document_translation",
            display_label="Document OCR" if ocr else "Document translation",
            source_type="matter_attachment_rendition",
            source_id=usage.rendition_id,
            metadata={"provider": provider},
        )
        settle_provider_spend(budget_session, reservation_id=reservation_id, amount_minor=cost)

    _budget_session_call(act)


def _release_no_charge(reservation_id: str | None) -> None:
    if reservation_id:
        _budget_session_call(
            lambda s: release_provider_spend_in_session(
                s, reservation_id=reservation_id, confirmed_no_charge=True,
            )
        )


def _reserve(
    *, company_id: str, actor: str | None, provider: str, operation: str, amount: int,
) -> str | None:
    try:
        return reserve_provider_spend(
            company_id=company_id,
            actor_membership_id=actor,
            provider_key=provider,
            operation_key=operation,
            amount_minor=amount,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        raise RenditionFailure(
            str(detail.get("code") or "provider_budget_exhausted"),
            str(detail.get("message") or "The workspace paid-provider budget is exhausted."),
        ) from exc


def _record(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    rendition_id: str,
    action: str,
    title: str,
    detail: str,
    metadata: dict[str, Any],
) -> None:
    session.add(
        MatterActivity(
            matter_id=matter_id,
            actor_membership_id=None,
            event_type=action.rsplit(".", 1)[-1],
            title=title,
            detail=detail,
        )
    )
    record_audit(
        session,
        company_id=company_id,
        action=action,
        target_type="matter_attachment_rendition",
        target_id=rendition_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label="document-processing-worker",
        matter_id=matter_id,
        metadata=metadata,
    )


# -------------------------------------------------------------- entry point


def process_rendition_job(session: Session, job: DocumentProcessingJob) -> None:
    job_id = job.id
    rendition = session.scalar(
        select(MatterAttachmentRendition).where(
            MatterAttachmentRendition.id == job.attachment_id,
            MatterAttachmentRendition.company_id == job.company_id,
        )
    )
    expected_kind = (
        RenditionKind.OCR if job.target_type == OCR_TARGET_TYPE else RenditionKind.TRANSLATION
    )
    if rendition is None or rendition.kind != expected_kind:
        _mark_job_failed(session, job, error_message="OCR or translation version not found.")
        return
    if rendition.status not in ACTIVE_RENDITION_STATUSES or rendition.processing_job_id != job_id:
        # Superseded or already finished; nothing to pay for again.
        _persist(
            session,
            rendition_id=rendition.id,
            mutate=lambda _r: _set_job_done(
                session, job_id, status=DocumentProcessingJobStatus.COMPLETED,
                error="Superseded; no work performed.",
            ),
        )
        return
    attachment = session.get(MatterAttachment, rendition.attachment_id)
    matter = session.get(Matter, rendition.matter_id)
    if attachment is None or matter is None or matter.company_id != job.company_id:
        _fail_rendition(
            session, job_id, rendition.id, "missing_source", "The original document is gone.",
        )
        return
    if not matter_is_operational(matter):
        _fail_rendition(
            session, job_id, rendition.id, "matter_disposed",
            "The matter is disposed or inactive; processing stopped.",
        )
        return
    rendition_id = rendition.id
    job_ref = _JobRef(
        id=job.id,
        company_id=job.company_id,
        requested_by_membership_id=job.requested_by_membership_id,
        no_paid_providers=job.no_paid_providers,
        target_type=job.target_type,
        action=str(job.action or ""),
    )
    session.info[_MATTER_FENCE_KEY] = _MatterFence(
        company_id=job.company_id,
        matter_id=matter.id,
        lifecycle_version=int(matter.lifecycle_version),
    )
    try:
        if rendition.kind == RenditionKind.OCR:
            _run_ocr(session, job_ref, rendition, attachment)
        else:
            _run_translation(session, job_ref, rendition, attachment)
    except RenditionFailure as failure:
        _fail_rendition(session, job_id, rendition_id, failure.code, failure.message)
    except _ClaimLost:
        raise
    except Exception:
        # Never leave a version stuck "processing": fail it, keep its pages.
        logger.exception("rendition processing failed for rendition=%s", rendition_id)
        _fail_rendition(
            session, job_id, rendition_id, "internal_error",
            "Processing stopped unexpectedly. Saved progress is kept; retry is available.",
        )
    finally:
        session.info.pop(_MATTER_FENCE_KEY, None)


def _fail_rendition(
    session: Session, job_id: str, rendition_id: str, code: str, message: str,
    *, pages: list[dict[str, Any]] | None = None,
) -> None:
    def mutate(rendition: MatterAttachmentRendition) -> None:
        rendition.status = RenditionStatus.FAILED
        rendition.error_code = code[:64]
        rendition.error_message = message
        rendition.completed_at = utcnow()
        if pages is not None:
            rendition.pages_json = json.dumps(pages, ensure_ascii=False)
            _apply_counts(rendition, pages)
        _set_job_done(session, job_id, status=DocumentProcessingJobStatus.FAILED, error=message)
        _record(
            session,
            company_id=rendition.company_id,
            matter_id=rendition.matter_id,
            rendition_id=rendition.id,
            action=(
                "matter_attachment.ocr_failed" if rendition.kind == RenditionKind.OCR
                else "matter_attachment.translation_failed"
            ),
            title="OCR failed" if rendition.kind == RenditionKind.OCR else "Translation failed",
            detail=f"Version {rendition.version}: {message}",
            metadata={"code": code, "attachment_id": rendition.attachment_id},
        )

    _persist(session, rendition_id=rendition_id, mutate=mutate, fence_matter=False)


def _apply_counts(rendition: MatterAttachmentRendition, pages: list[dict[str, Any]]) -> None:
    statuses = Counter(page.get("status") for page in pages)
    rendition.page_count = len(pages)
    rendition.pages_ok = statuses.get("ok", 0)
    rendition.pages_review = statuses.get("review", 0)
    rendition.pages_failed = statuses.get("failed", 0) + statuses.get("pending", 0)


def _requeue(
    session: Session, job: _JobRef, rendition_id: str,
    *, pages: list[dict[str, Any]], provider_jobs: list[dict[str, Any]],
) -> None:
    job_id, company_id, requester = job.id, job.company_id, job.requested_by_membership_id
    no_paid = job.no_paid_providers
    target_type = job.target_type

    def mutate(rendition: MatterAttachmentRendition) -> None:
        rendition.pages_json = json.dumps(pages, ensure_ascii=False)
        rendition.provider_jobs_json = json.dumps(provider_jobs)
        follow_up = enqueue_processing_job(
            session,
            company_id=company_id,
            requested_by_membership_id=requester,
            target_type=target_type,
            attachment_id=rendition.id,
            action="resume",
            no_paid_providers=no_paid,
        )
        rendition.processing_job_id = follow_up.id
        _set_job_done(
            session, job_id, status=DocumentProcessingJobStatus.COMPLETED,
            error="Provider still working; a follow-up job resumes this run.",
        )

    _persist(session, rendition_id=rendition_id, mutate=mutate)


# --------------------------------------------------------------------- OCR


def _run_ocr(
    session: Session,
    job: _JobRef,
    rendition: MatterAttachmentRendition,
    attachment: MatterAttachment,
) -> None:
    rid = rendition.id
    company_id = rendition.company_id
    matter_id = rendition.matter_id
    language = rendition.source_language
    requester = rendition.requested_by_membership_id
    expected_sha = rendition.source_sha256
    storage_key = attachment.storage_key
    filename = attachment.original_filename
    content_type = (attachment.content_type or "").split(";", 1)[0].strip().lower()
    local_only = attachment.native_local_processing_only
    fmt = source_format(attachment)
    pages = load_pages(rendition)
    provider_jobs: list[dict[str, Any]] = (
        json.loads(rendition.provider_jobs_json) if rendition.provider_jobs_json else []
    )
    provider_reason = ocr_provider_unavailable_reason(session)
    unit_cost = verified_actual_cost_minor(
        session, category=ProviderCostCategory.OCR_PAGE, provider=sarvam_document_ai.PROVIDER_KEY,
    )
    if fmt is None:
        raise RenditionFailure(
            "unsupported_format", "OCR & Translate supports PDF, JPG, JPEG and PNG only.",
        )
    first_pass = not pages

    def start(r: MatterAttachmentRendition) -> None:
        r.status = RenditionStatus.INSPECTING if first_pass else RenditionStatus.OCR_PROCESSING
        r.error_code = None
        r.error_message = None

    _persist(session, rendition_id=rid, mutate=start)

    path = str(resolve_storage_path(storage_key))
    if _file_sha256(path) != expected_sha:
        raise RenditionFailure(
            "source_changed", "The original file changed after OCR was requested.",
        )
    if first_pass:
        if fmt == "pdf":
            inspected = inspect_pdf(path, language=language)
        else:
            inspected = [(1, None, "image")]
        pages = []
        for number, native_text, reason in inspected:
            if native_text is not None:
                pages.append({
                    "page": number, "source": "native", "status": "ok", "reasons": [],
                    "text": native_text, "char_count": len(native_text),
                })
            else:
                pages.append({
                    "page": number, "source": "none", "status": "pending",
                    "reasons": [f"inspect_{reason}"], "text": None, "char_count": 0,
                })
    else:
        user_retry = job.action == "retry"
        # A batch recorded as "dispatching" was interrupted between the saved
        # intent and its receipt: Sarvam may have accepted and billed it. Keep
        # its hold and never resubmit it automatically; only a user retry may.
        for entry in provider_jobs:
            if entry.get("status") == "dispatching":
                entry["status"] = "uncertain"
        uncertain_pages: set[int] = set()
        for entry in provider_jobs:
            if entry.get("status") != "uncertain":
                continue
            if user_retry:
                entry["status"] = "uncertain_retried"
            else:
                uncertain_pages.update(entry.get("pages", []))
        open_pages = {
            number for entry in provider_jobs if entry.get("status") == "submitted"
            for number in entry.get("pages", [])
        }
        for page in pages:
            if page["page"] in open_pages:
                continue
            if page["page"] in uncertain_pages:
                if page.get("status") in {"pending", "failed"}:
                    page["status"] = "failed"
                    if "provider_submit_uncertain" not in page.get("reasons", []):
                        page["reasons"] = [*page.get("reasons", []), "provider_submit_uncertain"]
                continue
            # Automatic recovery continues pages never sent; settled failures are
            # resubmitted (and paid for again) only on an explicit user retry.
            if page.get("status") == "pending" or (
                user_retry and page.get("status") == "failed"
            ):
                page.update(status="pending", source="none", text=None, char_count=0)
                page["reasons"] = [r for r in page.get("reasons", []) if r.startswith("inspect_")]

    pending = [page for page in pages if page["status"] == "pending"]

    def save_pages(r: MatterAttachmentRendition) -> None:
        r.status = RenditionStatus.OCR_PROCESSING if pending else RenditionStatus.INSPECTING
        r.pages_json = json.dumps(pages, ensure_ascii=False)
        r.provider_jobs_json = json.dumps(provider_jobs)
        _apply_counts(r, pages)

    _persist(session, rendition_id=rid, mutate=save_pages)

    needs_resume = False
    if pending:
        block = None
        if local_only:
            block = "third_party_processing_not_permitted"
        elif provider_reason is not None:
            block = f"ocr_provider_{provider_reason}"
        client = mocked = None
        if block is None:
            client, mocked = sarvam_client()
            guard = paid_provider_block_reason(
                context=None,
                provider=sarvam_document_ai.PROVIDER_KEY,
                base_url=get_settings().sarvam_api_base_url,
                transport_is_mocked=mocked,
            )
            if guard is not None:
                block = "paid_provider_blocked_for_test"
        if block is not None:
            for page in pending:
                page["status"] = "failed"
                page["reasons"] = [*page.get("reasons", []), block]
        else:
            assert client is not None and unit_cost is not None
            try:
                needs_resume = _run_sarvam(
                    session,
                    rendition_id=rid,
                    client=client,
                    path=path,
                    fmt=fmt,
                    filename=filename,
                    content_type=content_type,
                    language=language,
                    pages=pages,
                    provider_jobs=provider_jobs,
                    unit_cost=unit_cost,
                    company_id=company_id,
                    requester=requester,
                    usage=_Usage(company_id, requester, matter_id, rid),
                )
            finally:
                client.close()

    if needs_resume:
        _requeue(session, job, rid, pages=pages, provider_jobs=provider_jobs)
        return
    _finish_ocr(session, job, rid, pages=pages, provider_jobs=provider_jobs)


def _content_for_batch(path: str, fmt: str, numbers: list[int], filename: str,
                       content_type: str) -> tuple[str, bytes, str]:
    if fmt == "image":
        with open(path, "rb") as handle:
            data = handle.read()
        suffix = filename.rsplit(".", 1)[-1].lower()
        return f"page-1.{suffix}", data, content_type or "image/jpeg"
    return (
        f"pages-{numbers[0]}-{numbers[-1]}.pdf",
        build_batch_pdf(path, numbers),
        "application/pdf",
    )


def _run_sarvam(
    session: Session,
    *,
    rendition_id: str,
    client: sarvam_document_ai.SarvamDocumentClient,
    path: str,
    fmt: str,
    filename: str,
    content_type: str,
    language: str,
    pages: list[dict[str, Any]],
    provider_jobs: list[dict[str, Any]],
    unit_cost: int,
    company_id: str,
    requester: str | None,
    usage: _Usage,
) -> bool:
    """Submit, poll and map Sarvam batches. Returns True if work is still open."""

    settings = get_settings()
    deadline = _monotonic() + settings.sarvam_job_max_wait_seconds
    by_number = {page["page"]: page for page in pages}

    def fail(numbers: list[int], reason: str) -> None:
        for number in numbers:
            page = by_number[number]
            page["status"] = "failed"
            page["reasons"] = [*page.get("reasons", []), reason]

    def checkpoint() -> None:
        def mutate(r: MatterAttachmentRendition) -> None:
            r.pages_json = json.dumps(pages, ensure_ascii=False)
            r.provider_jobs_json = json.dumps(provider_jobs)
            _apply_counts(r, pages)

        _persist(session, rendition_id=rendition_id, mutate=mutate)

    open_numbers = {
        number for entry in provider_jobs if entry.get("status") == "submitted"
        for number in entry.get("pages", [])
    }
    to_submit = [
        page["page"] for page in pages
        if page["status"] == "pending" and page["page"] not in open_numbers
    ]
    batches = [
        to_submit[index:index + sarvam_document_ai.MAX_PAGES_PER_JOB]
        for index in range(0, len(to_submit), sarvam_document_ai.MAX_PAGES_PER_JOB)
    ]
    for position, numbers in enumerate(batches):
        if _monotonic() >= deadline:
            break
        try:
            reservation_id = _reserve(
                company_id=company_id,
                actor=requester,
                provider=sarvam_document_ai.PROVIDER_KEY,
                operation=f"sarvam_ocr_pages:{rendition_id}",
                amount=unit_cost * len(numbers),
            )
        except RenditionFailure as failure:
            for remaining in batches[position:]:
                fail(remaining, failure.code)
            break
        name, content, media_type = _content_for_batch(path, fmt, numbers, filename, content_type)
        # Commit the intent before any byte leaves: if the worker dies after
        # Sarvam accepts the file, recovery sees this entry and does not pay
        # for the same pages again.
        entry: dict[str, Any] = {
            "pages": numbers, "status": "dispatching", "reservation_id": reservation_id,
            "dispatched_at": utcnow().isoformat(),
        }
        provider_jobs.append(entry)
        checkpoint()
        _dispatch(reservation_id, company_id)
        try:
            provider_job_id = client.submit_parse(
                filename=name, content=content, content_type=media_type, language=language,
            )
        except sarvam_document_ai.SarvamError as error:
            if not error.charge_possible:
                _release_no_charge(reservation_id)
            entry.update(
                status="submit_failed", error=error.code, charge_possible=error.charge_possible,
            )
            fail(numbers, f"provider_{error.code}")
            if error.code in {"auth", "billing"}:
                for remaining in batches[position + 1:]:
                    fail(remaining, f"provider_{error.code}")
                checkpoint()
                break
            checkpoint()
            continue
        entry.update(
            status="submitted", job_id=provider_job_id, submitted_at=utcnow().isoformat(),
        )
        # Save the provider job id before polling: a crash resumes, never resubmits.
        checkpoint()

    open_entries = [entry for entry in provider_jobs if entry.get("status") == "submitted"]
    while open_entries:
        progressed = False
        for entry in list(open_entries):
            try:
                state = client.get_status(entry["job_id"])
            except sarvam_document_ai.SarvamError as error:
                if error.retryable:
                    continue
                state = sarvam_document_ai.SarvamJobStatus(
                    entry["job_id"], "failed", None, None, None,
                )
            if not state.terminal:
                continue
            _finish_sarvam_entry(client, entry, state, by_number, unit_cost, usage)
            open_entries.remove(entry)
            progressed = True
        if progressed:
            checkpoint()
        if not open_entries or _monotonic() >= deadline:
            break
        _sleep(settings.sarvam_poll_interval_seconds)
    still_pending = any(page["status"] == "pending" for page in pages)
    return bool(open_entries) or still_pending


def _finish_sarvam_entry(
    client: sarvam_document_ai.SarvamDocumentClient,
    entry: dict[str, Any],
    state: sarvam_document_ai.SarvamJobStatus,
    by_number: dict[int, dict[str, Any]],
    unit_cost: int,
    usage: _Usage,
) -> None:
    numbers: list[int] = list(entry["pages"])

    def settle(amount: int | None, pages: int) -> None:
        _settle(
            reservation_id, amount, usage=usage, provider=sarvam_document_ai.PROVIDER_KEY,
            quantity=pages, unit="page",
        )

    reservation_id = entry.get("reservation_id")
    entry["status"] = state.status
    entry["pages_succeeded"] = state.pages_succeeded
    entry["pages_failed"] = state.pages_failed
    if state.status == "rejected":
        _release_no_charge(reservation_id)
        for number in numbers:
            by_number[number].update(status="failed")
            by_number[number]["reasons"].append("provider_rejected")
        return
    if state.status == "failed":
        # Billing for a failed job is unknown; count the full hold.
        settle(None, len(numbers))
        for number in numbers:
            by_number[number].update(status="failed")
            by_number[number]["reasons"].append("provider_failed")
        return
    succeeded = (
        min(state.pages_succeeded, len(numbers))
        if state.pages_succeeded is not None else len(numbers)
    )
    settle(succeeded * unit_cost, succeeded)
    try:
        archive = client.download_output(entry["job_id"])
        parsed = sarvam_document_ai.parse_output_archive(archive, page_count=len(numbers))
    except sarvam_document_ai.SarvamError as error:
        entry["output_error"] = error.code
        for number in numbers:
            by_number[number].update(status="failed")
            by_number[number]["reasons"].append(f"provider_{error.code}")
        return
    for position, number in enumerate(numbers, start=1):
        page = by_number[number]
        result = parsed.get(position)
        if result is None:
            page["status"] = "failed"
            page["reasons"].append("provider_page_missing")
            continue
        page.update(
            source="ocr",
            text=result.text,
            min_confidence=result.min_confidence,
            low_confidence_blocks=result.low_confidence_blocks,
            blocks=result.blocks[:BLOCK_TAGS_KEPT],
            # The cap limits stored layout metadata only; translation must then
            # read the complete page text instead of the capped block list.
            blocks_truncated=len(result.blocks) > BLOCK_TAGS_KEPT,
            provider_job_id=entry["job_id"],
        )
        validate_ocr_page(page)


def _finish_ocr(
    session: Session,
    job: _JobRef,
    rendition_id: str,
    *,
    pages: list[dict[str, Any]],
    provider_jobs: list[dict[str, Any]],
) -> None:
    job_id = job.id
    no_paid = job.no_paid_providers
    readable = sum(1 for page in pages if page["status"] in {"ok", "review"})
    failed_reasons = Counter(
        reason for page in pages if page["status"] == "failed"
        for reason in page.get("reasons", [])[-1:]
    )
    used_ocr = any(page.get("source") == "ocr" for page in pages) or any(
        entry.get("job_id") for entry in provider_jobs
    )
    used_native = any(page.get("source") == "native" for page in pages)
    chained: dict[str, str] = {}
    total_chars = sum(int(page.get("char_count") or 0) for page in pages)

    def mutate(rendition: MatterAttachmentRendition) -> None:
        rendition.pages_json = json.dumps(pages, ensure_ascii=False)
        rendition.provider_jobs_json = json.dumps(provider_jobs)
        _apply_counts(rendition, pages)
        rendition.provider = "+".join(
            name for name, used in (("native-pdf-text", used_native), ("sarvam", used_ocr))
            if used
        ) or None
        rendition.model = sarvam_document_ai.MODEL_LABEL if used_ocr else None
        rendition.completed_at = utcnow()
        if readable == 0:
            code = failed_reasons.most_common(1)[0][0] if failed_reasons else "no_readable_text"
            rendition.status = RenditionStatus.FAILED
            rendition.error_code = code[:64]
            rendition.error_message = _ocr_failure_message(code)
        elif rendition.pages_failed or rendition.pages_review:
            rendition.status = RenditionStatus.REVIEW_REQUIRED
            if rendition.pages_failed:
                rendition.error_code = "partial_page_failure"
                rendition.error_message = (
                    f"{rendition.pages_failed} of {rendition.page_count} pages could not be "
                    "read. They are listed below and can be retried."
                )
        else:
            rendition.status = RenditionStatus.OCR_COMPLETED
        succeeded = rendition.status != RenditionStatus.FAILED
        _set_job_done(
            session, job_id,
            status=(
                DocumentProcessingJobStatus.COMPLETED if succeeded
                else DocumentProcessingJobStatus.FAILED
            ),
            error=None if succeeded else rendition.error_message,
            chars=total_chars,
        )
        _record(
            session,
            company_id=rendition.company_id,
            matter_id=rendition.matter_id,
            rendition_id=rendition.id,
            action=(
                "matter_attachment.ocr_completed" if succeeded
                else "matter_attachment.ocr_failed"
            ),
            title="OCR finished" if succeeded else "OCR failed",
            detail=(
                f"Version {rendition.version}: {rendition.pages_ok} pages read, "
                f"{rendition.pages_review} need review, {rendition.pages_failed} failed."
            ),
            metadata={
                "attachment_id": rendition.attachment_id,
                "pages": rendition.page_count,
                "pages_failed": rendition.pages_failed,
                "provider": rendition.provider,
            },
        )
        target = rendition.chain_target_language
        if succeeded and target:
            attachment = session.get(MatterAttachment, rendition.attachment_id)
            # Chain once per OCR version: a retry of a partly failed OCR run never
            # re-buys a translation, and an open translation is never duplicated.
            blocking_translation = session.scalar(
                select(MatterAttachmentRendition.id).where(
                    MatterAttachmentRendition.attachment_id == rendition.attachment_id,
                    MatterAttachmentRendition.kind == RenditionKind.TRANSLATION,
                    or_(
                        MatterAttachmentRendition.source_rendition_id == rendition.id,
                        MatterAttachmentRendition.status.in_(
                            [status.value for status in ACTIVE_RENDITION_STATUSES]
                        ),
                    ),
                ).limit(1)
            )
            if attachment is not None and blocking_translation is None:
                translation = queue_translation(
                    session,
                    company_id=rendition.company_id,
                    attachment=attachment,
                    source=rendition,
                    target_language=target,
                    requested_by_membership_id=rendition.requested_by_membership_id,
                )
                session.add(translation)
                session.flush()
                follow_up = enqueue_processing_job(
                    session,
                    company_id=rendition.company_id,
                    requested_by_membership_id=rendition.requested_by_membership_id,
                    target_type=TRANSLATION_TARGET_TYPE,
                    attachment_id=translation.id,
                    action="translate",
                    no_paid_providers=no_paid,
                )
                translation.processing_job_id = follow_up.id
                chained["job_id"] = follow_up.id

    _persist(session, rendition_id=rendition_id, mutate=mutate)
    if chained:
        from caseops_api.services.document_jobs import run_document_processing_job

        # Continue straight into translation in this worker invocation.
        run_document_processing_job(chained["job_id"])


def _ocr_failure_message(code: str) -> str:
    messages = {
        "third_party_processing_not_permitted": (
            "This document is limited to on-device processing, and none of its pages have "
            "a usable text layer."
        ),
        "ocr_provider_provider_disabled": "Scanned-page OCR is not enabled for this workspace.",
        "ocr_provider_credentials_missing": "Scanned-page OCR is not configured on the server.",
        "ocr_provider_cost_not_verified": (
            "OCR pricing has not been verified, so no paid OCR call was made."
        ),
        "paid_provider_blocked_for_test": (
            "Paid OCR is disabled for automated verification; no external request was made."
        ),
        "provider_budget_exhausted": (
            "The workspace paid-provider budget is exhausted; no OCR request was made."
        ),
    }
    if code in messages:
        return messages[code]
    if code.startswith("provider_"):
        return f"Sarvam OCR could not read the pages ({code.removeprefix('provider_')})."
    return "No page of this document could be read."


# ------------------------------------------------------------- translation


def _translation_pages(ocr_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in sorted(ocr_pages, key=lambda item: int(item.get("page", 0))):
        paragraphs: list[dict[str, Any]] = []
        if page.get("status") == "failed" or not (page.get("text") or "").strip():
            paragraphs.append({
                "index": 0, "kind": "unavailable", "source": "", "translated": None,
                "source_unavailable": True, "flags": ["source_page_unreadable"],
            })
        else:
            blocks = [block for block in page.get("blocks") or [] if block.get("text")]
            if blocks and not page.get("blocks_truncated"):
                units = [
                    (str(block.get("tag") or "paragraph"), str(block["text"])) for block in blocks
                ]
            else:
                units = [("paragraph", text) for text in split_paragraphs(page["text"])]
            for index, (kind, text) in enumerate(units):
                flags = ["source_needs_review"] if page.get("status") == "review" else []
                paragraphs.append({
                    "index": index, "kind": kind[:40], "source": text, "translated": None,
                    "source_unavailable": False, "flags": flags,
                })
        result.append({
            "page": int(page.get("page", 0)),
            "source": page.get("source") or "none",
            "status": "pending",
            "reasons": [],
            "char_count": 0,
            "paragraphs": paragraphs,
        })
    return result


def _apply_translation_page_status(page: dict[str, Any]) -> None:
    paragraphs = page.get("paragraphs") or []
    if any(item.get("source_unavailable") for item in paragraphs) and all(
        item.get("source_unavailable") for item in paragraphs
    ):
        page["status"] = "failed"
        page["reasons"] = ["source_page_unreadable"]
    elif any(
        item.get("translated") is None and not item.get("source_unavailable")
        for item in paragraphs
    ):
        page["status"] = "pending"
    else:
        flags = sorted({flag for item in paragraphs for flag in item.get("flags", [])})
        page["status"] = "review" if flags else "ok"
        page["reasons"] = flags
    page["char_count"] = sum(len(item.get("translated") or "") for item in paragraphs)


def _run_translation(
    session: Session,
    job: _JobRef,
    rendition: MatterAttachmentRendition,
    attachment: MatterAttachment,
) -> None:
    rid = rendition.id
    company_id = rendition.company_id
    matter_id = rendition.matter_id
    requester = rendition.requested_by_membership_id
    source_language = rendition.source_language
    target_language = rendition.target_language or ""
    version = rendition.version
    title = attachment.original_filename
    pages = load_pages(rendition)
    local_only = attachment.native_local_processing_only
    source = (
        session.get(MatterAttachmentRendition, rendition.source_rendition_id)
        if rendition.source_rendition_id else None
    )
    if source is None or source.kind != RenditionKind.OCR or source.attachment_id != attachment.id:
        raise RenditionFailure("ocr_missing", "The OCR version for this translation is gone.")
    ocr_pages = load_pages(source)
    reason = translation_unavailable_reason(session)
    unit_cost = verified_actual_cost_minor(
        session, category=TRANSLATION_COST_CATEGORY, provider=google_translation.PROVIDER_KEY,
    )
    if local_only:
        raise RenditionFailure(
            "third_party_processing_not_permitted",
            "This document is limited to on-device processing and cannot be translated.",
        )
    if reason is not None:
        raise RenditionFailure(
            f"translation_{reason}",
            {
                "provider_disabled": "Translation is not enabled for this workspace.",
                "credentials_missing": "Translation is not configured on the server.",
                "cost_not_verified": (
                    "Translation pricing has not been verified, so no paid call was made."
                ),
            }[reason],
        )
    if not pages:
        pages = _translation_pages(ocr_pages)

    def start(r: MatterAttachmentRendition) -> None:
        r.status = RenditionStatus.TRANSLATION_PROCESSING
        r.error_code = None
        r.error_message = None
        r.pages_json = json.dumps(pages, ensure_ascii=False)
        _apply_counts(r, pages)

    _persist(session, rendition_id=rid, mutate=start)

    client, mocked = translation_client()
    try:
        if paid_provider_block_reason(
            context=None,
            provider=google_translation.PROVIDER_KEY,
            base_url=get_settings().google_translation_api_base_url,
            transport_is_mocked=mocked,
        ) is not None:
            raise RenditionFailure(
                "paid_provider_blocked_for_test",
                "Paid translation is disabled for automated verification; no external "
                "request was made.",
            )
        assert unit_cost is not None
        open_work = _translate_paragraphs(
            session,
            rendition_id=rid,
            client=client,
            pages=pages,
            source_language=source_language,
            target_language=target_language,
            unit_cost=unit_cost,
            company_id=company_id,
            requester=requester,
            usage=_Usage(company_id, requester, matter_id, rid),
        )
        model = client.model
    finally:
        client.close()
    if open_work:
        _requeue(session, job, rid, pages=pages, provider_jobs=[])
        return
    _finish_translation(
        session,
        job,
        rid,
        pages=pages,
        model=model,
        company_id=company_id,
        matter_id=matter_id,
        title=title,
        version=version,
        source_language=source_language,
        target_language=target_language,
    )


def _translate_paragraphs(
    session: Session,
    *,
    rendition_id: str,
    client: google_translation.GoogleTranslationClient,
    pages: list[dict[str, Any]],
    source_language: str,
    target_language: str,
    unit_cost: int,
    company_id: str,
    requester: str | None,
    usage: _Usage,
) -> bool:
    """Translate untranslated paragraphs. Returns True if work remains."""

    deadline = _monotonic() + TRANSLATION_WORK_SECONDS
    keys: list[tuple[int, int]] = []
    texts: list[str] = []
    for page_index, page in enumerate(pages):
        for paragraph_index, paragraph in enumerate(page.get("paragraphs") or []):
            if paragraph.get("translated") is None and not paragraph.get("source_unavailable"):
                keys.append((page_index, paragraph_index))
                texts.append(paragraph["source"])
    segments = segment_paragraphs(texts, limit=TRANSLATION_REQUEST_CHARS)
    pieces_needed = Counter(segment.paragraph_index for segment in segments)
    done: dict[int, list[str]] = {}

    def complete(index: int) -> None:
        page_index, paragraph_index = keys[index]
        paragraph = pages[page_index]["paragraphs"][paragraph_index]
        translated = " ".join(done.pop(index)).strip()
        paragraph["translated"] = translated
        flags = [
            flag for flag in paragraph.get("flags", [])
            if flag in {"source_needs_review"}
        ]
        flags.extend(check_translation(paragraph["source"], translated))
        paragraph["flags"] = sorted(set(flags))
        paragraph.update(missing_details(paragraph["source"], translated))

    def checkpoint() -> None:
        for page in pages:
            _apply_translation_page_status(page)

        def mutate(r: MatterAttachmentRendition) -> None:
            r.pages_json = json.dumps(pages, ensure_ascii=False)
            _apply_counts(r, pages)

        _persist(session, rendition_id=rendition_id, mutate=mutate)

    for batch in batch_segments(
        segments, max_chars=TRANSLATION_REQUEST_CHARS, max_items=TRANSLATION_REQUEST_ITEMS,
    ):
        if _monotonic() >= deadline:
            checkpoint()
            return True
        chars = sum(len(segment.text) for segment in batch)
        reservation_id = _reserve(
            company_id=company_id,
            actor=requester,
            provider=google_translation.PROVIDER_KEY,
            operation=f"translation_llm:{rendition_id}",
            amount=unit_cost * max(1, math.ceil(chars / 1000)),
        )
        _dispatch(reservation_id, company_id)
        result = None
        for attempt in range(2):
            try:
                result = client.translate(
                    [segment.text for segment in batch],
                    source=source_language,
                    target=target_language,
                )
                break
            except google_translation.GoogleTranslationError as error:
                if attempt == 0 and error.retryable and not error.charge_possible:
                    _sleep(RATE_LIMIT_BACKOFF_SECONDS)
                    continue
                if not error.charge_possible:
                    _release_no_charge(reservation_id)
                checkpoint()
                raise RenditionFailure(f"translation_{error.code}", error.message) from error
        assert result is not None
        _settle(
            reservation_id, None, usage=usage, provider=google_translation.PROVIDER_KEY,
            quantity=chars, unit="character",
        )
        for segment, translated in zip(batch, result.texts, strict=True):
            done.setdefault(segment.paragraph_index, []).append(translated)
            if len(done[segment.paragraph_index]) == pieces_needed[segment.paragraph_index]:
                complete(segment.paragraph_index)
        checkpoint()
    for page in pages:
        _apply_translation_page_status(page)
    return False


def _finish_translation(
    session: Session,
    job: _JobRef,
    rendition_id: str,
    *,
    pages: list[dict[str, Any]],
    model: str,
    company_id: str,
    matter_id: str,
    title: str,
    version: int,
    source_language: str,
    target_language: str,
) -> None:
    job_id = job.id
    generated_at = utcnow()
    pdf_bytes = render_translation_pdf(
        title=title,
        source_language=LANGUAGE_NAMES.get(source_language, source_language),
        target_language=LANGUAGE_NAMES.get(target_language, target_language),
        model=model,
        version=version,
        generated_at=generated_at,
        pages=pages,
    )
    # Quota check in its own short transaction, before the object is written.
    session.rollback()
    previous = session.scalar(
        select(MatterAttachmentRendition.output_size_bytes).where(
            MatterAttachmentRendition.id == rendition_id
        )
    )
    try:
        assert_storage_quota_allows_upload(
            session,
            company_id=company_id,
            matter_id=matter_id,
            incoming_size_bytes=len(pdf_bytes),
            replaced_size_bytes=int(previous or 0),
        )
    except StorageQuotaExceeded as exc:
        session.rollback()
        raise RenditionFailure(
            "storage_quota_exceeded",
            "The workspace storage quota is full; the translation is kept and the PDF "
            "can be generated on retry.",
        ) from exc
    session.rollback()
    try:
        stored = persist_workspace_attachment(
            company_id=company_id,
            workspace_id=matter_id,
            attachment_id=rendition_id,
            filename="translation.pdf",
            stream=io.BytesIO(pdf_bytes),
        )
    except Exception as exc:  # storage backends raise several types
        logger.warning("translation PDF storage failed for rendition=%s", rendition_id)
        raise RenditionFailure(
            "storage_failed",
            "The translated PDF could not be saved; the translation is kept. Retry to save it.",
        ) from exc

    total_chars = sum(int(page.get("char_count") or 0) for page in pages)

    def mutate(rendition: MatterAttachmentRendition) -> None:
        # The preflight above released its Company lock before storage I/O.
        # Admit again under the Company fence this transaction already holds,
        # so concurrent publishes cannot jointly exceed the quota.
        try:
            assert_storage_quota_allows_upload(
                session,
                company_id=company_id,
                matter_id=matter_id,
                incoming_size_bytes=stored.size_bytes,
                replaced_size_bytes=int(rendition.output_size_bytes or 0),
            )
        except StorageQuotaExceeded as exc:
            raise RenditionFailure(
                "storage_quota_exceeded",
                "The workspace storage quota is full; the translation is kept and the PDF "
                "can be generated on retry.",
            ) from exc
        rendition.pages_json = json.dumps(pages, ensure_ascii=False)
        _apply_counts(rendition, pages)
        rendition.model = model
        rendition.provider = google_translation.PROVIDER_KEY
        rendition.output_storage_key = stored.storage_key
        rendition.output_size_bytes = stored.size_bytes
        rendition.output_sha256 = stored.sha256_hex
        rendition.completed_at = generated_at
        rendition.status = (
            RenditionStatus.REVIEW_REQUIRED
            if rendition.pages_review or rendition.pages_failed
            else RenditionStatus.TRANSLATION_COMPLETED
        )
        rendition.error_code = None
        rendition.error_message = None
        _set_job_done(
            session, job_id, status=DocumentProcessingJobStatus.COMPLETED, chars=total_chars,
        )
        _record(
            session,
            company_id=rendition.company_id,
            matter_id=rendition.matter_id,
            rendition_id=rendition.id,
            action="matter_attachment.translation_completed",
            title="Translation finished",
            detail=(
                f"Version {rendition.version}: {rendition.pages_ok} pages clean, "
                f"{rendition.pages_review} flagged for review, "
                f"{rendition.pages_failed} unreadable in the source."
            ),
            metadata={
                "attachment_id": rendition.attachment_id,
                "model": model,
                "target_language": rendition.target_language,
                "pages_review": rendition.pages_review,
            },
        )

    try:
        _persist(session, rendition_id=rendition_id, mutate=mutate)
    except Exception:
        # Never leave a stored PDF that no committed record points to.
        session.rollback()
        try:
            delete_stored_document(stored.storage_key)
        except Exception:  # pragma: no cover - best-effort cleanup
            logger.warning("orphan translation PDF cleanup failed for %s", rendition_id)
        raise


def register_rendition_processors() -> None:
    """Register the OCR/translation job processor with document_jobs (idempotent).

    Entry points call this explicitly; document_jobs never imports this module.
    """

    register_document_target_processor(
        (OCR_TARGET_TYPE, TRANSLATION_TARGET_TYPE), process_rendition_job,
    )


__all__ = [
    "RenditionFailure",
    "build_batch_pdf",
    "inspect_pdf",
    "process_rendition_job",
    "register_rendition_processors",
    "sarvam_client",
    "translation_client",
    "usable_native_text",
    "validate_ocr_page",
]
