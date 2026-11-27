"""Uploaded KYC documents of a client (BUG-003, US-037 / US-053 / FT-049).

Before this module a KYC "submission" was a list of document names typed into
a text box: no file ever reached CaseOps, so a reviewer approved or rejected a
pack it could not open. A KYC pack is now the client's current uploaded files.

One set of rules serves every path that writes a KYC submission or decision:

* firm users upload, list, open and remove files on the client profile
  (``/api/clients/{id}/kyc/documents``);
* a client-portal user does the same for a client linked to a granted Matter,
  and sees only the files they uploaded
  (``/api/portal/matters/{matter_id}/kyc/documents``);
* every submit (internal, portal, matter verification PATCH) requires the pack
  to meet :data:`KYC_REQUIREMENTS`; every approval names every current file it
  reviewed, and a rejection names the files it reviewed;
* a file counts as reviewed only when the reviewer opened it (inline view or
  download) after it was uploaded: the server checks its own audit trail, so a
  direct API call cannot approve a file nobody opened.

Files go through the same validation, malware scan, quota and storage as
Matter attachments (``file_security.verify_upload``, ``virus_scan``,
``storage_governance``, ``document_storage``) under the ``client-kyc``
namespace. They are never indexed or embedded (PRD SEC-016).

Assumption recorded for BUG-003: the PRD names KYC documents but does not
define a required set, so the required set is explicit here: a PAN card, and
one identity/address proof (masked Aadhaar, passport, or another address
proof such as a utility bill). Further documents are optional.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import PurePath
from typing import BinaryIO
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.client_kyc_document_models import (
    ClientKycDocument,
    KycDocumentType,
)
from caseops_api.db.models import (
    AuditActorType,
    AuditEvent,
    AuditResult,
    Client,
    ClientKycStatus,
    CompanyMembership,
    Matter,
    MatterClientAssignment,
    PortalUser,
    User,
)
from caseops_api.schemas.clients import (
    ClientKycDocumentListResponse,
    ClientKycDocumentRecord,
    KycDocumentTypeOption,
    KycRequirementRecord,
)
from caseops_api.services.aadhaar_privacy import (
    UNMASKED_AADHAAR_MESSAGE,
    contains_full_aadhaar,
    mask_full_aadhaar_in_filename,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.document_storage import (
    delete_stored_document,
    persist_workspace_attachment,
    resolve_storage_path,
    sanitize_filename,
)
from caseops_api.services.file_security import DEFAULT_MAX_BYTES, verify_upload
from caseops_api.services.matter_write_fence import require_read_only_upload_session
from caseops_api.services.session_context import SessionContext
from caseops_api.services.storage_governance import (
    StorageQuotaExceeded,
    assert_storage_quota_allows_upload,
)
from caseops_api.services.virus_scan import reject_if_infected

logger = logging.getLogger(__name__)

STORAGE_NAMESPACE = "client-kyc"

KYC_DOCUMENT_TYPE_OPTIONS: tuple[KycDocumentTypeOption, ...] = (
    KycDocumentTypeOption(
        value="pan",
        label="PAN card",
        hint="Front of the PAN card, as a PDF or photo.",
        requires_label=False,
    ),
    KycDocumentTypeOption(
        value="aadhaar_masked",
        label="Aadhaar (masked)",
        hint=(
            "Upload a masked Aadhaar only: the first eight digits hidden "
            "(download it from the UIDAI site). Never upload or type the "
            "full 12-digit number."
        ),
        requires_label=False,
    ),
    KycDocumentTypeOption(
        value="passport",
        label="Passport",
        hint="Photo page and address page.",
        requires_label=False,
    ),
    KycDocumentTypeOption(
        value="address_proof",
        label="Other address proof",
        hint="Utility bill, bank statement or registered-office proof, under three months old.",
        requires_label=False,
    ),
    KycDocumentTypeOption(
        value="other",
        label="Other document",
        hint="Board resolution, authorisation letter or another supporting document.",
        requires_label=True,
    ),
)
_TYPE_LABELS = {option.value: option.label for option in KYC_DOCUMENT_TYPE_OPTIONS}

# (key, label, document types that satisfy it)
KYC_REQUIREMENTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("pan", "PAN card", (KycDocumentType.PAN.value,)),
    (
        "identity_address_proof",
        "Masked Aadhaar, passport or another address proof",
        (
            KycDocumentType.AADHAAR_MASKED.value,
            KycDocumentType.PASSPORT.value,
            KycDocumentType.ADDRESS_PROOF.value,
        ),
    ),
)

# Identity documents are images or PDFs: the reviewer opens them inline.
KYC_ACCEPTED_EXTENSIONS: tuple[str, ...] = (".pdf", ".png", ".jpg", ".jpeg")
_INLINE_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# Files can be added or removed while the pack is being assembled, after a
# rejection, and while a submitted pack waits for review (a reviewer's
# approval names the exact files, so a changed pack cannot be approved
# blind). Under review and verified packs are frozen.
UPLOAD_OPEN_STATUSES = frozenset(
    {
        ClientKycStatus.NOT_REQUIRED.value,
        ClientKycStatus.REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.SUBMITTED.value,
        ClientKycStatus.REJECTED.value,
        ClientKycStatus.EXPIRED.value,
    }
)

_KYC_READ_CAPABILITIES = ("clients:kyc_submit", "clients:kyc_review")

# Response headers for every KYC file response (firm and portal, inline and
# attachment). The web app reads the bytes with fetch and renders them itself,
# so these govern a direct navigation to the URL: no MIME sniffing, no caching,
# no framing by another origin, and a sandboxed document with no script
# (Chromium still renders a top-level PDF or image under this policy).
KYC_FILE_RESPONSE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "private, no-store, max-age=0",
    "Pragma": "no-cache",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; sandbox",
}

# Audit actions written by get_client_kyc_document_download when a firm user
# opens a file inline or downloads it. The review rule reads them back.
KYC_DOCUMENT_OPENED_ACTIONS = ("client.kyc_document_viewed", "client.kyc_document_downloaded")


def kyc_max_upload_bytes() -> int:
    return min(DEFAULT_MAX_BYTES, get_settings().max_attachment_size_bytes)


def _normalized_status(value: object) -> str:
    raw = str(value or ClientKycStatus.NOT_REQUIRED.value)
    return {"not_started": "not_required", "pending": "submitted"}.get(raw, raw)


# ---------------------------------------------------------------------------
# Pack rules shared by every submit / review path
# ---------------------------------------------------------------------------


def current_kyc_documents(
    session: Session, *, company_id: str, client_id: str,
) -> list[ClientKycDocument]:
    return list(
        session.scalars(
            select(ClientKycDocument)
            .where(
                ClientKycDocument.company_id == company_id,
                ClientKycDocument.client_id == client_id,
                ClientKycDocument.retired_at.is_(None),
            )
            .order_by(ClientKycDocument.created_at, ClientKycDocument.id)
        )
    )


def kyc_requirement_records(
    documents: Iterable[ClientKycDocument],
) -> list[KycRequirementRecord]:
    present = {doc.document_type for doc in documents}
    return [
        KycRequirementRecord(
            key=key,
            label=label,
            satisfied_by=list(types),  # type: ignore[arg-type]
            satisfied=any(t in present for t in types),
        )
        for key, label, types in KYC_REQUIREMENTS
    ]


def assert_kyc_pack_complete(
    session: Session, *, client: Client, action: str,
) -> list[ClientKycDocument]:
    """Refuse ``action`` unless the client's current files meet every requirement."""
    documents = current_kyc_documents(
        session, company_id=client.company_id, client_id=client.id,
    )
    missing = [r.label for r in kyc_requirement_records(documents) if not r.satisfied]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"KYC cannot be {action} yet. Upload these documents first: "
                f"{'; '.join(missing)}."
            ),
        )
    return documents


