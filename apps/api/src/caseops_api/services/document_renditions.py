"""Matter Documents "OCR & Translate": request, read, review and download.

Every read and write resolves the Matter through the canonical visibility
gate (tenant, team scope, ethical walls) before touching an attachment or a
rendition, and denied callers get the same opaque 404 as the download route.
Paid provider work runs later in the document-processing worker; this module
only records the request and queues it on the existing job queue.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.document_rendition_models import (
    ACTIVE_RENDITION_STATUSES,
    MatterAttachmentRendition,
    RenditionKind,
    RenditionReviewStatus,
    RenditionStatus,
)
from caseops_api.db.models import (
    CompanyMembership,
    DocumentProcessingTargetType,
    Matter,
    MatterAttachment,
    ProviderCostCategory,
    utcnow,
)
from caseops_api.schemas.document_renditions import (
    SUPPORTED_TRANSLATION_PAIRS,
    AttachmentRenditionsResponse,
    LanguagePair,
    MatterRenditionsResponse,
    ProviderReadiness,
    RenditionBlock,
    RenditionCreateRequest,
    RenditionDetail,
    RenditionMutationResponse,
    RenditionPage,
    RenditionParagraph,
    RenditionReviewRequest,
    RenditionSummary,
    TranslationCreateRequest,
)
from caseops_api.services import google_translation, sarvam_document_ai
from caseops_api.services.audit import record_from_context
from caseops_api.services.document_jobs import enqueue_processing_job
from caseops_api.services.document_storage import resolve_storage_path
from caseops_api.services.matters import (
    _append_activity,
    _assert_matter_not_disposed,
    _get_matter_model,
    _lock_matter_mutation_actor,
)
from caseops_api.services.provider_costs import verified_actual_cost_minor
from caseops_api.services.session_context import SessionContext

OCR_TARGET_TYPE = DocumentProcessingTargetType.MATTER_ATTACHMENT_OCR.value
TRANSLATION_TARGET_TYPE = DocumentProcessingTargetType.MATTER_ATTACHMENT_TRANSLATION.value
RENDITION_TARGET_TYPES = frozenset({OCR_TARGET_TYPE, TRANSLATION_TARGET_TYPE})
OCR_LANGUAGES = ("en", "hi", "mr", "gu", "ta", "te", "kn", "bn", "ml", "pa", "od", "ur", "as")
TRANSLATION_COST_CATEGORY = ProviderCostCategory.TRANSLATION_CHARACTERS
LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "gu": "Gujarati",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "bn": "Bengali",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "od": "Odia",
    "ur": "Urdu",
    "as": "Assamese",
}
# Extension -> accepted declared content types (images and PDFs only).
SUPPORTED_SOURCE_TYPES: dict[str, frozenset[str]] = {
    "pdf": frozenset({"application/pdf"}),
    "png": frozenset({"image/png"}),
    "jpg": frozenset({"image/jpeg", "image/jpg", "image/pjpeg"}),
    "jpeg": frozenset({"image/jpeg", "image/jpg", "image/pjpeg"}),
}
UPLOAD_CAPABILITY = "documents:upload"
REVIEW_CAPABILITY = "documents:manage"


def source_format(attachment: MatterAttachment) -> str | None:
    """Return ``pdf`` or ``image`` for supported sources, else ``None``."""

    name = attachment.original_filename or ""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    accepted = SUPPORTED_SOURCE_TYPES.get(suffix)
    if accepted is None:
        return None
    declared = (attachment.content_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in accepted and declared != "application/octet-stream":
        return None
    return "pdf" if suffix == "pdf" else "image"


def ocr_provider_unavailable_reason(session: Session) -> str | None:
    settings = get_settings()
    if not settings.sarvam_document_ai_enabled:
        return "provider_disabled"
    if not settings.sarvam_api_key:
        return "credentials_missing"
    if verified_actual_cost_minor(
        session,
        category=ProviderCostCategory.OCR_PAGE,
        provider=sarvam_document_ai.PROVIDER_KEY,
    ) is None:
        return "cost_not_verified"
    return None


def translation_unavailable_reason(session: Session) -> str | None:
    settings = get_settings()
    if not settings.google_translation_enabled:
        return "provider_disabled"
    if not (settings.google_translation_project_id or settings.gcp_project_id):
        return "credentials_missing"
    if verified_actual_cost_minor(
        session,
        category=TRANSLATION_COST_CATEGORY,
        provider=google_translation.PROVIDER_KEY,
    ) is None:
        return "cost_not_verified"
    return None


def translation_project_id() -> str | None:
    settings = get_settings()
    return settings.google_translation_project_id or settings.gcp_project_id


def _readiness(session: Session, attachment: MatterAttachment) -> ProviderReadiness:
    ocr_reason = ocr_provider_unavailable_reason(session)
    translation_reason = translation_unavailable_reason(session)
    permitted = not attachment.native_local_processing_only
    if not permitted:
        ocr_reason = ocr_reason or "third_party_processing_not_permitted"
        translation_reason = "third_party_processing_not_permitted"
    return ProviderReadiness(
        ocr_provider_available=ocr_reason is None,
        ocr_unavailable_reason=ocr_reason,
        translation_available=translation_reason is None,
        translation_unavailable_reason=translation_reason,
        third_party_processing_permitted=permitted,
        ocr_languages=list(OCR_LANGUAGES),
        translation_pairs=[
            LanguagePair(source=source, target=target)
            for source, target in sorted(SUPPORTED_TRANSLATION_PAIRS)
        ],
    )


def retry_allowed(rendition: MatterAttachmentRendition) -> bool:
    if rendition.status == RenditionStatus.FAILED:
        return True
    return (
        rendition.kind == RenditionKind.OCR
        and rendition.status == RenditionStatus.REVIEW_REQUIRED
        and rendition.pages_failed > 0
    )


def _membership_names(session: Session, ids: set[str]) -> dict[str, str]:
    ids = {item for item in ids if item}
    if not ids:
        return {}
    rows = session.scalars(
        select(CompanyMembership).where(CompanyMembership.id.in_(ids))
    ).all()
    names: dict[str, str] = {}
    for membership in rows:
        user = membership.user
        names[membership.id] = (
            (getattr(user, "full_name", None) or getattr(user, "email", None) or "Member")
            if user is not None else "Member"
        )
    return names


def _summary(
    rendition: MatterAttachmentRendition, names: dict[str, str],
) -> RenditionSummary:
    return RenditionSummary(
        id=rendition.id,
        company_id=rendition.company_id,
        matter_id=rendition.matter_id,
        attachment_id=rendition.attachment_id,
        source_rendition_id=rendition.source_rendition_id,
        kind=rendition.kind,
        version=rendition.version,
        status=rendition.status,
        review_status=rendition.review_status,
        source_language=rendition.source_language,
        target_language=rendition.target_language,
        chain_target_language=rendition.chain_target_language,
        provider=rendition.provider,
        model=rendition.model,
        page_count=rendition.page_count,
        pages_ok=rendition.pages_ok,
        pages_review=rendition.pages_review,
        pages_failed=rendition.pages_failed,
        error_code=rendition.error_code,
        error_message=rendition.error_message,
        has_output_file=bool(rendition.output_storage_key),
        output_size_bytes=rendition.output_size_bytes,
        requested_by_name=names.get(rendition.requested_by_membership_id or ""),
        reviewed_by_name=names.get(rendition.reviewed_by_membership_id or ""),
        reviewed_at=rendition.reviewed_at,
        review_note=rendition.review_note,
        retry_allowed=retry_allowed(rendition),
        created_at=rendition.created_at,
        updated_at=rendition.updated_at,
        completed_at=rendition.completed_at,
    )


def _summaries(
    session: Session, renditions: list[MatterAttachmentRendition],
) -> list[RenditionSummary]:
    ids: set[str] = set()
    for rendition in renditions:
        ids.update(
            item for item in (
                rendition.requested_by_membership_id, rendition.reviewed_by_membership_id,
            ) if item
        )
    names = _membership_names(session, ids)
    return [_summary(rendition, names) for rendition in renditions]


def load_pages(rendition: MatterAttachmentRendition) -> list[dict[str, Any]]:
    if not rendition.pages_json:
        return []
    try:
        pages = json.loads(rendition.pages_json)
    except ValueError:
        return []
    return [page for page in pages if isinstance(page, dict)] if isinstance(pages, list) else []


def _page_model(page: dict[str, Any]) -> RenditionPage:
    return RenditionPage(
        page=int(page.get("page", 0)),
        source=page.get("source") or "none",
        status=page.get("status") or "failed",
        reasons=list(page.get("reasons") or []),
        text=page.get("text"),
        char_count=int(page.get("char_count") or 0),
        min_confidence=page.get("min_confidence"),
        blocks=[
            RenditionBlock(
                tag=str(block.get("tag") or "paragraph"),
                text=str(block.get("text") or ""),
                confidence=block.get("confidence"),
            )
            for block in page.get("blocks") or []
            if isinstance(block, dict)
        ],
        paragraphs=[
            RenditionParagraph(**paragraph)
            for paragraph in page.get("paragraphs") or []
            if isinstance(paragraph, dict)
        ],
    )


def _matter_and_attachment(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    lock_for_update: bool = False,
) -> tuple[Matter, MatterAttachment]:
    matter = _get_matter_model(
        session, context=context, matter_id=matter_id, lock_for_update=lock_for_update,
    )
    attachment = session.scalar(
        select(MatterAttachment).where(
            MatterAttachment.id == attachment_id, MatterAttachment.matter_id == matter.id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    return matter, attachment


def _rendition_for(
    session: Session,
    *,
    context: SessionContext,
    attachment: MatterAttachment,
    rendition_id: str,
) -> MatterAttachmentRendition:
    rendition = session.scalar(
        select(MatterAttachmentRendition).where(
            MatterAttachmentRendition.id == rendition_id,
            MatterAttachmentRendition.company_id == context.company.id,
            MatterAttachmentRendition.attachment_id == attachment.id,
        )
    )
    if rendition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="OCR or translation version not found.",
        )
    return rendition


def _active(
    session: Session, *, attachment_id: str, kind: str,
) -> MatterAttachmentRendition | None:
    return session.scalar(
        select(MatterAttachmentRendition).where(
            MatterAttachmentRendition.attachment_id == attachment_id,
            MatterAttachmentRendition.kind == kind,
            MatterAttachmentRendition.status.in_([s.value for s in ACTIVE_RENDITION_STATUSES]),
        )
    )


def _next_version(session: Session, *, attachment_id: str, kind: str) -> int:
    current = session.scalar(
        select(func.max(MatterAttachmentRendition.version)).where(
            MatterAttachmentRendition.attachment_id == attachment_id,
            MatterAttachmentRendition.kind == kind,
        )
    )
    return int(current or 0) + 1


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"type": code, "code": code, "message": message},
    )


def _unsupported_source() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail={
            "type": "unsupported_format",
            "code": "unsupported_format",
            "message": "OCR & Translate supports PDF, JPG, JPEG and PNG documents only.",
        },
    )


def _assert_translation_allowed(
    session: Session, attachment: MatterAttachment, *, source: str, target: str,
) -> None:
    if (source, target) not in SUPPORTED_TRANSLATION_PAIRS:
        raise _conflict(
            "unsupported_language_pair",
            f"Translation from {LANGUAGE_NAMES[source]} to {LANGUAGE_NAMES[target]} "
            "is not supported.",
        )
    if attachment.native_local_processing_only:
        raise _conflict(
            "third_party_processing_not_permitted",
            "This document was uploaded for on-device processing only and cannot be sent "
            "to a translation provider.",
        )
    reason = translation_unavailable_reason(session)
    if reason is not None:
        raise _conflict(
            "translation_unavailable",
            {
                "provider_disabled": "Translation is not enabled for this workspace.",
                "credentials_missing": "Translation is not configured on the server.",
                "cost_not_verified": (
                    "Translation pricing has not been verified, so no paid call can be made."
                ),
            }[reason],
        )


def _queue(
    session: Session,
    *,
    context: SessionContext,
    attachment: MatterAttachment,
    rendition: MatterAttachmentRendition,
    action: str,
) -> str:
    job = enqueue_processing_job(
        session,
        company_id=context.company.id,
        requested_by_membership_id=context.membership.id,
        target_type=(
            OCR_TARGET_TYPE if rendition.kind == RenditionKind.OCR else TRANSLATION_TARGET_TYPE
        ),
        attachment_id=rendition.id,
        action=action,
        no_paid_providers=attachment.native_local_processing_only,
    )
    rendition.processing_job_id = job.id
    return job.id


def _commit_or_existing(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    kind: str,
) -> MatterAttachmentRendition | None:
    """Commit; a concurrent duplicate request loses to the open run."""

    try:
        session.commit()
        return None
    except IntegrityError:
        session.rollback()
        _, attachment = _matter_and_attachment(
            session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        )
        existing = _active(session, attachment_id=attachment.id, kind=kind)
        if existing is None:
            raise
        return existing


def create_ocr_rendition(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    payload: RenditionCreateRequest,
) -> tuple[RenditionMutationResponse, str | None]:
    _lock_matter_mutation_actor(session, context=context, required_capability=UPLOAD_CAPABILITY)
    matter, attachment = _matter_and_attachment(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        lock_for_update=True,
    )
    _assert_matter_not_disposed(matter, operation="run OCR")
    if source_format(attachment) is None:
        raise _unsupported_source()
    if payload.target_language is not None:
        _assert_translation_allowed(
            session, attachment, source=payload.source_language, target=payload.target_language,
        )
    existing = _active(session, attachment_id=attachment.id, kind=RenditionKind.OCR)
    if existing is not None:
        return RenditionMutationResponse(
            created=False, rendition=_summaries(session, [existing])[0],
        ), None
    rendition = MatterAttachmentRendition(
        company_id=context.company.id,
        matter_id=matter.id,
        attachment_id=attachment.id,
        kind=RenditionKind.OCR,
        version=_next_version(session, attachment_id=attachment.id, kind=RenditionKind.OCR),
        status=RenditionStatus.QUEUED,
        review_status=RenditionReviewStatus.UNREVIEWED,
        source_language=payload.source_language,
        chain_target_language=payload.target_language,
        source_sha256=attachment.sha256_hex,
        requested_by_membership_id=context.membership.id,
    )
    session.add(rendition)
    session.flush()
    job_id = _queue(
        session, context=context, attachment=attachment, rendition=rendition, action="ocr",
    )
    target = (
        f" and translation to {LANGUAGE_NAMES[payload.target_language]}"
        if payload.target_language else ""
    )
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="attachment_ocr_requested",
        title="OCR requested",
        detail=f"{attachment.original_filename}: OCR version {rendition.version}{target} queued.",
    )
    record_from_context(
        session,
        context,
        action="matter_attachment.ocr_requested",
        target_type="matter_attachment_rendition",
        target_id=rendition.id,
        matter_id=matter.id,
        metadata={
            "attachment_id": attachment.id,
            "version": rendition.version,
            "source_language": payload.source_language,
            "target_language": payload.target_language,
        },
    )
    rendition_id = rendition.id
    existing = _commit_or_existing(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        kind=RenditionKind.OCR,
    )
    if existing is not None:
        return RenditionMutationResponse(
            created=False, rendition=_summaries(session, [existing])[0],
        ), None
    created = session.get(MatterAttachmentRendition, rendition_id)
    return (
        RenditionMutationResponse(created=True, rendition=_summaries(session, [created])[0]),
        job_id,
    )


def queue_translation(
    session: Session,
    *,
    company_id: str,
    attachment: MatterAttachment,
    source: MatterAttachmentRendition,
    target_language: str,
    requested_by_membership_id: str | None,
) -> MatterAttachmentRendition:
    """Create a queued translation version of a finished OCR version (no commit)."""

    return MatterAttachmentRendition(
        company_id=company_id,
        matter_id=attachment.matter_id,
        attachment_id=attachment.id,
        source_rendition_id=source.id,
        kind=RenditionKind.TRANSLATION,
        version=_next_version(
            session, attachment_id=attachment.id, kind=RenditionKind.TRANSLATION,
        ),
        status=RenditionStatus.QUEUED,
        review_status=RenditionReviewStatus.UNREVIEWED,
        source_language=source.source_language,
        target_language=target_language,
        provider=google_translation.PROVIDER_KEY,
        source_sha256=source.source_sha256,
        requested_by_membership_id=requested_by_membership_id,
    )


def create_translation_rendition(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    ocr_rendition_id: str,
    payload: TranslationCreateRequest,
) -> tuple[RenditionMutationResponse, str | None]:
    _lock_matter_mutation_actor(session, context=context, required_capability=UPLOAD_CAPABILITY)
    matter, attachment = _matter_and_attachment(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        lock_for_update=True,
    )
    _assert_matter_not_disposed(matter, operation="translate a document")
    source = _rendition_for(
        session, context=context, attachment=attachment, rendition_id=ocr_rendition_id,
    )
    if source.kind != RenditionKind.OCR or source.status not in {
        RenditionStatus.OCR_COMPLETED, RenditionStatus.REVIEW_REQUIRED,
    } or source.pages_ok + source.pages_review == 0:
        raise _conflict(
            "ocr_not_ready", "Translate from a finished OCR version that has readable pages.",
        )
    _assert_translation_allowed(
        session, attachment, source=source.source_language, target=payload.target_language,
    )
    existing = _active(session, attachment_id=attachment.id, kind=RenditionKind.TRANSLATION)
    if existing is not None:
        return RenditionMutationResponse(
            created=False, rendition=_summaries(session, [existing])[0],
        ), None
    rendition = queue_translation(
        session,
        company_id=context.company.id,
        attachment=attachment,
        source=source,
        target_language=payload.target_language,
        requested_by_membership_id=context.membership.id,
    )
    session.add(rendition)
    session.flush()
    job_id = _queue(
        session, context=context, attachment=attachment, rendition=rendition, action="translate",
    )
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="attachment_translation_requested",
        title="Translation requested",
        detail=(
            f"{attachment.original_filename}: translation version {rendition.version} to "
            f"{LANGUAGE_NAMES[payload.target_language]} queued."
        ),
    )
    record_from_context(
        session,
        context,
        action="matter_attachment.translation_requested",
        target_type="matter_attachment_rendition",
        target_id=rendition.id,
        matter_id=matter.id,
        metadata={
            "attachment_id": attachment.id,
            "ocr_rendition_id": source.id,
            "version": rendition.version,
            "source_language": source.source_language,
            "target_language": payload.target_language,
        },
    )
    rendition_id = rendition.id
    existing = _commit_or_existing(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        kind=RenditionKind.TRANSLATION,
    )
    if existing is not None:
        return RenditionMutationResponse(
            created=False, rendition=_summaries(session, [existing])[0],
        ), None
    created = session.get(MatterAttachmentRendition, rendition_id)
    return (
        RenditionMutationResponse(created=True, rendition=_summaries(session, [created])[0]),
        job_id,
    )


def retry_rendition(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
) -> tuple[RenditionMutationResponse, str | None]:
    _lock_matter_mutation_actor(session, context=context, required_capability=UPLOAD_CAPABILITY)
    matter, attachment = _matter_and_attachment(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        lock_for_update=True,
    )
    _assert_matter_not_disposed(matter, operation="retry OCR or translation")
    rendition = _rendition_for(
        session, context=context, attachment=attachment, rendition_id=rendition_id,
    )
    if rendition.status in ACTIVE_RENDITION_STATUSES:
        return RenditionMutationResponse(
            created=False, rendition=_summaries(session, [rendition])[0],
        ), None
    if not retry_allowed(rendition):
        raise _conflict(
            "retry_not_allowed", "Only failed or partly failed versions can be retried.",
        )
    if rendition.kind == RenditionKind.TRANSLATION:
        if rendition.source_rendition_id is None:
            raise _conflict("ocr_not_ready", "The OCR version this translation used is gone.")
        _assert_translation_allowed(
            session,
            attachment,
            source=rendition.source_language,
            target=rendition.target_language or "",
        )
    if _active(session, attachment_id=attachment.id, kind=rendition.kind) is not None:
        raise _conflict("already_running", "Another run of this kind is already in progress.")
    rendition.status = RenditionStatus.QUEUED
    rendition.error_code = None
    rendition.error_message = None
    rendition.review_status = RenditionReviewStatus.UNREVIEWED
    rendition.reviewed_at = None
    rendition.reviewed_by_membership_id = None
    rendition.review_note = None
    job_id = _queue(
        session, context=context, attachment=attachment, rendition=rendition, action="retry",
    )
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="attachment_rendition_retry_requested",
        title="OCR retry requested" if rendition.kind == RenditionKind.OCR
        else "Translation retry requested",
        detail=f"{attachment.original_filename}: version {rendition.version} queued again.",
    )
    record_from_context(
        session,
        context,
        action="matter_attachment.rendition_retry_requested",
        target_type="matter_attachment_rendition",
        target_id=rendition.id,
        matter_id=matter.id,
        metadata={"attachment_id": attachment.id, "kind": rendition.kind},
    )
    existing = _commit_or_existing(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        kind=rendition.kind,
    )
    if existing is not None:
        return RenditionMutationResponse(
            created=False, rendition=_summaries(session, [existing])[0],
        ), None
    refreshed = session.get(MatterAttachmentRendition, rendition_id)
    return RenditionMutationResponse(
        created=True, rendition=_summaries(session, [refreshed])[0],
    ), job_id


def review_rendition(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
    payload: RenditionReviewRequest,
) -> RenditionSummary:
    _lock_matter_mutation_actor(session, context=context, required_capability=REVIEW_CAPABILITY)
    matter, attachment = _matter_and_attachment(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        lock_for_update=True,
    )
    rendition = _rendition_for(
        session, context=context, attachment=attachment, rendition_id=rendition_id,
    )
    if rendition.status in ACTIVE_RENDITION_STATUSES or rendition.status == RenditionStatus.FAILED:
        raise _conflict(
            "review_not_allowed", "Only finished OCR or translation versions can be reviewed.",
        )
    if (
        payload.review_status == RenditionReviewStatus.REVIEWED
        and rendition.pages_failed
        and not (payload.note and payload.note.strip())
    ):
        raise _conflict(
            "review_note_required",
            "Some pages could not be read. Add a note recording how they were checked.",
        )
    rendition.review_status = payload.review_status
    rendition.reviewed_by_membership_id = context.membership.id
    rendition.reviewed_at = utcnow()
    rendition.review_note = (payload.note or "").strip() or None
    _append_activity(
        session,
        matter_id=matter.id,
        actor_membership_id=context.membership.id,
        event_type="attachment_rendition_reviewed",
        title=(
            "Translation reviewed" if rendition.kind == RenditionKind.TRANSLATION
            else "OCR text reviewed"
        ) if payload.review_status == RenditionReviewStatus.REVIEWED else "Correction requested",
        detail=f"{attachment.original_filename}: version {rendition.version}.",
    )
    record_from_context(
        session,
        context,
        action="matter_attachment.rendition_reviewed",
        target_type="matter_attachment_rendition",
        target_id=rendition.id,
        matter_id=matter.id,
        metadata={
            "attachment_id": attachment.id,
            "kind": rendition.kind,
            "review_status": payload.review_status,
        },
    )
    session.commit()
    refreshed = session.get(MatterAttachmentRendition, rendition_id)
    return _summaries(session, [refreshed])[0]


def get_attachment_renditions(
    session: Session, *, context: SessionContext, matter_id: str, attachment_id: str,
) -> AttachmentRenditionsResponse:
    _, attachment = _matter_and_attachment(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
    )
    renditions = list(
        session.scalars(
            select(MatterAttachmentRendition)
            .where(
                MatterAttachmentRendition.attachment_id == attachment.id,
                MatterAttachmentRendition.company_id == context.company.id,
            )
            .order_by(
                MatterAttachmentRendition.created_at.desc(),
                MatterAttachmentRendition.version.desc(),
            )
        )
    )
    return AttachmentRenditionsResponse(
        attachment_id=attachment.id,
        providers=_readiness(session, attachment),
        renditions=_summaries(session, renditions),
    )


def list_matter_renditions(
    session: Session, *, context: SessionContext, matter_id: str,
) -> MatterRenditionsResponse:
    """Latest OCR and latest translation version per attachment in a matter."""

    matter = _get_matter_model(session, context=context, matter_id=matter_id)
    rows = session.scalars(
        select(MatterAttachmentRendition)
        .where(
            MatterAttachmentRendition.matter_id == matter.id,
            MatterAttachmentRendition.company_id == context.company.id,
        )
        .order_by(MatterAttachmentRendition.version.desc())
    ).all()
    latest: dict[tuple[str, str], MatterAttachmentRendition] = {}
    for row in rows:
        latest.setdefault((row.attachment_id, row.kind), row)
    return MatterRenditionsResponse(
        matter_id=matter.id, renditions=_summaries(session, list(latest.values())),
    )


def get_rendition_detail(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
) -> RenditionDetail:
    _, attachment = _matter_and_attachment(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
    )
    rendition = _rendition_for(
        session, context=context, attachment=attachment, rendition_id=rendition_id,
    )
    summary = _summaries(session, [rendition])[0]
    pages = [_page_model(page) for page in load_pages(rendition)]
    return RenditionDetail(
        **summary.model_dump(),
        attachment_filename=attachment.original_filename,
        failed_pages=[page.page for page in pages if page.status == "failed"],
        review_pages=[page.page for page in pages if page.status == "review"],
        pages=pages,
    )


def get_rendition_download(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
) -> tuple[str, str]:
    matter, attachment = _matter_and_attachment(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
    )
    rendition = _rendition_for(
        session, context=context, attachment=attachment, rendition_id=rendition_id,
    )
    if not rendition.output_storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This version has no translated PDF yet.",
        )
    path = resolve_storage_path(rendition.output_storage_key)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The translated PDF is no longer available.",
        )
    record_from_context(
        session,
        context,
        action="matter_attachment.translation_downloaded",
        target_type="matter_attachment_rendition",
        target_id=rendition.id,
        matter_id=matter.id,
        metadata={"attachment_id": attachment.id, "version": rendition.version},
    )
    session.commit()
    stem = Path(attachment.original_filename).stem or "document"
    filename = f"{stem}.{rendition.target_language}.translation-v{rendition.version}.pdf"
    return str(path), filename


__all__ = [
    "OCR_TARGET_TYPE",
    "RENDITION_TARGET_TYPES",
    "TRANSLATION_TARGET_TYPE",
    "create_ocr_rendition",
    "create_translation_rendition",
    "get_attachment_renditions",
    "get_rendition_detail",
    "get_rendition_download",
    "list_matter_renditions",
    "load_pages",
    "ocr_provider_unavailable_reason",
    "queue_translation",
    "retry_rendition",
    "review_rendition",
    "source_format",
    "translation_project_id",
    "translation_unavailable_reason",
]
