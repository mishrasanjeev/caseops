"""Phase B / J12 / M11 — communications log service.

Slice 1: manual logging only. The lawyer types into a "Log
communication" form and we record what they pasted in. Slice 2 will
add a Send-via-SendGrid path on the same row (status pivots from
``logged`` → ``queued`` → ``sent`` → ``delivered``).

Tenant isolation contract: every read and every write joins on
``Matter.company_id == context.company.id``. Without that join a
matter_id could be guessed and another tenant's history disclosed.
The service helper that loads the matter (``_load_matter``) raises
404 — we never report 403 on a matter the caller doesn't own
because that confirms the matter exists.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from datetime import UTC, datetime
from io import BytesIO

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    DocumentProcessingAction,
    DocumentProcessingTargetType,
    EmailTemplate,
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterNote,
    PortalUser,
    PortalUserRole,
)
from caseops_api.schemas.communications import (
    CommunicationCreateRequest,
    CommunicationListResponse,
    CommunicationRecord,
    CommunicationTimelineAttachmentReference,
    CommunicationTimelineFilter,
    CommunicationTimelineItem,
    CommunicationTimelineResponse,
    InboundEmailAttachmentImport,
    InboundEmailImportRequest,
    InboundEmailImportResponse,
)
from caseops_api.schemas.email_templates import EmailSendRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.document_jobs import enqueue_processing_job
from caseops_api.services.document_storage import (
    delete_stored_document,
    persist_matter_attachment,
    resolve_storage_path,
    sanitize_filename,
)
from caseops_api.services.email_templates import render_template
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext
from caseops_api.services.storage_governance import (
    StorageQuotaExceeded,
    assert_storage_quota_allows_upload,
    record_storage_quota_blocked_upload,
)

logger = logging.getLogger(__name__)

_EMAIL_BODY_ATTACHMENT_TYPE = "correspondence"
_EMAIL_BODY_LIFECYCLE_STAGE = "administrative"
_MAX_AUDIT_HASH_LEN = 16
_TIMELINE_LIMIT = 500


def _load_matter(
    session: Session, *, context: SessionContext, matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        # Same 404 the rest of the matter surface returns when the
        # caller doesn't own the matter — never confirm existence to
        # an unauthorised tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def list_matter_communications(
    session: Session, *, context: SessionContext, matter_id: str,
) -> CommunicationListResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    rows = list(
        session.scalars(
            select(Communication)
            .where(Communication.matter_id == matter.id)
            .order_by(Communication.occurred_at.desc())
        )
    )
    return CommunicationListResponse(
        matter_id=matter.id,
        communications=[CommunicationRecord.model_validate(r) for r in rows],
    )


def _as_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _timeline_preview(text: str | None, *, max_chars: int = 320) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _is_imported_email(row: Communication) -> bool:
    metadata = row.metadata_json or {}
    return isinstance(metadata, dict) and (
        metadata.get("source") == "manual_inbound_email_import"
        or metadata.get("automation_mode") == "manual_only"
    )


def _communication_visibility(row: Communication) -> str:
    metadata = row.metadata_json or {}
    if _is_imported_email(row):
        return "imported_email"
    if isinstance(metadata, dict):
        if metadata.get("portal_visible") is False:
            return "internal"
        if metadata.get("portal_user_id"):
            return "client_visible"
        if (
            metadata.get("outside_counsel_portal_user_id")
            or metadata.get("actor_surface") == "outside_counsel_portal"
        ):
            return "outside_counsel_visible"
    return "firm_only"


def _communication_item_type(row: Communication) -> str:
    metadata = row.metadata_json or {}
    if _is_imported_email(row):
        return "imported_email"
    if (
        _as_value(row.channel) == CommunicationChannel.NOTE.value
        and isinstance(metadata, dict)
        and metadata.get("portal_user_id")
    ):
        return "client_visible_note"
    if (
        isinstance(metadata, dict)
        and (
            metadata.get("outside_counsel_portal_user_id")
            or metadata.get("actor_surface") == "outside_counsel_portal"
        )
    ):
        return "outside_counsel_visible_update"
    return "platform_message"


def _communication_thread_key(row: Communication) -> str | None:
    if _as_value(row.channel) != CommunicationChannel.EMAIL.value:
        return None
    metadata = row.metadata_json or {}
    if isinstance(metadata, dict):
        for key in (
            "provider_thread_id",
            "thread_id",
            "conversation_id",
            "provider_conversation_id",
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                provider = _normalised_provider(
                    str(metadata.get("provider") or "email")
                )
                return f"{provider}:{value.strip()}"
    return row.external_message_id


def _communication_title(row: Communication) -> str:
    if row.subject and row.subject.strip():
        return row.subject.strip()
    channel = _as_value(row.channel)
    direction = _as_value(row.direction)
    if _is_imported_email(row):
        return "Imported email"
    return f"{str(channel).replace('_', ' ').title()} ({direction})"


def _communication_actor(row: Communication) -> str | None:
    metadata = row.metadata_json or {}
    if _is_imported_email(row):
        sender_name = metadata.get("sender_name") if isinstance(metadata, dict) else None
        return str(sender_name).strip() if sender_name else "Imported email sender"
    if isinstance(metadata, dict):
        if metadata.get("portal_user_id"):
            return "Client portal"
        if (
            metadata.get("outside_counsel_portal_user_id")
            or metadata.get("actor_surface") == "outside_counsel_portal"
        ):
            return "Outside counsel portal"
    if row.recipient_name:
        return row.recipient_name
    return "Firm user"


def _timeline_attachment_reference(
    attachment: MatterAttachment,
) -> CommunicationTimelineAttachmentReference:
    return CommunicationTimelineAttachmentReference(
        id=attachment.id,
        filename=attachment.original_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        document_type=attachment.document_type,
        uploaded_by_membership_id=attachment.uploaded_by_membership_id,
        submitted_by_portal_user_id=attachment.submitted_by_portal_user_id,
        created_at=attachment.created_at,
    )


def _attachment_visibility(
    attachment: MatterAttachment,
    *,
    email_attachment_ids: set[str],
    portal_roles_by_id: dict[str, str],
) -> str:
    if attachment.id in email_attachment_ids:
        return "imported_email"
    if attachment.submitted_by_portal_user_id:
        role = portal_roles_by_id.get(attachment.submitted_by_portal_user_id)
        if role == PortalUserRole.OUTSIDE_COUNSEL.value:
            return "outside_counsel_visible"
        return "client_visible"
    return "firm_only"


def _attachment_preview(
    attachment: MatterAttachment, *, email_attachment_ids: set[str],
) -> str:
    if attachment.id in email_attachment_ids:
        if attachment.original_filename == "email-body.txt":
            return "Email body is stored as a matter attachment; body content is not shown here."
        return "Attachment imported from a manually selected email."
    if attachment.submitted_by_portal_user_id:
        return "Portal-uploaded matter attachment reference."
    return "Matter attachment reference."


def _timeline_filter_matches(
    item: CommunicationTimelineItem,
    selected: CommunicationTimelineFilter,
) -> bool:
    if selected == "all":
        return True
    if selected == "email":
        return item.item_type in {"imported_email", "email_thread"} or (
            item.channel == "email"
        ) or item.visibility == "imported_email"
    if selected == "platform":
        return item.item_type in {
            "platform_message",
            "client_visible_note",
            "outside_counsel_visible_update",
        } and item.visibility != "imported_email"
    if selected == "notes":
        return item.item_type in {"internal_note", "client_visible_note"} or (
            item.channel == "note"
        )
    if selected == "attachments":
        return item.item_type == "attachment"
    if selected == "internal":
        return item.visibility in {"internal", "firm_only"}
    return True


def list_matter_communication_timeline(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    selected_filter: CommunicationTimelineFilter = "all",
) -> CommunicationTimelineResponse:
    """Read-only unified matter communications timeline.

    ADP-05 deliberately composes existing records only: communications,
    manually imported email artifacts, internal matter notes, and matter
    attachment references. It does not poll mailboxes, accept provider
    webhooks, copy payloads, or expose storage keys/full email bodies.
    """
    matter = _load_matter(session, context=context, matter_id=matter_id)
    communications = list(
        session.scalars(
            select(Communication)
            .where(Communication.matter_id == matter.id)
            .order_by(Communication.occurred_at.asc(), Communication.created_at.asc())
            .limit(_TIMELINE_LIMIT)
        )
    )
    notes = list(
        session.scalars(
            select(MatterNote)
            .where(MatterNote.matter_id == matter.id)
            .order_by(MatterNote.created_at.asc())
            .limit(_TIMELINE_LIMIT)
        )
    )
    attachments = list(
        session.scalars(
            select(MatterAttachment)
            .where(MatterAttachment.matter_id == matter.id)
            .order_by(MatterAttachment.created_at.asc())
            .limit(_TIMELINE_LIMIT)
        )
    )

    thread_counts: dict[str, int] = {}
    for row in communications:
        thread_key = _communication_thread_key(row)
        if thread_key:
            thread_counts[thread_key] = thread_counts.get(thread_key, 0) + 1

    email_attachment_ids: set[str] = set()
    email_attachment_sources: dict[str, Communication] = {}
    for row in communications:
        metadata = row.metadata_json or {}
        if not isinstance(metadata, dict) or not _is_imported_email(row):
            continue
        ids = list(metadata.get("attachment_ids") or [])
        body_attachment_id = metadata.get("body_attachment_id")
        if body_attachment_id:
            ids.append(body_attachment_id)
        for attachment_id in ids:
            if isinstance(attachment_id, str):
                email_attachment_ids.add(attachment_id)
                email_attachment_sources[attachment_id] = row

    portal_ids = {
        attachment.submitted_by_portal_user_id
        for attachment in attachments
        if attachment.submitted_by_portal_user_id
    }
    portal_roles_by_id: dict[str, str] = {}
    if portal_ids:
        portal_roles_by_id = {
            user.id: user.role
            for user in session.scalars(
                select(PortalUser).where(
                    PortalUser.company_id == context.company.id,
                    PortalUser.id.in_(portal_ids),
                )
            )
        }

    items: list[CommunicationTimelineItem] = []
    for row in communications:
        thread_key = _communication_thread_key(row)
        metadata = {
            "thread_message_count": thread_counts.get(thread_key, 0)
            if thread_key
            else 0,
            "has_attachments": bool(
                isinstance(row.metadata_json, dict)
                and row.metadata_json.get("attachment_ids")
            ),
            "body_is_preview": _is_imported_email(row),
        }
        items.append(
            CommunicationTimelineItem(
                id=f"communication:{row.id}",
                item_type=_communication_item_type(row),
                visibility=_communication_visibility(row),
                occurred_at=row.occurred_at,
                title=_communication_title(row),
                preview=_timeline_preview(row.body),
                actor_label=_communication_actor(row),
                direction=_as_value(row.direction),
                channel=_as_value(row.channel),
                status=_as_value(row.status),
                thread_key=thread_key,
                source_type="communication",
                source_id=row.id,
                communication_id=row.id,
                metadata=metadata,
            )
        )

    for note in notes:
        items.append(
            CommunicationTimelineItem(
                id=f"note:{note.id}",
                item_type="internal_note",
                visibility="internal",
                occurred_at=note.created_at,
                title="Internal note",
                preview=_timeline_preview(note.body),
                actor_label="Firm user",
                source_type="matter_note",
                source_id=note.id,
                note_id=note.id,
                metadata={"internal_only": True},
            )
        )

    for attachment in attachments:
        email_source = email_attachment_sources.get(attachment.id)
        source_label = "attachment"
        metadata = {
            "size_bytes": attachment.size_bytes,
            "is_email_body_attachment": (
                attachment.original_filename == "email-body.txt"
                and attachment.id in email_attachment_ids
            ),
            "from_imported_email": attachment.id in email_attachment_ids,
        }
        if email_source is not None:
            source_label = "imported_email_attachment"
            metadata["communication_id"] = email_source.id
        items.append(
            CommunicationTimelineItem(
                id=f"attachment:{attachment.id}",
                item_type="attachment",
                visibility=_attachment_visibility(
                    attachment,
                    email_attachment_ids=email_attachment_ids,
                    portal_roles_by_id=portal_roles_by_id,
                ),
                occurred_at=attachment.created_at,
                title=f"Attachment: {attachment.original_filename}",
                preview=_attachment_preview(
                    attachment,
                    email_attachment_ids=email_attachment_ids,
                ),
                actor_label="Attachment reference",
                thread_key=_communication_thread_key(email_source)
                if email_source is not None
                else None,
                source_type=source_label,
                source_id=attachment.id,
                communication_id=email_source.id if email_source is not None else None,
                attachment_id=attachment.id,
                attachment=_timeline_attachment_reference(attachment),
                metadata=metadata,
            )
        )

    filtered = [
        item for item in items if _timeline_filter_matches(item, selected_filter)
    ]
    filtered.sort(key=lambda item: (item.occurred_at, item.id))
    return CommunicationTimelineResponse(
        matter_id=matter.id,
        filter=selected_filter,
        generated_at=datetime.now(UTC),
        items=filtered[:_TIMELINE_LIMIT],
    )


def create_matter_communication(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: CommunicationCreateRequest,
) -> CommunicationRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="log a communication",
    )
    occurred = payload.occurred_at or datetime.now(UTC)
    row = Communication(
        company_id=context.company.id,
        matter_id=matter.id,
        client_id=payload.client_id,
        direction=payload.direction,
        channel=payload.channel,
        subject=payload.subject,
        body=payload.body,
        recipient_name=payload.recipient_name,
        recipient_email=str(payload.recipient_email)
        if payload.recipient_email else None,
        recipient_phone=payload.recipient_phone,
        # Slice 1 is manual logging — terminal status is LOGGED. Slice
        # 2's send path will start at QUEUED instead.
        status=CommunicationStatus.LOGGED,
        occurred_at=occurred,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return CommunicationRecord.model_validate(row)


def _normalised_provider(provider: str) -> str:
    return provider.strip().lower()


def _external_message_id(provider: str, provider_message_id: str) -> str:
    return f"{_normalised_provider(provider)}:{provider_message_id.strip()}"


def _message_hash(provider_message_id: str) -> str:
    return hashlib.sha256(provider_message_id.encode("utf-8")).hexdigest()[
        :_MAX_AUDIT_HASH_LEN
    ]


def _email_domain(address: str) -> str | None:
    if "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].strip().lower()
    return domain or None


def _preview_from_payload(payload: InboundEmailImportRequest) -> str:
    if payload.body_preview and payload.body_preview.strip():
        return payload.body_preview.strip()
    if payload.body_text and payload.body_text.strip():
        return "[Email body stored as matter attachment; preview not provided]"
    return "[No email body preview provided]"


def _decode_attachment_content(attachment: InboundEmailAttachmentImport) -> BytesIO:
    encoded = attachment.content_base64.strip()
    max_bytes = get_settings().max_attachment_size_bytes
    max_encoded_chars = ((max_bytes + 2) // 3) * 4 + 4
    if len(encoded) > max_encoded_chars:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Attachments must be {max_bytes} bytes or smaller.",
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Attachment {attachment.filename!r} is not valid base64.",
        ) from exc
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Attachments must be {max_bytes} bytes or smaller.",
        )
    return BytesIO(raw)


def _persist_inbound_attachment(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    filename: str,
    content_type: str | None,
    stream: BytesIO,
) -> tuple[MatterAttachment, str, str]:
    """Persist one imported email artifact without committing.

    This mirrors the matter upload pipeline: upload validation, storage,
    virus scan, MatterAttachment row, processing job, and matter activity.
    The caller owns the transaction so the Communication row, metadata,
    audit event, and all imported attachments commit together.
    """
    from caseops_api.services.file_security import verify_upload
    from caseops_api.services.virus_scan import reject_if_infected

    verify_upload(filename=filename, content_type=content_type, stream=stream)
    attachment = MatterAttachment(
        matter_id=matter.id,
        uploaded_by_membership_id=context.membership.id,
        original_filename=sanitize_filename(filename),
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
        document_type=_EMAIL_BODY_ATTACHMENT_TYPE,
        lifecycle_stage=_EMAIL_BODY_LIFECYCLE_STAGE,
    )
    session.add(attachment)
    session.flush()

    stored = persist_matter_attachment(
        company_id=context.company.id,
        matter_id=matter.id,
        attachment_id=attachment.id,
        filename=filename,
        stream=stream,
        before_store=lambda size_bytes: assert_storage_quota_allows_upload(
            session,
            company_id=context.company.id,
            matter_id=matter.id,
            incoming_size_bytes=size_bytes,
        ),
    )
    try:
        reject_if_infected(resolve_storage_path(stored.storage_key), filename=filename)
    except Exception:
        try:
            delete_stored_document(stored.storage_key)
        except Exception:
            logger.warning(
                "inbound_email.attachment_cleanup_failed",
                extra={"attachment_id": attachment.id},
            )
        raise

    attachment.storage_key = stored.storage_key
    attachment.size_bytes = stored.size_bytes
    attachment.sha256_hex = stored.sha256_hex
    job = enqueue_processing_job(
        session,
        company_id=context.company.id,
        requested_by_membership_id=context.membership.id,
        target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
        attachment_id=attachment.id,
        action=DocumentProcessingAction.INITIAL_INDEX,
    )
    session.add(attachment)
    session.add(
        MatterActivity(
            matter_id=matter.id,
            actor_membership_id=context.membership.id,
            event_type="inbound_email_attachment_added",
            title="Inbound email artifact imported",
            detail=f"{attachment.original_filename} queued for document processing.",
        )
    )
    return attachment, job.id, stored.storage_key


def _existing_import_response(
    *,
    matter_id: str,
    row: Communication,
) -> InboundEmailImportResponse:
    metadata = row.metadata_json or {}
    attachment_ids = list(metadata.get("attachment_ids") or [])
    body_attachment_id = metadata.get("body_attachment_id")
    if body_attachment_id and body_attachment_id not in attachment_ids:
        attachment_ids = [body_attachment_id, *attachment_ids]
    return InboundEmailImportResponse(
        matter_id=matter_id,
        communication=CommunicationRecord.model_validate(row),
        duplicate=True,
        body_attachment_id=body_attachment_id,
        attachment_ids=attachment_ids,
        processing_job_ids=list(metadata.get("processing_job_ids") or []),
    )


def import_inbound_email(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: InboundEmailImportRequest,
) -> InboundEmailImportResponse:
    """Import one explicitly selected inbound email into a matter.

    No mailbox sweep, no autonomous polling, and no provider webhook
    acceptance happens here. A signed-in fee-earner selects the matter,
    the standard matter access rules run, then we persist a preview in
    Communications and the full body/attachments through MatterAttachment.
    """
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="import an email",
    )
    provider = _normalised_provider(payload.provider)
    provider_message_id = payload.provider_message_id.strip()
    external_id = _external_message_id(provider, provider_message_id)

    existing = session.scalar(
        select(Communication).where(
            Communication.company_id == context.company.id,
            Communication.matter_id == matter.id,
            Communication.external_message_id == external_id,
        )
    )
    if existing is not None:
        return _existing_import_response(matter_id=matter.id, row=existing)

    received_at = payload.received_at or datetime.now(UTC)
    body_preview = _preview_from_payload(payload)
    sender_email = str(payload.sender_email).strip().lower()
    stored_keys: list[str] = []
    imported_attachments: list[MatterAttachment] = []
    processing_job_ids: list[str] = []
    body_attachment_id: str | None = None

    row = Communication(
        company_id=context.company.id,
        matter_id=matter.id,
        direction=CommunicationDirection.INBOUND,
        channel=CommunicationChannel.EMAIL,
        subject=payload.subject.strip() if payload.subject else None,
        body=body_preview,
        recipient_name=payload.sender_name.strip() if payload.sender_name else None,
        recipient_email=sender_email,
        status=CommunicationStatus.LOGGED,
        occurred_at=received_at,
        external_message_id=external_id,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)

    try:
        session.flush()
        if payload.body_text and payload.body_text.strip():
            body_stream = BytesIO(payload.body_text.encode("utf-8"))
            body_attachment, job_id, storage_key = _persist_inbound_attachment(
                session,
                context=context,
                matter=matter,
                filename="email-body.txt",
                content_type="text/plain",
                stream=body_stream,
            )
            imported_attachments.append(body_attachment)
            processing_job_ids.append(job_id)
            stored_keys.append(storage_key)
            body_attachment_id = body_attachment.id

        for attachment_payload in payload.attachments:
            attachment, job_id, storage_key = _persist_inbound_attachment(
                session,
                context=context,
                matter=matter,
                filename=attachment_payload.filename,
                content_type=attachment_payload.content_type,
                stream=_decode_attachment_content(attachment_payload),
            )
            imported_attachments.append(attachment)
            processing_job_ids.append(job_id)
            stored_keys.append(storage_key)

        attachment_ids = [attachment.id for attachment in imported_attachments]
        row.metadata_json = {
            "source": "manual_inbound_email_import",
            "provider": provider,
            "provider_message_id": provider_message_id,
            "sender_email": sender_email,
            "sender_name": payload.sender_name.strip() if payload.sender_name else None,
            "to_recipients": [str(email).lower() for email in payload.to_recipients],
            "cc_recipients": [str(email).lower() for email in payload.cc_recipients],
            "bcc_recipient_count": len(payload.bcc_recipients),
            "received_at": received_at.isoformat(),
            "body_preview_chars": len(body_preview),
            "body_attachment_id": body_attachment_id,
            "attachment_ids": attachment_ids,
            "processing_job_ids": processing_job_ids,
            "match_basis": "explicit_matter_selection",
            "automation_mode": "manual_only",
        }
        session.add(row)
        record_from_context(
            session,
            context,
            action="inbound_email.imported",
            target_type="communication",
            target_id=row.id,
            matter_id=matter.id,
            metadata={
                "provider": provider,
                "provider_message_id_hash": _message_hash(provider_message_id),
                "sender_domain": _email_domain(sender_email),
                "attachment_count": len(payload.attachments),
                "has_body_attachment": body_attachment_id is not None,
                "match_basis": "explicit_matter_selection",
                "automation_mode": "manual_only",
            },
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        for storage_key in stored_keys:
            try:
                delete_stored_document(storage_key)
            except Exception:
                logger.warning("inbound_email.duplicate_cleanup_failed")
        existing_after_race = session.scalar(
            select(Communication).where(
                Communication.company_id == context.company.id,
                Communication.matter_id == matter.id,
                Communication.external_message_id == external_id,
            )
        )
        if existing_after_race is not None:
            return _existing_import_response(matter_id=matter.id, row=existing_after_race)
        raise
    except StorageQuotaExceeded as exc:
        session.rollback()
        for storage_key in stored_keys:
            try:
                delete_stored_document(storage_key)
            except Exception:
                logger.warning("inbound_email.quota_block_cleanup_failed")
        record_storage_quota_blocked_upload(
            session,
            context=context,
            matter_id=matter.id,
            error=exc,
        )
        raise exc.to_http_exception() from exc
    except Exception:
        session.rollback()
        for storage_key in stored_keys:
            try:
                delete_stored_document(storage_key)
            except Exception:
                logger.warning("inbound_email.failed_import_cleanup_failed")
        raise

    session.refresh(row)
    return InboundEmailImportResponse(
        matter_id=matter.id,
        communication=CommunicationRecord.model_validate(row),
        duplicate=False,
        body_attachment_id=body_attachment_id,
        attachment_ids=[attachment.id for attachment in imported_attachments],
        processing_job_ids=processing_job_ids,
    )


def send_matter_email(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: EmailSendRequest,
) -> CommunicationRecord:
    """Phase B M11 slice 2 — Compose & send.

    Picks the named template, renders it with the user-supplied
    variables, dispatches via SendGrid, and writes the resulting
    ``communications`` row. The webhook handler later transitions
    ``status`` from ``sent`` → ``delivered`` / ``opened`` /
    ``bounced`` as events arrive (matched by external_message_id).

    Refuses to send when:

    - the template doesn't belong to the caller's company (404)
    - the template declares required variables the caller did not
      supply (400 — actionable detail lists the missing names)
    - SendGrid isn't configured in this env (503)
    """
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="send an email",
    )

    template = session.scalar(
        select(EmailTemplate).where(
            EmailTemplate.id == payload.template_id,
            EmailTemplate.company_id == context.company.id,
            EmailTemplate.is_active.is_(True),
        )
    )
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email template not found or archived.",
        )

    rendered = render_template(template=template, variables=payload.variables)
    if rendered.missing_variables:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Required template variables are missing: "
                + ", ".join(rendered.missing_variables)
            ),
        )

    settings = get_settings()
    if not (settings.sendgrid_api_key and settings.sendgrid_sender_email):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Email sending is not configured for this workspace. "
                "Ask your workspace admin to set up SendGrid."
            ),
        )

    # BUG-038 (2026-05-09) — pre-flight tenant-scoped suppression
    # check. If the recipient hard-bounced, was dropped, reported
    # spam, or unsubscribed for this tenant via a prior SendGrid
    # event, refuse the send and surface an actionable 422 rather
    # than burn a SendGrid request that will fail/spam-flag again.
    # Auth-flow mailers (account setup, password reset, portal) do
    # NOT call this function and so are not affected — they remain
    # critical for tenant access.
    from caseops_api.services.email_suppression import is_suppressed

    suppression = is_suppressed(
        session,
        company_id=context.company.id,
        recipient_email=str(payload.recipient_email),
    )
    if suppression is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"This address is on the workspace suppression list "
                f"(reason: {suppression.reason}, recorded "
                f"{suppression.last_event_at.isoformat()}). Reach the "
                "recipient through another channel, or have a workspace "
                "admin review and remove the suppression entry."
            ),
        )

    success, message_id, error = _send_via_sendgrid(
        to_email=str(payload.recipient_email),
        recipient_name=payload.recipient_name,
        subject=rendered.subject,
        body_text=rendered.body,
    )
    now = datetime.now(UTC)
    row = Communication(
        company_id=context.company.id,
        matter_id=matter.id,
        client_id=payload.client_id,
        direction=CommunicationDirection.OUTBOUND,
        channel=CommunicationChannel.EMAIL,
        subject=rendered.subject,
        body=rendered.body,
        recipient_name=payload.recipient_name,
        recipient_email=str(payload.recipient_email),
        status=CommunicationStatus.SENT if success else CommunicationStatus.FAILED,
        occurred_at=now,
        external_message_id=message_id,
        metadata_json={
            "template_id": template.id,
            "template_name": template.name,
            "send_error": error,
        } if (template or error) else None,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    if not success:
        # Surface the failure but the row is still persisted so the
        # operator can see it on the Communications tab. The 502 has
        # an actionable detail.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"SendGrid refused the message: {error}. The communication "
                "was logged with status=failed; you can re-send from a "
                "fresh Compose dialog."
            ),
        )
    return CommunicationRecord.model_validate(row)


def _send_via_sendgrid(
    *,
    to_email: str,
    recipient_name: str | None,
    subject: str,
    body_text: str,
    custom_args: dict[str, str] | None = None,
) -> tuple[bool, str | None, str | None]:
    """Direct SendGrid Web API call. Mirrors the helper in
    services.hearing_reminders so we don't pull in the full SDK
    for one POST.

    Returns ``(success, provider_message_id, error)``. On 200/202
    the X-Message-Id header lets the webhook handler tie a delivery
    event back to the originating row.
    """
    import httpx

    settings = get_settings()
    to_block: dict = {"email": to_email}
    if recipient_name:
        to_block["name"] = recipient_name
    response = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [
                {
                    "to": [to_block],
                    **({"custom_args": custom_args} if custom_args else {}),
                }
            ],
            "from": {
                "email": settings.sendgrid_sender_email,
                "name": settings.sendgrid_sender_name,
            },
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body_text},
            ],
        },
        timeout=20,
    )
    if response.status_code in (200, 202):
        msg_id = response.headers.get("X-Message-Id") or response.headers.get(
            "x-message-id"
        )
        return True, msg_id, None
    return (
        False,
        None,
        f"sendgrid {response.status_code}: {response.text[:200]}",
    )


# SendGrid event names we promote to a CommunicationStatus.
_SENDGRID_EVENT_TO_STATUS: dict[str, str] = {
    "delivered": CommunicationStatus.DELIVERED,
    "open": CommunicationStatus.OPENED,
    "bounce": CommunicationStatus.BOUNCED,
    "dropped": CommunicationStatus.BOUNCED,
    "spamreport": CommunicationStatus.BOUNCED,
}

# Status promotion order — never demote (e.g. an "open" event
# arriving after "delivered" should keep the row at OPENED;
# a stray "delivered" arriving after "opened" should not regress).
_STATUS_RANK: dict[str, int] = {
    CommunicationStatus.LOGGED: 0,
    CommunicationStatus.QUEUED: 1,
    CommunicationStatus.FAILED: 2,
    CommunicationStatus.SENT: 3,
    CommunicationStatus.DELIVERED: 4,
    CommunicationStatus.OPENED: 5,
    CommunicationStatus.BOUNCED: 6,
}


def apply_sendgrid_communication_event(
    session: Session, *, event: dict,
) -> bool:
    """Update a ``Communication`` row from a SendGrid event payload.

    Match key is ``sg_message_id`` from the event ↔
    ``Communication.external_message_id`` we stored at send time.
    Returns True when a row was updated; False when there was no
    matching row (event for a different sender / hearing-reminder
    channel — silently ignored).

    Idempotent: replaying the same event is safe; status only moves
    forward in the rank table above. Bounce / dropped / spam_report
    / unsubscribe / group_unsubscribe events also write a tenant-
    scoped ``EmailSuppression`` row so future ``send_matter_email``
    calls to the same address are blocked. Auth-flow mailers
    (account setup, password reset, portal) bypass that suppression
    by design.
    """
    from caseops_api.services.email_suppression import (
        reason_for_event,
        record_suppression,
    )

    sg_message_id = (event.get("sg_message_id") or "").strip()
    event_name = (event.get("event") or "").strip().lower()
    if not sg_message_id or not event_name:
        return False

    target_status = _SENDGRID_EVENT_TO_STATUS.get(event_name)
    suppression_reason = reason_for_event(event_name)
    if target_status is None and suppression_reason is None:
        # Events we neither track on the row (delivered/open/bounce/
        # dropped/spamreport) nor map to suppression
        # (unsubscribe/group_unsubscribe) — drop. Includes
        # processed / click / deferred.
        return False

    # SendGrid mangles message IDs in the X-Message-Id header
    # ("ABCDEF.filterdrecv-12345") and in the webhook's
    # sg_message_id ("ABCDEF.filterdrecv-12345.0"). Match the prefix
    # before the second dot.
    base_id = sg_message_id.split(".")[0]
    row = session.scalar(
        select(Communication).where(
            Communication.external_message_id.like(f"{base_id}%"),
        )
    )
    if row is None:
        return False

    timestamp_iso = event.get("timestamp")
    when = (
        datetime.fromtimestamp(int(timestamp_iso), tz=UTC)
        if isinstance(timestamp_iso, (int, float))
        else datetime.now(UTC)
    )

    if target_status is not None and _STATUS_RANK.get(
        target_status, -1
    ) > _STATUS_RANK.get(row.status, -1):
        row.status = target_status

    if event_name == "delivered" and row.delivered_at is None:
        row.delivered_at = when
    if event_name == "open" and row.opened_at is None:
        row.opened_at = when

    # BUG-038 (2026-05-09) — record tenant-scoped suppression for the
    # exact address SendGrid reported. Prefer event["email"] (the
    # canonical recipient SendGrid sees) over row.recipient_email.
    if suppression_reason is not None:
        event_email = (event.get("email") or "").strip().lower()
        target_email = event_email or (row.recipient_email or "")
        if target_email:
            detail = event.get("reason") or event.get("response")
            record_suppression(
                session,
                company_id=row.company_id,
                recipient_email=target_email,
                reason=suppression_reason,
                detail=str(detail) if detail else None,
                source_message_id=sg_message_id,
            )

    session.flush()
    return True


__all__ = [
    "apply_sendgrid_communication_event",
    "create_matter_communication",
    "import_inbound_email",
    "list_matter_communications",
    "send_matter_email",
]