def kyc_display_filename(doc: ClientKycDocument) -> str:
    """The stored file name with any full Aadhaar number masked.

    Uploads mask on write; this also covers rows stored before that rule, on
    every read (API record and Content-Disposition).
    """
    return mask_full_aadhaar_in_filename(doc.original_filename)


def _document_name(doc: ClientKycDocument) -> str:
    kind = _TYPE_LABELS.get(doc.document_type, doc.document_type)
    if doc.label:
        kind = f"{kind}: {doc.label}"
    return f"{kind} ({kyc_display_filename(doc)})"


def _as_utc(value: datetime) -> datetime:
    # SQLite returns naive datetimes; every KYC and audit timestamp is UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def documents_opened_by_reviewer(
    session: Session,
    *,
    client: Client,
    reviewer_membership_id: str,
    documents: Iterable[ClientKycDocument],
) -> set[str]:
    """Ids of ``documents`` the reviewer opened inline or downloaded after the
    file was uploaded.

    The evidence is the reviewer's own successful open/download audit rows for
    this client in this tenant. Audit rows are insert-only, carry the actor's
    membership, and are committed before the file's bytes are returned, so a
    row exists only when the server served that reviewer that file.
    """
    uploaded_at = {doc.id: _as_utc(doc.created_at) for doc in documents}
    if not uploaded_at:
        return set()
    rows = session.execute(
        select(AuditEvent.metadata_json, AuditEvent.created_at).where(
            AuditEvent.company_id == client.company_id,
            AuditEvent.action.in_(KYC_DOCUMENT_OPENED_ACTIONS),
            AuditEvent.target_type == "client",
            AuditEvent.target_id == client.id,
            AuditEvent.actor_membership_id == reviewer_membership_id,
            AuditEvent.result == AuditResult.SUCCESS,
        )
    ).all()
    opened: set[str] = set()
    for metadata_json, opened_at in rows:
        try:
            metadata = json.loads(metadata_json or "{}")
        except (TypeError, ValueError):
            continue
        document_id = metadata.get("document_id") if isinstance(metadata, dict) else None
        uploaded = uploaded_at.get(document_id) if isinstance(document_id, str) else None
        if uploaded is not None and opened_at is not None and _as_utc(opened_at) >= uploaded:
            opened.add(document_id)
    return opened


