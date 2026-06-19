from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    InboundEmailAlias,
    InboundEmailAliasStatus,
    InboundEmailEvent,
    InboundEmailEventStatus,
    Matter,
    MatterNote,
    MatterTask,
    MatterTaskPriority,
    MatterTaskStatus,
)
from caseops_api.schemas.inbound_email import (
    InboundEmailAliasCreateRequest,
    InboundEmailAliasListResponse,
    InboundEmailAliasRecord,
    InboundEmailAliasUpdateRequest,
    InboundEmailEventListResponse,
    InboundEmailEventRecord,
    InboundEmailEventReviewRequest,
    InboundEmailEventReviewResponse,
    InboundEmailWebhookRequest,
    InboundEmailWebhookResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.session_context import SessionContext


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned[:48] or "tenant"


def _alias_record(row: InboundEmailAlias) -> InboundEmailAliasRecord:
    return InboundEmailAliasRecord(
        id=row.id,
        company_id=row.company_id,
        matter_id=row.matter_id,
        alias_type=row.alias_type,  # type: ignore[arg-type]
        alias_address=row.alias_address,
        status=row.status,  # type: ignore[arg-type]
        allowed_senders=list(row.allowed_senders_json or []),
        allowed_domains=list(row.allowed_domains_json or []),
        retention_days=row.retention_days,
        spam_security_status=row.spam_security_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _event_record(row: InboundEmailEvent) -> InboundEmailEventRecord:
    return InboundEmailEventRecord(
        id=row.id,
        company_id=row.company_id,
        alias_id=row.alias_id,
        matched_matter_id=row.matched_matter_id,
        linked_matter_id=row.linked_matter_id,
        communication_id=row.communication_id,
        provider=row.provider,
        provider_message_id=row.provider_message_id,
        from_display=row.from_display,
        to_addresses=list(row.to_addresses_json or []),
        cc_addresses=list(row.cc_addresses_json or []),
        subject=row.subject,
        received_at=row.received_at,
        snippet=row.snippet,
        attachment_metadata=list(row.attachment_metadata_json or []),
        status=row.status,  # type: ignore[arg-type]
        redacted_failure_reason=row.redacted_failure_reason,
        provenance=row.provenance_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _matter_alias_address(context: SessionContext, matter: Matter | None) -> str:
    domain = get_settings().inbound_email_domain.strip().lower()
    tenant_part = _slug(context.company.name or context.company.id)
    if matter is None:
        return f"{tenant_part}@{domain}"
    return f"{tenant_part}+{_slug(matter.matter_code)}@{domain}"


def list_inbound_email_aliases(
    session: Session,
    *,
    context: SessionContext,
) -> InboundEmailAliasListResponse:
    rows = list(
        session.scalars(
            select(InboundEmailAlias)
            .where(InboundEmailAlias.company_id == context.company.id)
            .order_by(InboundEmailAlias.created_at.asc())
        )
    )
    return InboundEmailAliasListResponse(aliases=[_alias_record(row) for row in rows])


def create_inbound_email_alias(
    session: Session,
    *,
    context: SessionContext,
    payload: InboundEmailAliasCreateRequest,
) -> InboundEmailAliasRecord:
    matter = None
    if payload.matter_id:
        matter = session.get(Matter, payload.matter_id)
        if matter is None or matter.company_id != context.company.id:
            raise HTTPException(status_code=404, detail="Matter not found.")
        assert_access(session, context=context, matter=matter)
    alias_type = "matter" if matter else "tenant"
    alias_address = _matter_alias_address(context, matter)
    existing = session.scalar(
        select(InboundEmailAlias).where(
            InboundEmailAlias.company_id == context.company.id,
            InboundEmailAlias.alias_address == alias_address,
        )
    )
    if existing is not None:
        return _alias_record(existing)
    row = InboundEmailAlias(
        company_id=context.company.id,
        matter_id=matter.id if matter else None,
        alias_type=alias_type,
        alias_address=alias_address,
        status=payload.status,
        allowed_senders_json=payload.allowed_senders,
        allowed_domains_json=payload.allowed_domains,
        retention_days=payload.retention_days,
        spam_security_status="provider_unverified",
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="inbound_email.alias.created",
        target_type="inbound_email_alias",
        target_id=row.id,
        matter_id=matter.id if matter else None,
        metadata={
            "alias_type": alias_type,
            "status": row.status,
            "provider_mode": get_settings().inbound_email_provider_mode,
        },
    )
    session.commit()
    return _alias_record(row)


def update_inbound_email_alias(
    session: Session,
    *,
    context: SessionContext,
    alias_id: str,
    payload: InboundEmailAliasUpdateRequest,
) -> InboundEmailAliasRecord:
    row = session.scalar(
        select(InboundEmailAlias).where(
            InboundEmailAlias.id == alias_id,
            InboundEmailAlias.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Inbound email alias not found.")
    if payload.status is not None:
        row.status = payload.status
    if payload.allowed_senders is not None:
        row.allowed_senders_json = payload.allowed_senders
    if payload.allowed_domains is not None:
        row.allowed_domains_json = payload.allowed_domains
    if payload.retention_days is not None:
        row.retention_days = payload.retention_days
    session.add(row)
    record_from_context(
        session,
        context,
        action="inbound_email.alias.updated",
        target_type="inbound_email_alias",
        target_id=row.id,
        matter_id=row.matter_id,
        metadata={"status": row.status},
    )
    session.commit()
    return _alias_record(row)


def _verify_signature(raw_body: bytes, signature: str | None) -> None:
    settings = get_settings()
    if settings.inbound_email_provider_mode == "disabled":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inbound email provider is disabled.",
        )
    if settings.inbound_email_provider_mode == "mock":
        return
    if not settings.inbound_email_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inbound email webhook secret is not configured.",
        )
    expected = hmac.new(
        settings.inbound_email_webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    supplied = (signature or "").removeprefix("sha256=").strip()
    if not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature.")


def _sender_allowed(alias: InboundEmailAlias, sender: str | None) -> bool:
    if not sender:
        return False
    sender_lower = sender.strip().lower()
    allowed_senders = [value.lower() for value in (alias.allowed_senders_json or [])]
    if allowed_senders and sender_lower not in allowed_senders:
        return False
    allowed_domains = [value.lower().lstrip("@") for value in (alias.allowed_domains_json or [])]
    if allowed_domains:
        domain = sender_lower.rsplit("@", 1)[-1]
        return domain in allowed_domains
    return True


def ingest_inbound_email_webhook(
    session: Session,
    *,
    payload: InboundEmailWebhookRequest,
    raw_body: bytes,
    signature: str | None = None,
) -> InboundEmailWebhookResponse:
    _verify_signature(raw_body, signature)
    to_addresses = [address.strip().lower() for address in payload.to_addresses if address.strip()]
    alias = session.scalar(
        select(InboundEmailAlias).where(
            InboundEmailAlias.alias_address.in_(to_addresses),
            InboundEmailAlias.status == InboundEmailAliasStatus.ENABLED,
        )
    )
    if alias is None:
        raise HTTPException(status_code=404, detail="Inbound email alias not found or disabled.")
    existing = session.scalar(
        select(InboundEmailEvent).where(
            InboundEmailEvent.company_id == alias.company_id,
            InboundEmailEvent.provider_message_id == payload.provider_message_id,
        )
    )
    if existing is not None:
        return InboundEmailWebhookResponse(
            accepted=True,
            event_id=existing.id,
            status=existing.status,  # type: ignore[arg-type]
        )
    allowed = _sender_allowed(alias, payload.from_email)
    event = InboundEmailEvent(
        company_id=alias.company_id,
        alias_id=alias.id,
        matched_matter_id=alias.matter_id,
        provider=payload.provider,
        provider_message_id=payload.provider_message_id,
        from_address_hash=_hash(payload.from_email),
        from_display=payload.from_display,
        to_addresses_json=to_addresses,
        cc_addresses_json=[address.strip().lower() for address in payload.cc_addresses],
        subject=payload.subject,
        received_at=payload.received_at or _now(),
        snippet=payload.snippet,
        attachment_metadata_json=[item.model_dump() for item in payload.attachments],
        status=InboundEmailEventStatus.NEW if allowed else InboundEmailEventStatus.REJECTED,
        redacted_failure_reason=None if allowed else "Sender is not allowed for this alias.",
        provenance_json={
            "provider_mode": get_settings().inbound_email_provider_mode,
            "raw_body_imported": False,
            "attachment_bytes_imported": False,
        },
    )
    session.add(event)
    session.commit()
    return InboundEmailWebhookResponse(
        accepted=allowed,
        event_id=event.id,
        status=event.status,  # type: ignore[arg-type]
    )


def list_inbound_email_events(
    session: Session,
    *,
    context: SessionContext,
    status_filter: str | None = None,
    matter_id: str | None = None,
    limit: int = 50,
) -> InboundEmailEventListResponse:
    filters = [InboundEmailEvent.company_id == context.company.id]
    if status_filter:
        filters.append(InboundEmailEvent.status == status_filter)
    if matter_id:
        filters.append(
            (InboundEmailEvent.linked_matter_id == matter_id)
            | (InboundEmailEvent.matched_matter_id == matter_id)
        )
    rows = list(
        session.scalars(
            select(InboundEmailEvent)
            .where(*filters)
            .order_by(InboundEmailEvent.updated_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    )
    visible: list[InboundEmailEvent] = []
    for row in rows:
        target_matter_id = row.linked_matter_id or row.matched_matter_id
        if target_matter_id:
            matter = session.get(Matter, target_matter_id)
            if matter is None:
                continue
            try:
                assert_access(session, context=context, matter=matter)
            except HTTPException:
                continue
        visible.append(row)
    return InboundEmailEventListResponse(
        events=[_event_record(row) for row in visible],
        pending_count=sum(1 for row in visible if row.status == InboundEmailEventStatus.NEW),
    )


def review_inbound_email_event(
    session: Session,
    *,
    context: SessionContext,
    event_id: str,
    payload: InboundEmailEventReviewRequest,
) -> InboundEmailEventReviewResponse:
    event = session.scalar(
        select(InboundEmailEvent).where(
            InboundEmailEvent.id == event_id,
            InboundEmailEvent.company_id == context.company.id,
        )
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Inbound email event not found.")
    note: MatterNote | None = None
    task: MatterTask | None = None
    if payload.action in {"ignore", "reject"}:
        event.status = (
            InboundEmailEventStatus.IGNORED
            if payload.action == "ignore"
            else InboundEmailEventStatus.REJECTED
        )
        session.add(event)
        record_from_context(
            session,
            context,
            action=f"inbound_email.event.{payload.action}",
            target_type="inbound_email_event",
            target_id=event.id,
        )
        session.commit()
        return InboundEmailEventReviewResponse(event=_event_record(event))
    matter_id = payload.matter_id or event.linked_matter_id or event.matched_matter_id
    matter = session.get(Matter, matter_id) if matter_id else None
    if matter is None or matter.company_id != context.company.id:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    if payload.action in {"link_to_matter", "create_note", "create_task"}:
        event.linked_matter_id = matter.id
        event.status = InboundEmailEventStatus.LINKED_METADATA
        if event.communication_id is None:
            communication = Communication(
                company_id=context.company.id,
                matter_id=matter.id,
                direction=CommunicationDirection.INBOUND,
                channel=CommunicationChannel.EMAIL,
                subject=event.subject,
                body=event.snippet,
                recipient_name=event.from_display,
                recipient_email=None,
                status=CommunicationStatus.LOGGED,
                occurred_at=event.received_at,
                external_message_id=f"inbound:{event.provider_message_id}",
                created_by_membership_id=context.membership.id,
                metadata_json={
                    "source": "inbound_email_alias",
                    "provider": event.provider,
                    "provider_message_id_hash": _hash(event.provider_message_id),
                    "raw_body_imported": False,
                },
            )
            session.add(communication)
            session.flush()
            event.communication_id = communication.id
        if payload.action == "create_note":
            note = MatterNote(
                matter_id=matter.id,
                author_membership_id=context.membership.id,
                body=payload.note_body or _default_event_note_body(event),
            )
            session.add(note)
            session.flush()
        if payload.action == "create_task":
            task = MatterTask(
                matter_id=matter.id,
                created_by_membership_id=context.membership.id,
                owner_membership_id=context.membership.id,
                title=(payload.task_title or event.subject or "Review inbound email")[:255],
                description=payload.task_description or event.snippet,
                status=MatterTaskStatus.TODO,
                priority=MatterTaskPriority.MEDIUM,
            )
            session.add(task)
            session.flush()
    elif payload.action == "request_attachment_import":
        event.linked_matter_id = matter.id
        event.status = InboundEmailEventStatus.CONTENT_IMPORT_REQUESTED
    else:
        raise HTTPException(status_code=400, detail="Unsupported inbound email action.")
    session.add(event)
    record_from_context(
        session,
        context,
        action=f"inbound_email.event.{payload.action}",
        target_type="inbound_email_event",
        target_id=event.id,
        matter_id=matter.id,
        metadata={
            "raw_body_imported": False,
            "attachment_bytes_imported": False,
            "note_id": note.id if note else None,
            "task_id": task.id if task else None,
        },
    )
    session.commit()
    return InboundEmailEventReviewResponse(
        event=_event_record(event),
        note_id=note.id if note else None,
        task_id=task.id if task else None,
    )


def _default_event_note_body(event: InboundEmailEvent) -> str:
    lines = ["Linked inbound email metadata"]
    if event.subject:
        lines.append(f"Subject: {event.subject}")
    if event.from_display:
        lines.append(f"From: {event.from_display}")
    lines.append(f"Received: {event.received_at.isoformat()}")
    if event.snippet:
        lines.extend(["", event.snippet])
    return "\n".join(lines)[:4000]


def payload_to_raw_body(payload: InboundEmailWebhookRequest) -> bytes:
    return json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode("utf-8")
