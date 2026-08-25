from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    DocumentProcessingAction,
    DocumentProcessingTargetType,
    IpDeadline,
    IpDocketEvent,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyAlias,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpProceeding,
    TrademarkApplication,
    utcnow,
)
from caseops_api.schemas.ip_documents import (
    IpDocumentAddLinksRequest,
    IpDocumentAliasImportConflict,
    IpDocumentAliasImportRequest,
    IpDocumentAliasImportResponse,
    IpDocumentBulkApplyRequest,
    IpDocumentBulkItem,
    IpDocumentBulkPreviewItem,
    IpDocumentBulkPreviewRequest,
    IpDocumentBulkPreviewResponse,
    IpDocumentDuplicateCandidate,
    IpDocumentLinkRecord,
    IpDocumentLinkTarget,
    IpDocumentListResponse,
    IpDocumentNewVersionMetadata,
    IpDocumentPolicyActionRequest,
    IpDocumentPolicyActionResponse,
    IpDocumentPolicyResponse,
    IpDocumentRecord,
    IpDocumentStateTransitionRequest,
    IpDocumentUploadMetadata,
    IpDocumentUploadResponse,
    IpDocumentVersionRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.document_jobs import (
    enqueue_processing_job,
    load_latest_processing_jobs,
)
from caseops_api.services.document_storage import (
    delete_stored_document,
    persist_workspace_attachment,
)
from caseops_api.services.file_security import verify_upload
from caseops_api.services.ip_documents import (
    TAXONOMY_VERSION,
    _normalize_alias,
    preview_ip_document_name,
)
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.session_context import SessionContext
from caseops_api.services.storage_governance import assert_storage_quota_allows_upload
from caseops_api.services.virus_scan import reject_if_infected

LOW_OCR_QUALITY_THRESHOLD = 0.65
_TARGET_MODELS = {
    "application": TrademarkApplication,
    "proceeding": IpProceeding,
    "event": IpDocketEvent,
    "deadline": IpDeadline,
}
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"review", "rejected"},
    "review": {"draft", "approved", "rejected"},
    "approved": {"filed", "served", "accepted", "rejected", "superseded"},
    "filed": {"served", "accepted", "rejected", "superseded"},
    "served": {"accepted", "rejected", "superseded"},
    "accepted": {"superseded"},
    "rejected": {"draft", "superseded"},
    "superseded": set(),
}


def _require_document_capability(
    session: Session,
    *,
    context: SessionContext,
    capability: str,
) -> None:
    if not membership_has_capability(session, context.membership, capability):
        raise HTTPException(status_code=403, detail=f"Capability {capability!r} is required.")