def record_kyc_review(
    session: Session,
    *,
    client: Client,
    reviewed_document_ids: list[str],
    decision: str,
    reviewer_membership_id: str,
    require_complete_review: bool,
) -> list[ClientKycDocument]:
    """Stamp the reviewed files with the decision.

    An approval must name every current file; a rejection may name any subset
    (including none, when files are missing). A named file that is not in the
    current pack means the pack changed after the reviewer loaded it.

    Every named file must have been opened by this reviewer after it was
    uploaded (:func:`documents_opened_by_reviewer`), for an approval and a
    rejection alike: "reviewed" on a file always means the reviewer saw it. A
    rejection that names no file (for example, a required file is missing)
    needs no open.
    """
    if len(set(reviewed_document_ids)) != len(reviewed_document_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="reviewed_document_ids must not repeat a document.",
        )
    documents = current_kyc_documents(
        session, company_id=client.company_id, client_id=client.id,
    )
    by_id = {doc.id: doc for doc in documents}
    reviewed = set(reviewed_document_ids)
    stale = reviewed - set(by_id)
    unreviewed = set(by_id) - reviewed
    if stale or (require_complete_review and unreviewed):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The KYC documents changed since you opened them, or not every "
                "document was reviewed. Reload and review each current document."
            ),
        )
    named = [doc for doc in documents if doc.id in reviewed]
    opened = documents_opened_by_reviewer(
        session, client=client, reviewer_membership_id=reviewer_membership_id,
        documents=named,
    )
    unopened = [doc for doc in named if doc.id not in opened]
    if unopened:
        verb = "approve" if decision == "approved" else "reject"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Open each KYC document before you {verb} the pack. You have not "
                f"opened: {'; '.join(_document_name(doc) for doc in unopened)}."
            ),
        )
    now = datetime.now(UTC)
    out = []
    for doc in documents:
        if doc.id in reviewed:
            doc.review_decision = decision
            doc.reviewed_at = now
            doc.reviewed_by_membership_id = reviewer_membership_id
            out.append(doc)
    return out


def review_audit_metadata(documents: list[ClientKycDocument]) -> dict:
    return {
        "reviewed_document_ids": [doc.id for doc in documents],
        "reviewed_documents": [
            {"id": doc.id, "document_type": doc.document_type, "sha256_hex": doc.sha256_hex}
            for doc in documents
        ],
    }


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


def _uploader_names(session: Session, documents: list[ClientKycDocument]) -> dict[str, str]:
    ids = {doc.uploaded_by_membership_id for doc in documents if doc.uploaded_by_membership_id}
    if not ids:
        return {}
    rows = session.execute(
        select(CompanyMembership.id, User.full_name, User.email)
        .join(User, User.id == CompanyMembership.user_id)
        .where(CompanyMembership.id.in_(ids))
    ).all()
    return {row[0]: row[1] or row[2] for row in rows}


def _document_record(
    doc: ClientKycDocument, *, names: dict[str, str],
) -> ClientKycDocumentRecord:
    suffix = PurePath(doc.original_filename).suffix.lower()
    return ClientKycDocumentRecord(
        id=doc.id,
        client_id=doc.client_id,
        document_type=doc.document_type,  # type: ignore[arg-type]
        label=doc.label,
        original_filename=kyc_display_filename(doc),
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        uploaded_by_membership_id=doc.uploaded_by_membership_id,
        uploaded_by_name=(
            names.get(doc.uploaded_by_membership_id or "")
            if doc.uploaded_by_membership_id
            else ("Client portal" if doc.uploaded_by_portal_user_id else None)
        ),
        uploaded_by_portal=doc.uploaded_by_portal_user_id is not None,
        review_decision=doc.review_decision,  # type: ignore[arg-type]
        reviewed_at=doc.reviewed_at,
        reviewed_by_membership_id=doc.reviewed_by_membership_id,
        previewable=suffix in _INLINE_MEDIA_TYPES,
        created_at=doc.created_at,
    )


def _list_response(
    session: Session,
    *,
    client: Client,
    all_current: list[ClientKycDocument],
    visible: list[ClientKycDocument],
) -> ClientKycDocumentListResponse:
    names = _uploader_names(session, visible)
    requirements = kyc_requirement_records(all_current)
    return ClientKycDocumentListResponse(
        client_id=client.id,
        kyc_status=_normalized_status(client.kyc_status),  # type: ignore[arg-type]
        documents=[_document_record(doc, names=names) for doc in visible],
        requirements=requirements,
        requirements_met=all(r.satisfied for r in requirements),
        upload_allowed=_normalized_status(client.kyc_status) in UPLOAD_OPEN_STATUSES,
        document_types=list(KYC_DOCUMENT_TYPE_OPTIONS),
        accepted_extensions=list(KYC_ACCEPTED_EXTENSIONS),
        max_upload_bytes=kyc_max_upload_bytes(),
    )


# ---------------------------------------------------------------------------
# Upload validation shared by firm and portal paths
# ---------------------------------------------------------------------------


def _validated_type_and_label(document_type: str, label: str | None) -> tuple[str, str | None]:
    if document_type not in _TYPE_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Unknown KYC document type {document_type!r}. "
                f"Allowed: {', '.join(_TYPE_LABELS)}."
            ),
        )
    clean = (label or "").strip() or None
    if clean is not None and len(clean) > 120:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The document label must be 120 characters or fewer.",
        )
    if document_type == KycDocumentType.OTHER.value and clean is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Name the document when its type is Other.",
        )
    if contains_full_aadhaar(clean):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=UNMASKED_AADHAAR_MESSAGE,
        )
    return document_type, clean


def _verify_kyc_file(*, filename: str, content_type: str | None, stream: BinaryIO) -> None:
    suffix = PurePath((filename or "").strip()).suffix.lower()
    if suffix not in KYC_ACCEPTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "KYC documents must be a PDF, PNG or JPEG file "
                f"({', '.join(KYC_ACCEPTED_EXTENSIONS)})."
            ),
        )
    # Same extension / content-type / magic-byte / size checks as Matter uploads.
    verify_upload(
        filename=filename, content_type=content_type, stream=stream,
        max_bytes=kyc_max_upload_bytes(),
    )


def _assert_upload_open(client: Client) -> None:
    current = _normalized_status(client.kyc_status)
    if current not in UPLOAD_OPEN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"KYC documents cannot be changed while KYC is {current.replace('_', ' ')}."
            ),
        )


def _store_kyc_file(
    session: Session,
    *,
    company_id: str,
    client_id: str,
    document_id: str,
    filename: str,
    stream: BinaryIO,
):
    def preflight_quota(size_bytes: int) -> None:
        try:
            assert_storage_quota_allows_upload(
                session, company_id=company_id, matter_id=None,
                incoming_size_bytes=size_bytes,
            )
        finally:
            session.rollback()

    return persist_workspace_attachment(
        company_id=company_id,
        namespace=STORAGE_NAMESPACE,
        workspace_id=client_id,
        attachment_id=document_id,
        filename=filename,
        stream=stream,
        before_store=preflight_quota,
        validate_temp_file=lambda path: reject_if_infected(path, filename=filename),
    )