def _taxonomy_or_404(
    session: Session,
    *,
    company_id: str,
    key: str,
) -> IpDocumentTaxonomyEntry:
    row = session.scalar(
        select(IpDocumentTaxonomyEntry).where(
            IpDocumentTaxonomyEntry.company_id == company_id,
            IpDocumentTaxonomyEntry.key == key.strip().casefold(),
            IpDocumentTaxonomyEntry.is_active.is_(True),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Active document taxonomy entry not found.")
    return row


def _document_or_404(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    for_update: bool = False,
) -> IpDocument:
    stmt = select(IpDocument).where(
        IpDocument.id == document_id,
        IpDocument.company_id == context.company.id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    document = session.scalar(stmt)
    if document is None:
        raise HTTPException(status_code=404, detail="IP document not found.")
    _assert_document_targets_accessible(session, context=context, document_id=document.id)
    return document


def _version_or_404(
    session: Session,
    *,
    document: IpDocument,
    version: int,
    for_update: bool = False,
) -> IpDocumentVersion:
    stmt = select(IpDocumentVersion).where(
        IpDocumentVersion.company_id == document.company_id,
        IpDocumentVersion.document_id == document.id,
        IpDocumentVersion.version == version,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = session.scalar(stmt)
    if row is None:
        raise HTTPException(status_code=404, detail="IP document version not found.")
    return row


def _target_docket_id(
    session: Session,
    *,
    company_id: str,
    target: IpDocumentLinkTarget,
) -> str:
    if target.target_type == "docket":
        return target.target_id
    model = _TARGET_MODELS[target.target_type]
    row = session.scalar(
        select(model).where(model.id == target.target_id, model.company_id == company_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP document link target not found.")
    return str(row.docket_id)


def _validate_target(
    session: Session,
    *,
    context: SessionContext,
    target: IpDocumentLinkTarget,
) -> None:
    docket_id = _target_docket_id(session, company_id=context.company.id, target=target)
    _docket_or_404(session, context=context, docket_id=docket_id)


def _assert_document_targets_accessible(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
) -> None:
    links = list(
        session.scalars(
            select(IpDocumentLink).where(
                IpDocumentLink.company_id == context.company.id,
                IpDocumentLink.document_id == document_id,
            )
        ).all()
    )
    for row in links:
        _validate_target(
            session,
            context=context,
            target=IpDocumentLinkTarget(target_type=row.target_type, target_id=row.target_id),
        )


def assert_ip_document_access(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
) -> None:
    """Authorize every linked target before exposing document/source bytes."""

    _assert_document_targets_accessible(
        session,
        context=context,
        document_id=document_id,
    )


def _policy(document: IpDocument, version: IpDocumentVersion) -> IpDocumentPolicyResponse:
    reasons: list[str] = []
    if document.is_privileged:
        reasons.append(
            "Attorney-client privileged documents are restricted from AI, portal, "
            "export, and notification content."
        )
    if document.confidentiality != "internal":
        reasons.append(
            f"Confidentiality label {document.confidentiality!r} restricts downstream disclosure."
        )
    low_quality = (
        version.ocr_quality_score is not None
        and version.ocr_quality_score < LOW_OCR_QUALITY_THRESHOLD
    )
    if low_quality:
        reasons.append("OCR/extraction quality is below the legal-use threshold.")
    if version.processing_status != "indexed":
        reasons.append("Document processing is not complete and indexed.")
    disclosure_allowed = not document.is_privileged and document.confidentiality == "internal"
    return IpDocumentPolicyResponse(
        ai_retrieval_allowed=(
            disclosure_allowed and version.processing_status == "indexed" and not low_quality
        ),
        portal_share_allowed=disclosure_allowed,
        export_allowed=disclosure_allowed,
        notification_content_allowed=disclosure_allowed,
        reasons=reasons,
    )


def _serialize_document(
    session: Session,
    *,
    document: IpDocument,
) -> IpDocumentRecord:
    taxonomy = session.get(IpDocumentTaxonomyEntry, document.taxonomy_entry_id)
    if taxonomy is None or taxonomy.company_id != document.company_id:
        raise HTTPException(status_code=500, detail="Document taxonomy integrity failure.")
    versions = list(
        session.scalars(
            select(IpDocumentVersion)
            .where(
                IpDocumentVersion.company_id == document.company_id,
                IpDocumentVersion.document_id == document.id,
            )
            .order_by(IpDocumentVersion.version.desc())
        ).all()
    )
    jobs = load_latest_processing_jobs(
        session,
        target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
        attachment_ids=[row.id for row in versions],
    )
    links = list(
        session.scalars(
            select(IpDocumentLink)
            .where(
                IpDocumentLink.company_id == document.company_id,
                IpDocumentLink.document_id == document.id,
            )
            .order_by(IpDocumentLink.created_at, IpDocumentLink.id)
        ).all()
    )
    version_records: list[IpDocumentVersionRecord] = []
    for row in versions:
        policy = _policy(document, row)
        version_records.append(
            IpDocumentVersionRecord(
                id=row.id,
                version=row.version,
                original_filename=row.original_filename,
                display_name=row.display_name,
                content_type=row.content_type,
                size_bytes=row.size_bytes,
                sha256_hex=row.sha256_hex,
                processing_status=row.processing_status,
                extracted_char_count=row.extracted_char_count,
                extraction_error=row.extraction_error,
                ocr_quality_score=row.ocr_quality_score,
                low_ocr_quality=(
                    row.ocr_quality_score is not None
                    and row.ocr_quality_score < LOW_OCR_QUALITY_THRESHOLD
                ),
                ai_eligible=policy.ai_retrieval_allowed,
                state=row.state,
                uploaded_by_membership_id=row.uploaded_by_membership_id,
                locked_by_membership_id=row.locked_by_membership_id,
                locked_at=row.locked_at,
                created_at=row.created_at,
                latest_processing_job=jobs.get(row.id),
            )
        )
    return IpDocumentRecord(
        id=document.id,
        taxonomy_key=taxonomy.key,
        taxonomy_label=taxonomy.label,
        title=document.title,
        confidentiality=document.confidentiality,
        is_privileged=document.is_privileged,
        current_version=document.current_version,
        created_by_membership_id=document.created_by_membership_id,
        created_at=document.created_at,
        updated_at=document.updated_at,
        versions=version_records,
        links=[IpDocumentLinkRecord.model_validate(row) for row in links],
    )


def list_ip_documents(
    session: Session,
    *,
    context: SessionContext,
) -> IpDocumentListResponse:
    rows = list(
        session.scalars(
            select(IpDocument)
            .where(IpDocument.company_id == context.company.id)
            .order_by(IpDocument.updated_at.desc(), IpDocument.id)
        ).all()
    )
    visible: list[IpDocumentRecord] = []
    for row in rows:
        try:
            _assert_document_targets_accessible(session, context=context, document_id=row.id)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        visible.append(_serialize_document(session, document=row))
    return IpDocumentListResponse(items=visible, total=len(visible))


def list_linked_ip_documents(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    event_ids: set[str],
    deadline_ids: set[str],
    limit: int = 100,
) -> list[IpDocumentRecord]:
    """Return a bounded set of documents linked to one accessible workflow aggregate."""
    target_filters = [
        (IpDocumentLink.target_type == "docket")
        & (IpDocumentLink.target_id == docket_id)
    ]
    if event_ids:
        target_filters.append(
            (IpDocumentLink.target_type == "event")
            & (IpDocumentLink.target_id.in_(event_ids))
        )
    if deadline_ids:
        target_filters.append(
            (IpDocumentLink.target_type == "deadline")
            & (IpDocumentLink.target_id.in_(deadline_ids))
        )
    rows = list(
        session.scalars(
            select(IpDocument)
            .join(
                IpDocumentLink,
                (IpDocumentLink.document_id == IpDocument.id)
                & (IpDocumentLink.company_id == IpDocument.company_id),
            )
            .where(
                IpDocument.company_id == context.company.id,
                or_(*target_filters),
            )
            .distinct()
            .order_by(IpDocument.updated_at.desc(), IpDocument.id)
            .limit(limit)
        ).all()
    )
    visible: list[IpDocumentRecord] = []
    for row in rows:
        try:
            _assert_document_targets_accessible(session, context=context, document_id=row.id)
        except HTTPException as exc:
            if exc.status_code == 404:
                continue
            raise
        visible.append(_serialize_document(session, document=row))
    return visible


def get_ip_document(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
) -> IpDocumentRecord:
    document = _document_or_404(session, context=context, document_id=document_id, for_update=False)
    return _serialize_document(session, document=document)


def get_ip_document_policy(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
) -> IpDocumentPolicyResponse:
    document = _document_or_404(session, context=context, document_id=document_id)
    version = _version_or_404(session, document=document, version=document.current_version)
    return _policy(document, version)


def authorize_ip_document_action(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    payload: IpDocumentPolicyActionRequest,
) -> IpDocumentPolicyActionResponse:
    policy = get_ip_document_policy(session, context=context, document_id=document_id)
    allowed_by_action = {
        "ai_retrieval": policy.ai_retrieval_allowed,
        "portal_share": policy.portal_share_allowed,
        "export": policy.export_allowed,
        "notification_content": policy.notification_content_allowed,
    }
    allowed = allowed_by_action[payload.action]
    if not allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "ip_document_policy_denied",
                "action": payload.action,
                "reasons": policy.reasons,
            },
        )
    return IpDocumentPolicyActionResponse(
        action=payload.action,
        allowed=True,
        reasons=policy.reasons,
    )


def get_ip_document_version_for_download(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    version_number: int,
) -> IpDocumentVersion:
    document = _document_or_404(session, context=context, document_id=document_id)
    return _version_or_404(session, document=document, version=version_number)


def _existing_display_names(session: Session, *, company_id: str) -> list[str]:
    return list(
        session.scalars(
            select(IpDocumentVersion.display_name).where(IpDocumentVersion.company_id == company_id)
        ).all()
    )


def _create_link(
    session: Session,
    *,
    context: SessionContext,
    document: IpDocument,
    version_id: str | None,
    target: IpDocumentLinkTarget,
) -> IpDocumentLink:
    _validate_target(session, context=context, target=target)
    existing = session.scalar(
        select(IpDocumentLink).where(
            IpDocumentLink.document_id == document.id,
            IpDocumentLink.target_type == target.target_type,
            IpDocumentLink.target_id == target.target_id,
        )
    )
    if existing is not None:
        if version_id is not None and existing.version_id not in {None, version_id}:
            raise HTTPException(
                status_code=409,
                detail={"code": "ip_document_link_version_conflict", "link_id": existing.id},
            )
        return existing
    column_values = {
        f"{name}_id": None for name in ("docket", "application", "proceeding", "event", "deadline")
    }
    column_values[f"{target.target_type}_id"] = target.target_id
    row = IpDocumentLink(
        company_id=context.company.id,
        document_id=document.id,
        version_id=version_id,
        target_type=target.target_type,
        target_id=target.target_id,
        created_by_membership_id=context.membership.id,
        **column_values,
    )
    session.add(row)
    session.flush()
    return row


def upload_ip_document(
    session: Session,
    *,
    context: SessionContext,
    metadata: IpDocumentUploadMetadata,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> tuple[IpDocumentUploadResponse, str | None]:
    _require_document_capability(
        session, context=context, capability="documents:upload"
    )
    verify_upload(filename=filename, content_type=content_type, stream=stream)
    taxonomy = _taxonomy_or_404(session, company_id=context.company.id, key=metadata.taxonomy_key)
    document = IpDocument(
        company_id=context.company.id,
        taxonomy_entry_id=taxonomy.id,
        title=(metadata.title or Path(filename).stem or "Document").strip(),
        confidentiality=metadata.confidentiality,
        is_privileged=metadata.is_privileged,
        current_version=1,
        created_by_membership_id=context.membership.id,
    )
    session.add(document)
    session.flush()
    naming = preview_ip_document_name(
        metadata_to_naming_request(
            metadata,
            version=1,
            filename=filename,
            existing_names=_existing_display_names(session, company_id=context.company.id),
        )
    )
    version = IpDocumentVersion(
        company_id=context.company.id,
        document_id=document.id,
        version=1,
        original_filename=Path(filename).name,
        display_name=naming.resolved_name,
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
        uploaded_by_membership_id=context.membership.id,
    )
    session.add(version)
    session.flush()
    stored_key: str | None = None
    try:
        stored = persist_workspace_attachment(
            company_id=context.company.id,
            workspace_id=document.id,
            attachment_id=version.id,
            filename=filename,
            stream=stream,
            namespace="ip-documents",
            before_store=lambda size: assert_storage_quota_allows_upload(
                session,
                company_id=context.company.id,
                matter_id=None,
                incoming_size_bytes=size,
            ),
            validate_temp_file=lambda path: reject_if_infected(path, filename=filename),
        )
        stored_key = stored.storage_key
        duplicate_rows = list(
            session.execute(
                select(IpDocumentVersion, IpDocument)
                .join(IpDocument, IpDocument.id == IpDocumentVersion.document_id)
                .where(
                    IpDocumentVersion.company_id == context.company.id,
                    IpDocumentVersion.id != version.id,
                    IpDocumentVersion.sha256_hex == stored.sha256_hex,
                    IpDocumentVersion.size_bytes == stored.size_bytes,
                    IpDocumentVersion.content_type == content_type,
                    IpDocument.taxonomy_entry_id == taxonomy.id,
                )
            ).all()
        )
        visible_duplicates: list[IpDocumentDuplicateCandidate] = []
        for duplicate_version, duplicate_document in duplicate_rows:
            try:
                _assert_document_targets_accessible(
                    session, context=context, document_id=duplicate_document.id
                )
            except HTTPException:
                continue
            visible_duplicates.append(
                IpDocumentDuplicateCandidate(
                    document_id=duplicate_document.id,
                    version_id=duplicate_version.id,
                    display_name=duplicate_version.display_name,
                    sha256_hex=duplicate_version.sha256_hex,
                    size_bytes=duplicate_version.size_bytes,
                    content_type=duplicate_version.content_type,
                )
            )
        if visible_duplicates:
            delete_stored_document(stored.storage_key)
            stored_key = None
            session.rollback()
            record_from_context(
                session,
                context,
                action="ip_document.duplicate_offered",
                target_type="ip_document_version",
                target_id=visible_duplicates[0].version_id,
                metadata={
                    "sha256_hex": stored.sha256_hex,
                    "candidate_count": len(visible_duplicates),
                    "filename_match_not_required": True,
                },
            )
            session.commit()
            return (
                IpDocumentUploadResponse(
                    outcome="duplicate_found", duplicate_candidates=visible_duplicates
                ),
                None,
            )
        version.storage_key = stored.storage_key
        version.size_bytes = stored.size_bytes
        version.sha256_hex = stored.sha256_hex
        for target in metadata.links:
            _create_link(
                session,
                context=context,
                document=document,
                version_id=version.id,
                target=target,
            )
        job = enqueue_processing_job(
            session,
            company_id=context.company.id,
            requested_by_membership_id=context.membership.id,
            target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
            attachment_id=version.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        record_from_context(
            session,
            context,
            action="ip_document.uploaded",
            target_type="ip_document",
            target_id=document.id,
            metadata={
                "version_id": version.id,
                "taxonomy_key": taxonomy.key,
                "sha256_hex": version.sha256_hex,
                "original_filename": version.original_filename,
                "display_name": version.display_name,
                "link_count": len(metadata.links),
                "processing_job_id": job.id,
            },
        )
        session.commit()
        return (
            IpDocumentUploadResponse(
                outcome="created",
                document=_serialize_document(session, document=document),
                processing_job=load_latest_processing_jobs(
                    session,
                    target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
                    attachment_ids=[version.id],
                ).get(version.id),
            ),
            job.id,
        )
    except Exception:
        session.rollback()
        if stored_key:
            delete_stored_document(stored_key)
        raise


def upload_ip_document_version(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    metadata: IpDocumentNewVersionMetadata,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> tuple[IpDocumentUploadResponse, str | None]:
    _require_document_capability(
        session, context=context, capability="documents:upload"
    )
    verify_upload(filename=filename, content_type=content_type, stream=stream)
    document = _document_or_404(session, context=context, document_id=document_id, for_update=True)
    if document.current_version != metadata.expected_current_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_version_conflict",
                "current_version": document.current_version,
            },
        )
    previous = _version_or_404(
        session, document=document, version=document.current_version, for_update=True
    )
    next_version = document.current_version + 1
    taxonomy = session.get(IpDocumentTaxonomyEntry, document.taxonomy_entry_id)
    if taxonomy is None or taxonomy.company_id != context.company.id:
        raise HTTPException(status_code=500, detail="Document taxonomy integrity failure.")
    from caseops_api.schemas.ip_documents import IpDocumentNamingPreviewRequest

    naming = preview_ip_document_name(
        IpDocumentNamingPreviewRequest(
            client_code=metadata.client_code,
            asset_type=metadata.asset_type,
            mark=metadata.mark,
            jurisdiction=metadata.jurisdiction,
            application_no=metadata.application_no,
            proceeding_type=metadata.proceeding_type,
            proceeding_no=metadata.proceeding_no,
            document_type=taxonomy.key,
            document_date=metadata.document_date,
            version=next_version,
            extension=Path(filename).suffix,
            existing_names=_existing_display_names(session, company_id=context.company.id),
        )
    )
    version = IpDocumentVersion(
        company_id=context.company.id,
        document_id=document.id,
        version=next_version,
        original_filename=Path(filename).name,
        display_name=naming.resolved_name,
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
        uploaded_by_membership_id=context.membership.id,
    )
    session.add(version)
    session.flush()
    stored_key: str | None = None
    try:
        stored = persist_workspace_attachment(
            company_id=context.company.id,
            workspace_id=document.id,
            attachment_id=version.id,
            filename=filename,
            stream=stream,
            namespace="ip-documents",
            before_store=lambda size: assert_storage_quota_allows_upload(
                session,
                company_id=context.company.id,
                matter_id=None,
                incoming_size_bytes=size,
            ),
            validate_temp_file=lambda path: reject_if_infected(path, filename=filename),
        )
        stored_key = stored.storage_key
        duplicate_rows = list(
            session.execute(
                select(IpDocumentVersion, IpDocument)
                .join(IpDocument, IpDocument.id == IpDocumentVersion.document_id)
                .where(
                    IpDocumentVersion.company_id == context.company.id,
                    IpDocumentVersion.id != version.id,
                    IpDocumentVersion.sha256_hex == stored.sha256_hex,
                    IpDocumentVersion.size_bytes == stored.size_bytes,
                    IpDocumentVersion.content_type == content_type,
                    IpDocument.taxonomy_entry_id == taxonomy.id,
                )
            ).all()
        )
        visible_duplicates: list[IpDocumentDuplicateCandidate] = []
        for candidate, candidate_document in duplicate_rows:
            try:
                _assert_document_targets_accessible(
                    session, context=context, document_id=candidate_document.id
                )
            except HTTPException:
                continue
            visible_duplicates.append(
                IpDocumentDuplicateCandidate(
                    document_id=candidate.document_id,
                    version_id=candidate.id,
                    display_name=candidate.display_name,
                    sha256_hex=candidate.sha256_hex,
                    size_bytes=candidate.size_bytes,
                    content_type=candidate.content_type,
                )
            )
        if visible_duplicates:
            delete_stored_document(stored.storage_key)
            stored_key = None
            session.rollback()
            record_from_context(
                session,
                context,
                action="ip_document.duplicate_offered",
                target_type="ip_document_version",
                target_id=visible_duplicates[0].version_id,
                metadata={
                    "sha256_hex": stored.sha256_hex,
                    "candidate_count": len(visible_duplicates),
                    "filename_match_not_required": True,
                    "requested_document_id": document_id,
                },
            )
            session.commit()
            return (
                IpDocumentUploadResponse(
                    outcome="duplicate_found", duplicate_candidates=visible_duplicates
                ),
                None,
            )
        version.storage_key = stored.storage_key
        version.size_bytes = stored.size_bytes
        version.sha256_hex = stored.sha256_hex
        previous.state = "superseded"
        document.current_version = next_version
        job = enqueue_processing_job(
            session,
            company_id=context.company.id,
            requested_by_membership_id=context.membership.id,
            target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
            attachment_id=version.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        record_from_context(
            session,
            context,
            action="ip_document.version_uploaded",
            target_type="ip_document_version",
            target_id=version.id,
            metadata={
                "document_id": document.id,
                "version": next_version,
                "superseded_version_id": previous.id,
                "sha256_hex": version.sha256_hex,
                "processing_job_id": job.id,
            },
        )
        session.commit()
        return (
            IpDocumentUploadResponse(
                outcome="created",
                document=_serialize_document(session, document=document),
                processing_job=load_latest_processing_jobs(
                    session,
                    target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
                    attachment_ids=[version.id],
                ).get(version.id),
            ),
            job.id,
        )
    except Exception:
        session.rollback()
        if stored_key:
            delete_stored_document(stored_key)
        raise


def metadata_to_naming_request(
    metadata: IpDocumentUploadMetadata,
    *,
    version: int,
    filename: str,
    existing_names: list[str],
):
    from caseops_api.schemas.ip_documents import IpDocumentNamingPreviewRequest

    return IpDocumentNamingPreviewRequest(
        client_code=metadata.client_code,
        asset_type=metadata.asset_type,
        mark=metadata.mark,
        jurisdiction=metadata.jurisdiction,
        application_no=metadata.application_no,
        proceeding_type=metadata.proceeding_type,
        proceeding_no=metadata.proceeding_no,
        document_type=metadata.taxonomy_key,
        document_date=metadata.document_date,
        version=version,
        extension=Path(filename).suffix,
        existing_names=existing_names,
    )


def add_ip_document_links(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    payload: IpDocumentAddLinksRequest,
) -> IpDocumentRecord:
    _require_document_capability(
        session, context=context, capability="documents:manage"
    )
    document = _document_or_404(session, context=context, document_id=document_id, for_update=True)
    if document.current_version != payload.expected_current_version:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_version_conflict",
                "current_version": document.current_version,
            },
        )
    if payload.version_id is not None:
        valid_version = session.scalar(
            select(IpDocumentVersion.id).where(
                IpDocumentVersion.id == payload.version_id,
                IpDocumentVersion.company_id == context.company.id,
                IpDocumentVersion.document_id == document.id,
            )
        )
        if valid_version is None:
            raise HTTPException(status_code=404, detail="IP document version not found.")
    created: list[str] = []
    for target in payload.links:
        row = _create_link(
            session,
            context=context,
            document=document,
            version_id=payload.version_id,
            target=target,
        )
        created.append(row.id)
    record_from_context(
        session,
        context,
        action="ip_document.links_added",
        target_type="ip_document",
        target_id=document.id,
        metadata={"link_ids": created, "version_id": payload.version_id},
    )
    session.commit()
    return _serialize_document(session, document=document)


def transition_ip_document_state(
    session: Session,
    *,
    context: SessionContext,
    document_id: str,
    version_number: int,
    payload: IpDocumentStateTransitionRequest,
) -> IpDocumentRecord:
    _require_document_capability(
        session, context=context, capability="documents:manage"
    )
    document = _document_or_404(session, context=context, document_id=document_id, for_update=True)
    version = _version_or_404(session, document=document, version=version_number, for_update=True)
    if (
        document.current_version != payload.expected_current_version
        or version.version != document.current_version
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_version_conflict",
                "current_version": document.current_version,
            },
        )
    if version.state != payload.expected_state:
        raise HTTPException(
            status_code=409,
            detail={"code": "ip_document_state_conflict", "current_state": version.state},
        )
    if payload.target_state not in _ALLOWED_TRANSITIONS[version.state]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_invalid_transition",
                "from_state": version.state,
                "to_state": payload.target_state,
            },
        )
    if payload.target_state in {"approved", "filed"} and not membership_has_capability(
        session, context.membership, "ip:approve"
    ):
        raise HTTPException(status_code=403, detail="Capability 'ip:approve' is required.")
    if payload.target_state in {"approved", "filed"}:
        version.locked_by_membership_id = context.membership.id
        version.locked_at = utcnow()
    version.state = payload.target_state
    session.add(version)
    record_from_context(
        session,
        context,
        action="ip_document.state_transitioned",
        target_type="ip_document_version",
        target_id=version.id,
        metadata={
            "document_id": document.id,
            "version": version.version,
            "from_state": payload.expected_state,
            "to_state": payload.target_state,
            "locked": payload.target_state in {"approved", "filed"},
        },
    )
    session.commit()
    return _serialize_document(session, document=document)


def _bulk_material(
    session: Session,
    *,
    context: SessionContext,
    items: list[IpDocumentBulkItem],
    lock: bool,
) -> tuple[list[IpDocumentBulkPreviewItem], str]:
    existing_names = _existing_display_names(session, company_id=context.company.id)
    previews: list[IpDocumentBulkPreviewItem] = []
    token_rows: list[dict[str, object]] = []
    for item in sorted(items, key=lambda row: row.document_id):
        document = _document_or_404(
            session,
            context=context,
            document_id=item.document_id,
            for_update=lock,
        )
        taxonomy = session.get(IpDocumentTaxonomyEntry, document.taxonomy_entry_id)
        if taxonomy is None or taxonomy.key != item.expected_taxonomy_key:
            raise HTTPException(
                status_code=409,
                detail={"code": "ip_document_taxonomy_conflict", "document_id": document.id},
            )
        if document.current_version != item.expected_current_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ip_document_version_conflict",
                    "document_id": document.id,
                    "current_version": document.current_version,
                },
            )
        target_taxonomy = _taxonomy_or_404(
            session, company_id=context.company.id, key=item.taxonomy_key
        )
        version = _version_or_404(
            session, document=document, version=document.current_version, for_update=lock
        )
        if version.state not in {"draft", "review", "rejected"}:
            raise HTTPException(
                status_code=409,
                detail={"code": "ip_document_locked", "document_id": document.id},
            )
        naming = item.naming.model_copy(
            update={
                "document_type": target_taxonomy.key,
                "version": version.version,
                "extension": Path(version.original_filename).suffix,
                "existing_names": [
                    name
                    for name in existing_names
                    if name.casefold() != version.display_name.casefold()
                ]
                + [row.proposed_display_name for row in previews]
            }
        )
        proposed = preview_ip_document_name(naming)
        previews.append(
            IpDocumentBulkPreviewItem(
                document_id=document.id,
                taxonomy_key=target_taxonomy.key,
                current_display_name=version.display_name,
                proposed_display_name=proposed.resolved_name,
                conflict_detected=proposed.conflict_detected,
                warnings=proposed.warnings,
            )
        )
        token_rows.append(
            {
                "document_id": document.id,
                "current_version": document.current_version,
                "current_taxonomy": taxonomy.key,
                "target_taxonomy": target_taxonomy.key,
                "current_display_name": version.display_name,
                "proposed_display_name": proposed.resolved_name,
            }
        )
    token = hashlib.sha256(
        json.dumps(token_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return previews, token


def preview_ip_document_bulk_update(
    session: Session,
    *,
    context: SessionContext,
    payload: IpDocumentBulkPreviewRequest,
) -> IpDocumentBulkPreviewResponse:
    _require_document_capability(
        session, context=context, capability="documents:manage"
    )
    previews, token = _bulk_material(session, context=context, items=payload.items, lock=False)
    return IpDocumentBulkPreviewResponse(
        preview_token=token,
        items=previews,
        conflict_count=sum(row.conflict_detected for row in previews),
    )


def apply_ip_document_bulk_update(
    session: Session,
    *,
    context: SessionContext,
    payload: IpDocumentBulkApplyRequest,
) -> IpDocumentListResponse:
    _require_document_capability(
        session, context=context, capability="documents:manage"
    )
    previews, token = _bulk_material(session, context=context, items=payload.items, lock=True)
    if token != payload.preview_token:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": "ip_document_bulk_preview_stale"},
        )
    for preview in previews:
        document = _document_or_404(
            session,
            context=context,
            document_id=preview.document_id,
            for_update=True,
        )
        taxonomy = _taxonomy_or_404(
            session, company_id=context.company.id, key=preview.taxonomy_key
        )
        version = _version_or_404(
            session, document=document, version=document.current_version, for_update=True
        )
        document.taxonomy_entry_id = taxonomy.id
        version.display_name = preview.proposed_display_name
        session.add_all([document, version])
    record_from_context(
        session,
        context,
        action="ip_document.bulk_updated",
        target_type="ip_document_bulk",
        target_id=payload.preview_token,
        metadata={
            "document_ids": [row.document_id for row in previews],
            "conflict_count": sum(row.conflict_detected for row in previews),
        },
    )
    session.commit()
    return list_ip_documents(session, context=context)


def import_ip_document_aliases(
    session: Session,
    *,
    context: SessionContext,
    payload: IpDocumentAliasImportRequest,
) -> IpDocumentAliasImportResponse:
    requested: list[tuple[IpDocumentTaxonomyEntry, str, str]] = []
    seen: dict[str, str] = {}
    for entry_payload in payload.entries:
        entry = _taxonomy_or_404(
            session, company_id=context.company.id, key=entry_payload.taxonomy_key
        )
        for alias in entry_payload.aliases:
            normalized = _normalize_alias(alias)
            if not normalized:
                raise HTTPException(status_code=422, detail="Aliases need a letter or number.")
            previous = seen.get(normalized)
            if previous is not None and previous != entry.key:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "ip_document_alias_import_request_conflict", "alias": alias},
                )
            seen[normalized] = entry.key
            requested.append((entry, alias, normalized))
    existing = list(
        session.scalars(
            select(IpDocumentTaxonomyAlias).where(
                IpDocumentTaxonomyAlias.company_id == context.company.id,
                IpDocumentTaxonomyAlias.normalized_alias.in_(list(seen)),
            )
        ).all()
    )
    entries_by_id = {
        row.id: row
        for row in session.scalars(
            select(IpDocumentTaxonomyEntry).where(
                IpDocumentTaxonomyEntry.company_id == context.company.id
            )
        ).all()
    }
    existing_by_normalized = {row.normalized_alias: row for row in existing}
    conflicts: list[IpDocumentAliasImportConflict] = []
    unchanged = 0
    pending: list[tuple[IpDocumentTaxonomyEntry, str, str]] = []
    for entry, alias, normalized in requested:
        current = existing_by_normalized.get(normalized)
        if current is None:
            pending.append((entry, alias, normalized))
        elif current.taxonomy_entry_id == entry.id:
            unchanged += 1
        else:
            conflicts.append(
                IpDocumentAliasImportConflict(
                    alias=alias,
                    normalized_alias=normalized,
                    existing_taxonomy_key=entries_by_id[current.taxonomy_entry_id].key,
                    requested_taxonomy_key=entry.key,
                )
            )
    if conflicts and not payload.dry_run:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ip_document_alias_import_conflict",
                "conflicts": [row.model_dump() for row in conflicts],
            },
        )
    if not payload.dry_run:
        for entry, alias, normalized in pending:
            session.add(
                IpDocumentTaxonomyAlias(
                    company_id=context.company.id,
                    taxonomy_entry_id=entry.id,
                    alias=alias,
                    normalized_alias=normalized,
                    source="law_firm_import",
                    created_by_membership_id=context.membership.id,
                )
            )
        record_from_context(
            session,
            context,
            action="ip_document_taxonomy.aliases_imported",
            target_type="ip_document_taxonomy",
            target_id=context.company.id,
            metadata={
                "taxonomy_version": TAXONOMY_VERSION,
                "imported_count": len(pending),
                "unchanged_count": unchanged,
            },
        )
        session.commit()
    return IpDocumentAliasImportResponse(
        dry_run=payload.dry_run,
        imported_count=len(pending),
        unchanged_count=unchanged,
        conflicts=conflicts,
    )