def _discard(storage_key: str | None, document_id: str) -> None:
    if storage_key is None:
        return
    try:
        delete_stored_document(storage_key)
    except Exception:  # noqa: BLE001 - best-effort cleanup of an unpublished object
        logger.exception("Could not remove unpublished KYC document %s", document_id)


def _upload_audit_metadata(doc: ClientKycDocument) -> dict:
    # No filename: KYC filenames routinely carry the person's name or number.
    return {
        "document_id": doc.id,
        "document_type": doc.document_type,
        "size_bytes": doc.size_bytes,
        "sha256_hex": doc.sha256_hex,
        "content_type": doc.content_type,
    }


def _download_disposition(doc: ClientKycDocument, inline: bool) -> tuple[str, str]:
    """(media_type, disposition) for a download; inline only for PDF / image."""
    if not inline:
        return doc.content_type or "application/octet-stream", "attachment"
    suffix = PurePath(doc.original_filename).suffix.lower()
    media_type = _INLINE_MEDIA_TYPES.get(suffix)
    if media_type is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF and image KYC documents can be displayed inline.",
        )
    return media_type, "inline"


def _resolve_bytes(doc: ClientKycDocument) -> str:
    path = resolve_storage_path(doc.storage_key)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The KYC document file is no longer available.",
        )
    return str(path)


def _remove_document(doc: ClientKycDocument, session: Session) -> tuple[str, str | None]:
    """Retire a reviewed document (keep evidence) or delete an unreviewed one.

    Returns (outcome, storage key to delete after commit).
    """
    if doc.review_decision is not None:
        doc.retired_at = datetime.now(UTC)
        return "retired", None
    key = doc.storage_key
    session.delete(doc)
    return "deleted", key


def _delete_after_commit(storage_key: str | None, document_id: str) -> None:
    if storage_key is None:
        return
    try:
        delete_stored_document(storage_key)
    except Exception:  # noqa: BLE001 - the row is gone; an orphan object is logged
        logger.warning(
            "Removed KYC document %s but could not delete its stored object",
            document_id.replace("\r", "").replace("\n", ""),
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Firm users
# ---------------------------------------------------------------------------


def _require_kyc_reader(session: Session, context: SessionContext) -> None:
    from caseops_api.services.capabilities import membership_has_capability

    if not any(
        membership_has_capability(session, context.membership, capability)
        for capability in _KYC_READ_CAPABILITIES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your role cannot open client KYC documents.",
        )


def _client_document(
    session: Session, *, company_id: str, client_id: str, document_id: str,
    include_retired: bool = False,
) -> ClientKycDocument:
    stmt = select(ClientKycDocument).where(
        ClientKycDocument.id == document_id,
        ClientKycDocument.company_id == company_id,
        ClientKycDocument.client_id == client_id,
    )
    if not include_retired:
        stmt = stmt.where(ClientKycDocument.retired_at.is_(None))
    doc = session.scalar(stmt)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return doc


def list_client_kyc_documents(
    session: Session, *, context: SessionContext, client_id: str,
) -> ClientKycDocumentListResponse:
    from caseops_api.services.clients import _get_client_model

    client = _get_client_model(session, context=context, client_id=client_id)
    _require_kyc_reader(session, context)
    documents = current_kyc_documents(
        session, company_id=context.company.id, client_id=client.id,
    )
    return _list_response(session, client=client, all_current=documents, visible=documents)


def upload_client_kyc_document(
    session: Session,
    *,
    context: SessionContext,
    client_id: str,
    document_type: str,
    label: str | None,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
) -> ClientKycDocumentRecord:
    from caseops_api.services.clients import _get_client_model, _lock_private_client_writer

    require_read_only_upload_session(
        session, detail="KYC upload requires a read-only session before its I/O boundary.",
    )
    document_type, label = _validated_type_and_label(document_type, label)

    def admit() -> Client:
        _lock_private_client_writer(
            session, context=context, client_id=client_id,
            required_capability="clients:kyc_submit",
        )
        client = _get_client_model(session, context=context, client_id=client_id)
        _assert_upload_open(client)
        return client

    admit()
    _verify_kyc_file(filename=filename, content_type=content_type, stream=stream)
    company_id = context.company.id
    document_id = str(uuid4())
    session.rollback()
    stored_key: str | None = None
    commit_attempted = False
    try:
        stored = _store_kyc_file(
            session, company_id=company_id, client_id=client_id,
            document_id=document_id, filename=filename, stream=stream,
        )
        stored_key = stored.storage_key
        client = admit()
        assert_storage_quota_allows_upload(
            session, company_id=company_id, matter_id=None,
            incoming_size_bytes=stored.size_bytes,
        )
        doc = ClientKycDocument(
            id=document_id,
            company_id=company_id,
            client_id=client.id,
            document_type=document_type,
            label=label,
            # A file name often carries the person's number: never keep a
            # full Aadhaar number in it (BUG-003).
            original_filename=mask_full_aadhaar_in_filename(sanitize_filename(filename)),
            content_type=content_type,
            size_bytes=stored.size_bytes,
            sha256_hex=stored.sha256_hex,
            storage_key=stored.storage_key,
            uploaded_by_membership_id=context.membership.id,
        )
        session.add(doc)
        session.flush()
        record_from_context(
            session, context,
            action="client.kyc_document_uploaded",
            target_type="client",
            target_id=client.id,
            metadata=_upload_audit_metadata(doc),
        )
        commit_attempted = True
        session.commit()
    except StorageQuotaExceeded as exc:
        session.rollback()
        _discard(stored_key, document_id)
        record_from_context(
            session, context,
            action="storage_quota.upload_blocked",
            target_type="client",
            target_id=client_id,
            result=AuditResult.DENIED,
            metadata={**exc.audit_metadata(), "actor_surface": "client_kyc"},
            commit=True,
        )
        raise exc.to_http_exception() from exc
    except Exception:
        session.rollback()
        if not commit_attempted:
            _discard(stored_key, document_id)
        else:
            logger.warning("KYC document upload commit outcome is uncertain")
        raise
    session.refresh(doc)
    return _document_record(doc, names=_uploader_names(session, [doc]))


def get_client_kyc_document_download(
    session: Session,
    *,
    context: SessionContext,
    client_id: str,
    document_id: str,
    inline: bool,
) -> tuple[ClientKycDocument, str, str, str]:
    """(document, path, media type, disposition). Audits every open."""
    from caseops_api.services.clients import _get_client_model

    client = _get_client_model(session, context=context, client_id=client_id)
    _require_kyc_reader(session, context)
    # Retired files stay openable to firm users: they are decision evidence.
    doc = _client_document(
        session, company_id=context.company.id, client_id=client.id,
        document_id=document_id, include_retired=True,
    )
    media_type, disposition = _download_disposition(doc, inline)
    path = _resolve_bytes(doc)
    record_from_context(
        session, context,
        action="client.kyc_document_viewed" if inline else "client.kyc_document_downloaded",
        target_type="client",
        target_id=client.id,
        metadata={"document_id": doc.id, "document_type": doc.document_type},
        commit=True,
    )
    return doc, path, media_type, disposition


def remove_client_kyc_document(
    session: Session, *, context: SessionContext, client_id: str, document_id: str,
) -> str:
    from caseops_api.services.clients import _get_client_model, _lock_private_client_writer

    _lock_private_client_writer(
        session, context=context, client_id=client_id,
        required_capability="clients:kyc_submit",
    )
    client = _get_client_model(session, context=context, client_id=client_id)
    _assert_upload_open(client)
    doc = _client_document(
        session, company_id=context.company.id, client_id=client.id, document_id=document_id,
    )
    metadata = {"document_id": doc.id, "document_type": doc.document_type}
    outcome, storage_key = _remove_document(doc, session)
    record_from_context(
        session, context,
        action="client.kyc_document_removed",
        target_type="client",
        target_id=client.id,
        metadata={**metadata, "outcome": outcome},
    )
    session.commit()
    _delete_after_commit(storage_key, document_id)
    return outcome


# ---------------------------------------------------------------------------
# Client portal
# ---------------------------------------------------------------------------


def _portal_client(
    session: Session, *, portal_user: PortalUser, matter_id: str, client_id: str,
) -> tuple[Matter, Client]:
    """The client must be linked to a Matter the portal user holds a live
    client grant on. Every miss is the same 404 (no enumeration)."""
    from caseops_api.services.portal_matters import _assert_grant

    matter, _grant = _assert_grant(
        session, portal_user=portal_user, matter_id=matter_id, role="client",
    )
    target = session.scalar(
        select(Client)
        .join(MatterClientAssignment, MatterClientAssignment.client_id == Client.id)
        .where(
            MatterClientAssignment.matter_id == matter.id,
            Client.id == client_id,
            Client.company_id == portal_user.company_id,
        )
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found for this matter.",
        )
    return matter, target


def _admit_portal_kyc_write(
    session: Session,
    *,
    company_id: str,
    portal_user_id: str,
    session_cutoff: datetime | None,
    matter_id: str,
    client_id: str,
    operation: str,
) -> tuple[PortalUser, Matter, Client]:
    from caseops_api.services.matter_operational_guard import require_operational_matter
    from caseops_api.services.portal_outside_counsel import _upload_utc
    from caseops_api.services.private_retrieval import lock_private_authority_writer

    with session.no_autoflush:
        lock_private_authority_writer(session, company_id=company_id)
        user = session.scalar(
            select(PortalUser)
            .where(PortalUser.id == portal_user_id, PortalUser.company_id == company_id)
            .with_for_update(of=PortalUser, key_share=True)
            .execution_options(populate_existing=True)
        )
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="Portal user is no longer active.")
        if _upload_utc(user.sessions_valid_after) != _upload_utc(session_cutoff):
            raise HTTPException(
                status_code=401, detail="Portal session was revoked. Sign in again.",
            )
        matter, client = _portal_client(
            session, portal_user=user, matter_id=matter_id, client_id=client_id,
        )
        matter = require_operational_matter(session, matter=matter, operation=operation)
        _assert_upload_open(client)
    return user, matter, client


def _portal_audit(
    session: Session,
    *,
    portal_user: PortalUser,
    action: str,
    client: Client,
    matter_id: str,
    metadata: dict,
    ip: str | None,
    commit: bool,
) -> None:
    record_audit(
        session,
        company_id=portal_user.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label=f"portal:{portal_user.email}",
        action=action,
        target_type="client",
        target_id=client.id,
        matter_id=matter_id,
        result=AuditResult.SUCCESS,
        metadata={"portal_user_id": portal_user.id, **metadata},
        ip=ip,
        commit=commit,
    )


def list_portal_kyc_documents(
    session: Session, *, portal_user: PortalUser, matter_id: str, client_id: str,
) -> ClientKycDocumentListResponse:
    _matter, client = _portal_client(
        session, portal_user=portal_user, matter_id=matter_id, client_id=client_id,
    )
    documents = current_kyc_documents(
        session, company_id=portal_user.company_id, client_id=client.id,
    )
    own = [doc for doc in documents if doc.uploaded_by_portal_user_id == portal_user.id]
    # Requirements count the whole current pack (files the firm uploaded
    # included) so the portal user is not asked to upload what is on file.
    return _list_response(session, client=client, all_current=documents, visible=own)


def upload_portal_kyc_document(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    client_id: str,
    document_type: str,
    label: str | None,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
    request_ip: str | None = None,
) -> ClientKycDocumentRecord:
    require_read_only_upload_session(
        session, detail="KYC upload requires a read-only session before its I/O boundary.",
    )
    document_type, label = _validated_type_and_label(document_type, label)
    company_id, portal_user_id, cutoff = (
        portal_user.company_id, portal_user.id, portal_user.sessions_valid_after,
    )

    def admit() -> tuple[PortalUser, Matter, Client]:
        return _admit_portal_kyc_write(
            session, company_id=company_id, portal_user_id=portal_user_id,
            session_cutoff=cutoff, matter_id=matter_id, client_id=client_id,
            operation="upload KYC documents",
        )

    admit()
    _verify_kyc_file(filename=filename, content_type=content_type, stream=stream)
    document_id = str(uuid4())
    session.rollback()
    stored_key: str | None = None
    commit_attempted = False
    try:
        stored = _store_kyc_file(
            session, company_id=company_id, client_id=client_id,
            document_id=document_id, filename=filename, stream=stream,
        )
        stored_key = stored.storage_key
        user, matter, client = admit()
        assert_storage_quota_allows_upload(
            session, company_id=company_id, matter_id=None,
            incoming_size_bytes=stored.size_bytes,
        )
        doc = ClientKycDocument(
            id=document_id,
            company_id=company_id,
            client_id=client.id,
            document_type=document_type,
            label=label,
            # A file name often carries the person's number: never keep a
            # full Aadhaar number in it (BUG-003).
            original_filename=mask_full_aadhaar_in_filename(sanitize_filename(filename)),
            content_type=content_type,
            size_bytes=stored.size_bytes,
            sha256_hex=stored.sha256_hex,
            storage_key=stored.storage_key,
            uploaded_by_portal_user_id=user.id,
        )
        session.add(doc)
        session.flush()
        _portal_audit(
            session, portal_user=user, action="portal.kyc_document_uploaded",
            client=client, matter_id=matter.id, metadata=_upload_audit_metadata(doc),
            ip=request_ip, commit=False,
        )
        commit_attempted = True
        session.commit()
    except StorageQuotaExceeded as exc:
        session.rollback()
        _discard(stored_key, document_id)
        record_audit(
            session,
            company_id=company_id,
            actor_type=AuditActorType.SYSTEM,
            actor_label=f"portal:{portal_user.email}",
            target_type="client",
            target_id=client_id,
            matter_id=matter_id,
            action="storage_quota.upload_blocked",
            result=AuditResult.DENIED,
            metadata={**exc.audit_metadata(), "actor_surface": "client_portal_kyc"},
            ip=request_ip,
            commit=True,
        )
        raise exc.to_http_exception() from exc
    except Exception:
        session.rollback()
        if not commit_attempted:
            _discard(stored_key, document_id)
        else:
            logger.warning("Portal KYC document upload commit outcome is uncertain")
        raise
    session.refresh(doc)
    return _document_record(doc, names={})


def get_portal_kyc_document_download(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    client_id: str,
    document_id: str,
    inline: bool,
    request_ip: str | None = None,
) -> tuple[ClientKycDocument, str, str, str]:
    matter, client = _portal_client(
        session, portal_user=portal_user, matter_id=matter_id, client_id=client_id,
    )
    doc = _client_document(
        session, company_id=portal_user.company_id, client_id=client.id,
        document_id=document_id,
    )
    # A portal user opens only the files they uploaded themselves.
    if doc.uploaded_by_portal_user_id != portal_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    media_type, disposition = _download_disposition(doc, inline)
    path = _resolve_bytes(doc)
    _portal_audit(
        session, portal_user=portal_user,
        action="portal.kyc_document_viewed" if inline else "portal.kyc_document_downloaded",
        client=client, matter_id=matter.id,
        metadata={"document_id": doc.id, "document_type": doc.document_type},
        ip=request_ip, commit=True,
    )
    return doc, path, media_type, disposition


def remove_portal_kyc_document(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    client_id: str,
    document_id: str,
    request_ip: str | None = None,
) -> str:
    user, matter, client = _admit_portal_kyc_write(
        session, company_id=portal_user.company_id, portal_user_id=portal_user.id,
        session_cutoff=portal_user.sessions_valid_after, matter_id=matter_id,
        client_id=client_id, operation="remove KYC documents",
    )
    doc = _client_document(
        session, company_id=user.company_id, client_id=client.id, document_id=document_id,
    )
    if doc.uploaded_by_portal_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    metadata = {"document_id": doc.id, "document_type": doc.document_type}
    outcome, storage_key = _remove_document(doc, session)
    _portal_audit(
        session, portal_user=user, action="portal.kyc_document_removed",
        client=client, matter_id=matter.id, metadata={**metadata, "outcome": outcome},
        ip=request_ip, commit=False,
    )
    session.commit()
    _delete_after_commit(storage_key, document_id)
    return outcome


__all__ = [
    "KYC_ACCEPTED_EXTENSIONS",
    "KYC_DOCUMENT_OPENED_ACTIONS",
    "KYC_DOCUMENT_TYPE_OPTIONS",
    "KYC_FILE_RESPONSE_HEADERS",
    "KYC_REQUIREMENTS",
    "STORAGE_NAMESPACE",
    "UPLOAD_OPEN_STATUSES",
    "assert_kyc_pack_complete",
    "current_kyc_documents",
    "documents_opened_by_reviewer",
    "get_client_kyc_document_download",
    "get_portal_kyc_document_download",
    "kyc_display_filename",
    "kyc_requirement_records",
    "list_client_kyc_documents",
    "list_portal_kyc_documents",
    "record_kyc_review",
    "remove_client_kyc_document",
    "remove_portal_kyc_document",
    "review_audit_metadata",
    "upload_client_kyc_document",
    "upload_portal_kyc_document",
]
