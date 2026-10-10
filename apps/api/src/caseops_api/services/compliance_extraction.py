from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    DocumentProcessingStatus,
    Matter,
    MatterAttachment,
    MatterComplianceExtractionRun,
    MatterComplianceExtractionStatus,
    MatterComplianceItem,
    MatterComplianceReviewStatus,
    MatterComplianceSourceType,
    MatterComplianceStatus,
    MatterComplianceTrigger,
    MatterCourtOrder,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterProceedingConfidence,
    MatterProceedingSignalType,
    MatterTask,
    MatterTaskPriority,
    MatterTaskStatus,
    ModelRun,
    NotificationDeliveryChannel,
    utcnow,
)
from caseops_api.schemas.compliance import (
    ComplianceExtractionRunRecord,
    ComplianceItemRecord,
)
from caseops_api.schemas.matters import MatterCourtOrderSyncItem
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.compliance_participants import (
    ComplianceParticipantFenceError,
    _notification_context,
    _recipient_memberships,
    lock_compliance_participants,
)
from caseops_api.services.compliance_tail_protocol import (
    admit_compliance_run,
    bind_compliance_run_context,
)
from caseops_api.services.llm import (
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    build_provider,
    generate_structured,
)
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
    require_operational_matter,
)
from caseops_api.services.matter_write_fence import require_read_only_upload_session
from caseops_api.services.notification_delivery import enqueue_notification_delivery_intent
from caseops_api.services.proceeding_intelligence import (
    extract_imported_order_proceeding_intelligence,
    extract_order_signals_from_text,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.tenant_ai_policy import (
    ResolvedAIPolicy,
    is_model_allowed,
    resolve_tenant_policy,
)

PARSER_VERSION = "caseops-compliance-extraction-v1"
_MAX_SOURCE_CHARS = 12000
_MIN_SOURCE_CHARS = 24
_AMBIGUOUS_TIMELINE_RE = re.compile(
    r"\b(from today|within\s+(?:two|2)\s+weeks?|next date|within\s+\d+\s+"
    r"(?:days?|weeks?|months?)(?!\s+from\s+(?:the\s+)?(?:date|order)))\b",
    re.IGNORECASE,
)


class _AIComplianceItem(BaseModel):
    description: str = Field(min_length=3, max_length=2000)
    responsible_party: str | None = Field(default=None, max_length=255)
    due_on: date | None = None
    timeline_text: str | None = Field(default=None, max_length=500)
    filing_requirement: str | None = Field(default=None, max_length=500)
    court_direction: str | None = Field(default=None, max_length=4000)
    next_action: str | None = Field(default=None, max_length=4000)
    source_snippet: str = Field(min_length=8, max_length=1200)
    source_page: int | None = Field(default=None, ge=1)
    source_paragraph: str | None = Field(default=None, max_length=120)
    confidence_label: str = Field(default="low", pattern="^(low|medium|high)$")


class _AICompliancePayload(BaseModel):
    items: list[_AIComplianceItem] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True, slots=True)
class _PreparedAICompliance:
    """Provider output held in memory until the parent lifecycle is locked."""

    payload: _AICompliancePayload | None = None
    completion: LLMCompletion | None = None
    prompt_hash: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    error_message_redacted: str | None = None
    policy: ResolvedAIPolicy | None = None
    preparation_error_redacted: str | None = None


@dataclass(frozen=True, slots=True)
class _ComplianceMatterInput:
    id: str
    company_id: str
    title: str
    lifecycle_version: int


@dataclass(frozen=True, slots=True)
class _PreparedCourtOrderCompliance:
    input_hash: str
    existing_order_id: str | None
    prior_order_index: int | None
    order_text: str | None
    ai: _PreparedAICompliance


@dataclass(frozen=True, slots=True)
class PreparedCourtSyncCompliance:
    matter: _ComplianceMatterInput
    source: str
    enabled: tuple[bool, bool]
    orders: tuple[_PreparedCourtOrderCompliance, ...]


def _now() -> datetime:
    return datetime.now(UTC)


def _source_hash(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = " ".join(text.split())
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def _dedupe_key(*parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def _run_record(run: MatterComplianceExtractionRun) -> ComplianceExtractionRunRecord:
    return ComplianceExtractionRunRecord(
        id=run.id,
        company_id=run.company_id,
        matter_id=run.matter_id,
        court_order_id=run.court_order_id,
        attachment_id=run.attachment_id,
        source_type=run.source_type,
        trigger=run.trigger,
        status=run.status,
        skip_reason=run.skip_reason,
        model_run_id=run.model_run_id,
        parser_version=run.parser_version,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_message_redacted=run.error_message_redacted,
        metadata=dict(run.metadata_json or {}),
        created_at=run.created_at,
    )


def _item_record(item: MatterComplianceItem) -> ComplianceItemRecord:
    return ComplianceItemRecord(
        id=item.id,
        company_id=item.company_id,
        matter_id=item.matter_id,
        court_order_id=item.court_order_id,
        attachment_id=item.attachment_id,
        extraction_run_id=item.extraction_run_id,
        description=item.description,
        responsible_party=item.responsible_party,
        due_on=item.due_on,
        timeline_text=item.timeline_text,
        filing_requirement=item.filing_requirement,
        court_direction=item.court_direction,
        next_action=item.next_action,
        source_snippet=item.source_snippet,
        source_page=item.source_page,
        source_paragraph=item.source_paragraph,
        confidence_label=item.confidence_label,
        status=item.status,
        review_status=item.review_status,
        generated_task_id=item.generated_task_id,
        generated_deadline_id=item.generated_deadline_id,
        dedupe_key=item.dedupe_key,
        rejection_reason=item.rejection_reason,
        waived_reason=item.waived_reason,
        completed_at=item.completed_at,
        reviewed_by_membership_id=item.reviewed_by_membership_id,
        reviewed_at=item.reviewed_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def list_compliance(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> tuple[list[ComplianceExtractionRunRecord], list[ComplianceItemRecord]]:
    matter = _load_accessible_matter(session, context=context, matter_id=matter_id)
    runs = list(
        session.scalars(
            select(MatterComplianceExtractionRun)
            .where(MatterComplianceExtractionRun.matter_id == matter.id)
            .order_by(MatterComplianceExtractionRun.created_at.desc())
            .limit(50)
        )
    )
    items = list(
        session.scalars(
            select(MatterComplianceItem)
            .where(MatterComplianceItem.matter_id == matter.id)
            .order_by(
                MatterComplianceItem.review_status.asc(),
                MatterComplianceItem.due_on.asc().nulls_last(),
                MatterComplianceItem.created_at.desc(),
            )
        )
    )
    return [_run_record(run) for run in runs], [_item_record(item) for item in items]


def _load_accessible_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _notify_review_required(
    session: Session,
    *,
    matter: Matter,
    item: MatterComplianceItem,
    actor_membership_id: str | None,
) -> None:
    try:
        matter = assert_operational_matter(
            session,
            matter=matter,
        )
    except MatterNotOperationalError:
        return
    context = _notification_context(
        session,
        matter=matter,
        actor_membership_id=actor_membership_id,
    )
    if context is None:
        return
    for recipient in _recipient_memberships(
        session,
        matter=matter,
        actor_membership_id=actor_membership_id,
    ):
        enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type="compliance_review_required",
            source_type="matter_compliance_item",
            source_id=item.id,
            matter=matter,
            title="Court order compliance review required",
            body=item.description,
            linked_court_order_id=item.court_order_id,
        )


def _notify_extraction_failure(
    session: Session,
    *,
    matter: Matter,
    run: MatterComplianceExtractionRun,
    actor_membership_id: str | None,
) -> None:
    try:
        matter = assert_operational_matter(
            session,
            matter=matter,
        )
    except MatterNotOperationalError:
        return
    context = _notification_context(
        session,
        matter=matter,
        actor_membership_id=actor_membership_id,
    )
    if context is None:
        return
    for recipient in _recipient_memberships(
        session,
        matter=matter,
        actor_membership_id=actor_membership_id,
        include_admins=True,
    ):
        enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type="compliance_extraction_failed",
            source_type="matter_compliance_extraction_run",
            source_id=run.id,
            matter=matter,
            title="Court order compliance extraction needs attention",
            body=run.error_message_redacted or run.skip_reason or "Extraction did not complete.",
            linked_court_order_id=run.court_order_id,
        )


def _create_run(
    session: Session,
    *,
    matter: Matter,
    court_order: MatterCourtOrder | None,
    attachment: MatterAttachment | None,
    source_type: str,
    trigger: str,
    actor_membership_id: str | None,
    source_text: str | None,
) -> MatterComplianceExtractionRun:
    # This is the first compliance persistence boundary. Provider work may run
    # before it, but every run/item/model/audit side effect must be serialized
    # with disposal under the authoritative parent lifecycle lock.
    matter = assert_operational_matter(session, matter=matter)
    run = MatterComplianceExtractionRun(
        company_id=matter.company_id,
        matter_id=matter.id,
        court_order_id=court_order.id if court_order else None,
        attachment_id=attachment.id if attachment else None,
        source_type=source_type,
        trigger=trigger,
        status=MatterComplianceExtractionStatus.PROCESSING,
        parser_version=PARSER_VERSION,
        source_hash=_source_hash(source_text),
        started_at=_now(),
        created_by_membership_id=actor_membership_id,
        metadata_json={
            "source_backed": True,
            "schema_validated": True,
            "review_default": "review_required",
            "auto_activation_enabled": (
                get_settings().compliance_auto_activate_generated_work_enabled
            ),
        },
    )
    admit_compliance_run(session, run)
    session.add(run)
    session.flush()
    return run


def _safe_source_text(
    *,
    order: MatterCourtOrder | None = None,
    attachment: MatterAttachment | None = None,
) -> tuple[str | None, str | None]:
    if attachment is not None:
        if attachment.processing_status in {
            DocumentProcessingStatus.PENDING,
            DocumentProcessingStatus.NEEDS_OCR,
        }:
            return None, "text_extraction_pending"
        if attachment.processing_status == DocumentProcessingStatus.FAILED:
            return None, "text_extraction_failed"
        text = attachment.extracted_text
        if text and len(" ".join(text.split())) >= _MIN_SOURCE_CHARS:
            return text[:_MAX_SOURCE_CHARS], None
        return None, "text_extraction_pending"
    if order is not None:
        return _safe_order_text(order.order_text)
    return None, "source_missing"


def _safe_order_text(text: str | None) -> tuple[str | None, str | None]:
    if text and len(" ".join(text.split())) >= _MIN_SOURCE_CHARS:
        return text[:_MAX_SOURCE_CHARS], None
    return None, "order_text_missing"


def _create_item(
    session: Session,
    *,
    run: MatterComplianceExtractionRun,
    matter: Matter,
    court_order: MatterCourtOrder | None,
    attachment: MatterAttachment | None,
    description: str,
    source_snippet: str,
    dedupe_key: str,
    responsible_party: str | None = None,
    due_on: date | None = None,
    timeline_text: str | None = None,
    filing_requirement: str | None = None,
    court_direction: str | None = None,
    next_action: str | None = None,
    source_page: int | None = None,
    source_paragraph: str | None = None,
    confidence_label: str = "low",
) -> MatterComplianceItem | None:
    matter = assert_operational_matter(session, matter=matter)
    existing_filters = [
        MatterComplianceItem.matter_id == matter.id,
        MatterComplianceItem.dedupe_key == dedupe_key,
    ]
    if court_order is not None:
        existing_filters.append(MatterComplianceItem.court_order_id == court_order.id)
    if attachment is not None:
        existing_filters.append(MatterComplianceItem.attachment_id == attachment.id)
    existing = session.scalar(select(MatterComplianceItem.id).where(*existing_filters))
    if existing is not None:
        return None
    item = MatterComplianceItem(
        company_id=matter.company_id,
        matter_id=matter.id,
        court_order_id=court_order.id if court_order else None,
        attachment_id=attachment.id if attachment else None,
        extraction_run_id=run.id,
        description=description[:4000],
        responsible_party=responsible_party,
        due_on=due_on,
        timeline_text=timeline_text,
        filing_requirement=filing_requirement,
        court_direction=court_direction,
        next_action=next_action,
        source_snippet=source_snippet[:4000],
        source_page=source_page,
        source_paragraph=source_paragraph,
        confidence_label=confidence_label,
        status=MatterComplianceStatus.PENDING,
        review_status=MatterComplianceReviewStatus.REVIEW_REQUIRED,
        dedupe_key=dedupe_key,
        source_hash=run.source_hash,
    )
    session.add(item)
    session.flush()
    if get_settings().compliance_auto_activate_generated_work_enabled:
        _activate_item(session, matter=matter, item=item, actor_membership_id=None)
    _notify_review_required(
        session,
        matter=matter,
        item=item,
        actor_membership_id=run.created_by_membership_id,
    )
    return item


def _deterministic_items(
    session: Session,
    *,
    run: MatterComplianceExtractionRun,
    matter: Matter,
    court_order: MatterCourtOrder | None,
    attachment: MatterAttachment | None,
    source_text: str,
    order_date: date,
) -> list[MatterComplianceItem]:
    created: list[MatterComplianceItem] = []
    for signal in extract_order_signals_from_text(
        order_text=source_text,
        order_date=order_date,
    ):
        if signal.signal_type not in {
            MatterProceedingSignalType.FILING_DEFECT,
            MatterProceedingSignalType.REPLY_AFFIDAVIT_DEADLINE,
            MatterProceedingSignalType.COMPLIANCE_DIRECTION,
            MatterProceedingSignalType.ACTION_REQUIRED,
        }:
            continue
        ambiguous_timeline = bool(
            _AMBIGUOUS_TIMELINE_RE.search(signal.signal_text)
            or _AMBIGUOUS_TIMELINE_RE.search(signal.source_snippet)
        )
        item = _create_item(
            session,
            run=run,
            matter=matter,
            court_order=court_order,
            attachment=attachment,
            description=signal.signal_text,
            responsible_party="Not available",
            due_on=None if ambiguous_timeline else signal.due_on,
            timeline_text=signal.signal_text if signal.due_on or ambiguous_timeline else None,
            filing_requirement=(
                signal.action_required
                if signal.signal_type
                in {
                    MatterProceedingSignalType.FILING_DEFECT,
                    MatterProceedingSignalType.REPLY_AFFIDAVIT_DEADLINE,
                }
                else None
            ),
            court_direction=signal.action_required,
            next_action=signal.action_required,
            source_snippet=signal.source_snippet,
            confidence_label=(
                MatterProceedingConfidence.LOW
                if ambiguous_timeline
                else signal.confidence_label
            ),
            dedupe_key=_dedupe_key("deterministic", signal.signal_type, signal.signal_text),
        )
        if item is not None:
            created.append(item)
    for match in _AMBIGUOUS_TIMELINE_RE.finditer(source_text):
        start = max(0, match.start() - 180)
        end = min(len(source_text), match.end() + 180)
        snippet = " ".join(source_text[start:end].split())
        item = _create_item(
            session,
            run=run,
            matter=matter,
            court_order=court_order,
            attachment=attachment,
            description="Ambiguous compliance timeline requires legal review",
            responsible_party="Not available",
            due_on=None,
            timeline_text=match.group(0),
            court_direction=snippet,
            next_action="Review ambiguous timeline before creating any deadline.",
            source_snippet=snippet,
            confidence_label=MatterProceedingConfidence.LOW,
            dedupe_key=_dedupe_key("ambiguous", match.group(0), snippet),
        )
        if item is not None:
            created.append(item)
    return created


def _prepare_ai_items(
    session: Session,
    *,
    matter: Matter | _ComplianceMatterInput,
    source_text: str,
    provider: LLMProvider | None,
    detached: bool = False,
) -> _PreparedAICompliance:
    """Complete provider-bound analysis without creating operational children."""

    settings = get_settings()
    if not (
        settings.compliance_ai_extraction_enabled
        and settings.compliance_ai_extraction_auto_run_enabled
    ):
        return _PreparedAICompliance()
    llm = provider or build_provider(purpose="metadata_extract")
    policy = resolve_tenant_policy(session, company_id=matter.company_id)
    if not is_model_allowed(policy, purpose="metadata_extract", model=llm.model):
        return _PreparedAICompliance(
            metadata={"ai_skipped": "tenant_ai_policy_blocked_model"},
            policy=policy if detached else None,
        )
    messages = [
        LLMMessage(
            role="system",
            content=(
                "Extract source-backed court-order compliance items for lawyer review. "
                "Return only facts grounded in the supplied text. Do not invent due dates."
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                "Return JSON {items:[{description,responsible_party,due_on,"
                "timeline_text,filing_requirement,court_direction,next_action,"
                "source_snippet,source_page,source_paragraph,confidence_label}]}."
                " Use null due_on when the date is ambiguous or missing.\n"
                f"MATTER: {matter.title}\nTEXT:\n{source_text[:6000]}"
            ),
        ),
    ]
    prompt_hash = hashlib.sha256(
        "\n".join(f"{message.role}:{message.content}" for message in messages).encode("utf-8")
    ).hexdigest()
    if detached:
        require_read_only_upload_session(
            session, detail="Court compliance preparation cannot release caller-owned writes."
        )
    try:
        payload, completion = generate_structured(
            llm,
            session=session,
            schema=_AICompliancePayload,
            messages=messages,
            context=LLMCallContext(purpose="metadata_extract"),
            temperature=settings.llm_temperature,
            max_tokens=min(settings.llm_max_output_tokens, 1600),
            release_session_before_provider=detached,
        )
    except LLMProviderError as exc:
        return _PreparedAICompliance(
            metadata={"ai_failed": True},
            error_message_redacted=redact_provider_error(exc),
            policy=policy if detached else None,
        )
    return _PreparedAICompliance(
        payload=payload,
        completion=completion,
        prompt_hash=prompt_hash,
        metadata={"ai_item_count": len(payload.items)},
        policy=policy if detached else None,
    )


def _court_order_input_hash(order: MatterCourtOrderSyncItem) -> str:
    return hashlib.sha256(order.model_dump_json().encode("utf-8")).hexdigest()


def prepare_court_sync_compliance(
    session: Session, *, matter: Matter, orders: list[MatterCourtOrderSyncItem],
    source: str, order_sources: list[tuple[str | None, int | None, str | None]],
) -> PreparedCourtSyncCompliance:
    """Court callers enter before any import write or authority lock, never mid-import."""
    require_read_only_upload_session(
        session, detail="Court compliance preparation cannot release caller-owned writes."
    )
    snapshot = _ComplianceMatterInput(
        matter.id, matter.company_id, matter.title, matter.lifecycle_version,
    )
    settings = get_settings()
    enabled = (
        settings.compliance_ai_extraction_enabled,
        settings.compliance_ai_extraction_auto_run_enabled,
    )
    # Capture all inputs before rollback expires ORM reads or a callback changes a payload.
    inputs = tuple(
        (_court_order_input_hash(order), existing_id, prior_index, order_text)
        for order, (existing_id, prior_index, order_text) in zip(orders, order_sources, strict=True)
    )
    prepared = []
    for input_hash, existing_id, prior_index, order_text in inputs:
        source_text, _skip_reason = _safe_order_text(order_text)
        ai = _PreparedAICompliance()
        if source_text is not None:
            try:
                ai = _prepare_ai_items(
                    session, matter=snapshot, source_text=source_text,
                    provider=None, detached=True,
                )
            except LLMProviderError as exc:
                # Keep configuration failure on the existing failed-extraction path.
                ai = _PreparedAICompliance(preparation_error_redacted=redact_provider_error(exc))
        prepared.append(_PreparedCourtOrderCompliance(
            input_hash, existing_id, prior_index, order_text, ai,
        ))
    require_read_only_upload_session(
        session, detail="Court compliance preparation cannot release caller-owned writes."
    )
    session.rollback()
    return PreparedCourtSyncCompliance(snapshot, source, enabled, tuple(prepared))


def validate_court_sync_compliance(
    session: Session, *, matter: Matter, orders: list[MatterCourtOrderSyncItem],
    source: str, prepared: PreparedCourtSyncCompliance,
) -> None:
    """Reject stale prepared input under the caller's fresh Company/parent fence."""
    snapshot = _ComplianceMatterInput(
        matter.id, matter.company_id, matter.title, matter.lifecycle_version,
    )
    settings = get_settings()
    if snapshot != prepared.matter or source != prepared.source or prepared.enabled != (
        settings.compliance_ai_extraction_enabled,
        settings.compliance_ai_extraction_auto_run_enabled,
    ) or tuple(_court_order_input_hash(order) for order in orders) != tuple(
        order.input_hash for order in prepared.orders
    ):
        raise ComplianceParticipantFenceError(409, detail={"code": "compliance_source_changed"})
    policies = [order.ai.policy for order in prepared.orders if order.ai.policy is not None]
    if policies:
        current_policy = resolve_tenant_policy(session, company_id=matter.company_id)
        if any(policy != current_policy for policy in policies):
            raise ComplianceParticipantFenceError(409, detail={"code": "compliance_policy_changed"})


def _persist_ai_items(
    session: Session,
    *,
    run: MatterComplianceExtractionRun,
    matter: Matter,
    court_order: MatterCourtOrder | None,
    attachment: MatterAttachment | None,
    prepared: _PreparedAICompliance,
) -> list[MatterComplianceItem]:
    """Persist prepared provider output under the authoritative parent lock."""

    matter = assert_operational_matter(session, matter=matter)
    run.metadata_json = {
        **dict(run.metadata_json or {}),
        **prepared.metadata,
    }
    if prepared.error_message_redacted is not None:
        run.error_message_redacted = prepared.error_message_redacted
    payload = prepared.payload
    completion = prepared.completion
    prompt_hash = prepared.prompt_hash
    if payload is None or completion is None or prompt_hash is None:
        return []
    model_run = ModelRun(
        company_id=matter.company_id,
        matter_id=matter.id,
        actor_membership_id=run.created_by_membership_id,
        purpose="compliance_extraction",
        provider=completion.provider,
        model=completion.model,
        prompt_hash=prompt_hash,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        status="ok",
    )
    session.add(model_run)
    session.flush()
    run.model_run_id = model_run.id
    created: list[MatterComplianceItem] = []
    for payload_item in payload.items:
        item = _create_item(
            session,
            run=run,
            matter=matter,
            court_order=court_order,
            attachment=attachment,
            description=payload_item.description,
            responsible_party=payload_item.responsible_party,
            due_on=payload_item.due_on,
            timeline_text=payload_item.timeline_text,
            filing_requirement=payload_item.filing_requirement,
            court_direction=payload_item.court_direction,
            next_action=payload_item.next_action,
            source_snippet=payload_item.source_snippet,
            source_page=payload_item.source_page,
            source_paragraph=payload_item.source_paragraph,
            confidence_label=payload_item.confidence_label,
            dedupe_key=_dedupe_key(
                "ai",
                payload_item.description,
                payload_item.due_on,
                payload_item.source_snippet,
            ),
        )
        if item is not None:
            created.append(item)
    return created


def _finish_run(
    session: Session,
    *,
    run: MatterComplianceExtractionRun,
    matter: Matter,
    created_count: int,
    status_value: str,
    skip_reason: str | None = None,
    error: object | None = None,
) -> None:
    bind_compliance_run_context(session, run)
    run.status = status_value
    run.skip_reason = skip_reason
    run.completed_at = _now()
    if error is not None:
        run.error_message_redacted = redact_provider_error(error)
    run.metadata_json = {
        **dict(run.metadata_json or {}),
        "created_item_count": created_count,
    }
    session.add(run)
    metadata = {
        "status": run.status,
        "skip_reason": skip_reason,
        "created_item_count": created_count,
        "source_type": run.source_type,
        "trigger": run.trigger,
    }
    audit_context = _notification_context(
        session,
        matter=matter,
        actor_membership_id=run.created_by_membership_id,
    )
    if audit_context is not None:
        record_from_context(
            session,
            audit_context,
            action="matter_compliance.extraction.completed",
            target_type="matter_compliance_extraction_run",
            target_id=run.id,
            matter_id=matter.id,
            metadata=metadata,
        )
    else:
        record_audit(
            session,
            company_id=matter.company_id,
            action="matter_compliance.extraction.completed",
            target_type="matter_compliance_extraction_run",
            target_id=run.id,
            actor_membership_id=run.created_by_membership_id,
            matter_id=matter.id,
            metadata=metadata,
        )


def run_compliance_extraction_for_order(
    session: Session,
    *,
    matter: Matter,
    order: MatterCourtOrder,
    trigger: str = MatterComplianceTrigger.MANUAL_ORDER_CREATE,
    actor_membership_id: str | None = None,
    context: SessionContext | None = None,
    provider: LLMProvider | None = None,
    required_capability: str = "matters:edit",
    prepared_ai: _PreparedAICompliance | None = None,
) -> tuple[MatterComplianceExtractionRun, list[MatterComplianceItem]]:
    if trigger == "court_sync" and prepared_ai is None:
        raise RuntimeError("Court compliance must be prepared before import persistence.")
    previous = session.info.get("compliance_participants", {}).get(
        (matter.company_id, matter.id, actor_membership_id),
    )
    standalone = previous is None or previous.transaction is not session.get_transaction()
    source_identity = (order.order_date, order.order_text, order.source, order.sync_run_id)
    lock_compliance_participants(
        session,
        company_id=matter.company_id,
        matter_id=matter.id,
        actor_membership_id=actor_membership_id,
        context=context,
        required_capability=required_capability if context else None,
        expected_lifecycle_version=matter.lifecycle_version,
    )
    assert_operational_matter(session, matter=matter, lock_for_write=False)
    if standalone:
        with session.no_autoflush:
            session.refresh(order)
        if (order.order_date, order.order_text, order.source, order.sync_run_id) != source_identity:
            raise ComplianceParticipantFenceError(409, detail={"code": "compliance_source_changed"})
    try:
        extract_imported_order_proceeding_intelligence(
            session,
            matter=matter,
            order=order,
            actor_membership_id=actor_membership_id,
        )
    except MatterNotOperationalError:
        raise
    except ComplianceParticipantFenceError:
        raise
    except Exception as exc:  # noqa: BLE001
        safe_error = redact_provider_error(exc)
    else:
        safe_error = None
    source_text, skip_reason = _safe_source_text(order=order)
    run = _create_run(
        session,
        matter=matter,
        court_order=order,
        attachment=None,
        source_type=(
            MatterComplianceSourceType.AUTO_FETCHED_ORDER
            if order.sync_run_id
            else MatterComplianceSourceType.MANUAL_ORDER
        ),
        trigger=trigger,
        actor_membership_id=actor_membership_id,
        source_text=source_text,
    )
    if safe_error:
        run.metadata_json = {
            **dict(run.metadata_json or {}),
            "proceeding_extraction_error": safe_error,
        }
    if source_text is None:
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=0,
            status_value=MatterComplianceExtractionStatus.SKIPPED,
            skip_reason=skip_reason,
        )
        _notify_extraction_failure(
            session,
            matter=matter,
            run=run,
            actor_membership_id=actor_membership_id,
        )
        return run, []
    try:
        if prepared_ai is not None and prepared_ai.preparation_error_redacted is not None:
            raise LLMProviderError(prepared_ai.preparation_error_redacted)
        prepared_ai = prepared_ai if prepared_ai is not None else _prepare_ai_items(
            session,
            matter=matter,
            source_text=source_text,
            provider=provider,
        )
        created = _deterministic_items(
            session,
            run=run,
            matter=matter,
            court_order=order,
            attachment=None,
            source_text=source_text,
            order_date=order.order_date,
        )
        created.extend(
            _persist_ai_items(
                session,
                run=run,
                matter=matter,
                court_order=order,
                attachment=None,
                prepared=prepared_ai,
            )
        )
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=len(created),
            status_value=MatterComplianceExtractionStatus.COMPLETED,
        )
        return run, created
    except ComplianceParticipantFenceError:
        raise
    except MatterNotOperationalError:
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=0,
            status_value=MatterComplianceExtractionStatus.SKIPPED,
            skip_reason="matter_disposed",
        )
        return run, []
    except Exception as exc:  # noqa: BLE001
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=0,
            status_value=MatterComplianceExtractionStatus.FAILED,
            error=exc,
        )
        _notify_extraction_failure(
            session,
            matter=matter,
            run=run,
            actor_membership_id=actor_membership_id,
        )
        return run, []


def _attachment_source_identity(attachment: MatterAttachment) -> tuple[object, ...]:
    linked = attachment.linked_court_order
    return (
        attachment.document_type,
        attachment.processing_status,
        attachment.extracted_text,
        attachment.linked_court_order_id,
        attachment.document_date,
        attachment.sha256_hex,
        (linked.order_date, linked.order_text, linked.source, linked.sync_run_id)
        if linked else None,
    )


def _refresh_standalone_attachment_source(
    session: Session,
    *,
    attachment: MatterAttachment,
    standalone: bool,
    source_identity: tuple[object, ...],
) -> None:
    if not standalone:
        return
    with session.no_autoflush:
        session.refresh(attachment)
        if attachment.linked_court_order is not None:
            session.refresh(attachment.linked_court_order)
    if _attachment_source_identity(attachment) != source_identity:
        raise ComplianceParticipantFenceError(409, detail={"code": "compliance_source_changed"})


def run_compliance_extraction_for_attachment(
    session: Session,
    *,
    matter: Matter,
    attachment: MatterAttachment,
    trigger: str = MatterComplianceTrigger.ATTACHMENT_PROCESSED,
    actor_membership_id: str | None = None,
    context: SessionContext | None = None,
    provider: LLMProvider | None = None,
) -> tuple[MatterComplianceExtractionRun, list[MatterComplianceItem]]:
    assert_operational_matter(session, matter=matter, lock_for_write=False)
    lifecycle_version = matter.lifecycle_version
    source_identity = _attachment_source_identity(attachment)
    previous = session.info.get("compliance_participants", {}).get(
        (matter.company_id, matter.id, actor_membership_id),
    )
    standalone = previous is None or previous.transaction is not session.get_transaction()
    source_text, skip_reason = _safe_source_text(attachment=attachment)
    linked_order = attachment.linked_court_order
    if source_text is None:
        lock_compliance_participants(
            session,
            company_id=matter.company_id,
            matter_id=matter.id,
            actor_membership_id=actor_membership_id,
            context=context,
            required_capability="documents:manage" if context else None,
            expected_lifecycle_version=lifecycle_version,
        )
        _refresh_standalone_attachment_source(
            session,
            attachment=attachment,
            standalone=standalone,
            source_identity=source_identity,
        )
        run = _create_run(
            session,
            matter=matter,
            court_order=linked_order,
            attachment=attachment,
            source_type=MatterComplianceSourceType.MANUAL_UPLOAD,
            trigger=trigger,
            actor_membership_id=actor_membership_id,
            source_text=source_text,
        )
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=0,
            status_value=(
                MatterComplianceExtractionStatus.FAILED
                if skip_reason == "text_extraction_failed"
                else MatterComplianceExtractionStatus.SKIPPED
            ),
            skip_reason=skip_reason,
        )
        if skip_reason == "text_extraction_failed":
            _notify_extraction_failure(
                session,
                matter=matter,
                run=run,
                actor_membership_id=actor_membership_id,
            )
        return run, []
    order_date = (
        linked_order.order_date
        if linked_order is not None
        else attachment.document_date or utcnow().date()
    )
    # Standalone workers prepare before the persistence fence. Nested callers
    # already own their transaction; this must not commit or roll back it.
    prepared_ai = _prepare_ai_items(
        session,
        matter=matter,
        source_text=source_text,
        provider=provider,
    )
    lock_compliance_participants(
        session,
        company_id=matter.company_id,
        matter_id=matter.id,
        actor_membership_id=actor_membership_id,
        context=context,
        required_capability="documents:manage" if context else None,
        expected_lifecycle_version=lifecycle_version,
    )
    assert_operational_matter(session, matter=matter, lock_for_write=False)
    _refresh_standalone_attachment_source(
        session,
        attachment=attachment,
        standalone=standalone,
        source_identity=source_identity,
    )
    run = _create_run(
        session,
        matter=matter,
        court_order=linked_order,
        attachment=attachment,
        source_type=MatterComplianceSourceType.MANUAL_UPLOAD,
        trigger=trigger,
        actor_membership_id=actor_membership_id,
        source_text=source_text,
    )
    try:
        created = _deterministic_items(
            session,
            run=run,
            matter=matter,
            court_order=linked_order,
            attachment=attachment,
            source_text=source_text,
            order_date=order_date,
        )
        created.extend(
            _persist_ai_items(
                session,
                run=run,
                matter=matter,
                court_order=linked_order,
                attachment=attachment,
                prepared=prepared_ai,
            )
        )
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=len(created),
            status_value=MatterComplianceExtractionStatus.COMPLETED,
        )
        return run, created
    except ComplianceParticipantFenceError:
        raise
    except MatterNotOperationalError:
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=0,
            status_value=MatterComplianceExtractionStatus.SKIPPED,
            skip_reason="matter_disposed",
        )
        return run, []
    except Exception as exc:  # noqa: BLE001
        _finish_run(
            session,
            run=run,
            matter=matter,
            created_count=0,
            status_value=MatterComplianceExtractionStatus.FAILED,
            error=exc,
        )
        _notify_extraction_failure(
            session,
            matter=matter,
            run=run,
            actor_membership_id=actor_membership_id,
        )
        return run, []


def _priority_for_item(item: MatterComplianceItem) -> str:
    if item.due_on is None:
        return MatterTaskPriority.MEDIUM
    days = (item.due_on - date.today()).days
    return MatterTaskPriority.HIGH if days <= 3 else MatterTaskPriority.MEDIUM


def _activate_item(
    session: Session,
    *,
    matter: Matter,
    item: MatterComplianceItem,
    actor_membership_id: str | None,
) -> None:
    matter = assert_operational_matter(session, matter=matter)
    if item.generated_task_id is None:
        task = MatterTask(
            company_id=matter.company_id,
            matter_id=matter.id,
            created_by_membership_id=actor_membership_id,
            owner_membership_id=matter.assignee_membership_id,
            title=(item.next_action or item.description)[:255],
            description=(
                "Source-backed compliance item confirmed for action.\n"
                f"Snippet: {item.source_snippet}"
            )[:4000],
            due_on=item.due_on,
            status=MatterTaskStatus.TODO,
            priority=_priority_for_item(item),
        )
        session.add(task)
        session.flush()
        item.generated_task_id = task.id
    if item.due_on is not None and item.generated_deadline_id is None:
        deadline = MatterDeadline(
            company_id=matter.company_id,
            matter_id=matter.id,
            source="compliance",
            kind="court_order_compliance",
            title=item.description[:255],
            notes=item.source_snippet[:4000],
            due_on=item.due_on,
            status=MatterDeadlineStatus.OPEN,
            assignee_membership_id=matter.assignee_membership_id,
            source_ref_type="matter_compliance_item",
            source_ref_id=item.id,
            created_by_membership_id=actor_membership_id,
        )
        session.add(deadline)
        session.flush()
        item.generated_deadline_id = deadline.id
    session.add(item)


def update_compliance_item(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    item_id: str,
    action: str,
    updates: dict[str, object | None] | None = None,
) -> MatterComplianceItem:
    lock_compliance_participants(
        session,
        company_id=context.company.id,
        matter_id=matter_id,
        actor_membership_id=context.membership.id,
        context=context,
        required_capability="matters:write",
    )
    matter = _load_accessible_matter(session, context=context, matter_id=matter_id)
    item = session.scalar(
        select(MatterComplianceItem).where(
            MatterComplianceItem.id == item_id,
            MatterComplianceItem.matter_id == matter.id,
            MatterComplianceItem.company_id == context.company.id,
        )
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Compliance item not found.",
        )
    changed = updates or {}
    for field_name in [
        "description",
        "responsible_party",
        "due_on",
        "timeline_text",
        "filing_requirement",
        "court_direction",
        "next_action",
    ]:
        if field_name in changed and changed[field_name] is not None:
            setattr(item, field_name, changed[field_name])
    item.reviewed_by_membership_id = context.membership.id
    item.reviewed_at = _now()
    if action == "confirm":
        matter = require_operational_matter(
            session,
            matter=matter,
            operation="confirm compliance work",
        )
        item.review_status = (
            MatterComplianceReviewStatus.EDITED
            if changed
            else MatterComplianceReviewStatus.CONFIRMED
        )
        item.status = MatterComplianceStatus.PENDING
        _activate_item(
            session,
            matter=matter,
            item=item,
            actor_membership_id=context.membership.id,
        )
    elif action == "reject":
        item.review_status = MatterComplianceReviewStatus.REJECTED
        item.status = MatterComplianceStatus.NOT_APPLICABLE
        item.rejection_reason = str(changed.get("reason") or "Rejected by reviewer.")[:4000]
    elif action == "waive":
        item.review_status = MatterComplianceReviewStatus.CONFIRMED
        item.status = MatterComplianceStatus.WAIVED
        item.waived_reason = str(changed.get("reason") or "Waived by reviewer.")[:4000]
    elif action == "complete":
        item.review_status = MatterComplianceReviewStatus.CONFIRMED
        item.status = MatterComplianceStatus.COMPLETED
        item.completed_at = _now()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported compliance action.",
        )
    session.add(item)
    record_from_context(
        session,
        context,
        action=f"matter_compliance.item.{action}",
        target_type="matter_compliance_item",
        target_id=item.id,
        matter_id=matter.id,
        metadata={
            "review_status": item.review_status,
            "status": item.status,
            "generated_task_id": item.generated_task_id,
            "generated_deadline_id": item.generated_deadline_id,
        },
    )
    session.commit()
    session.refresh(item)
    return item


def retry_order_compliance_extraction(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    order_id: str,
) -> tuple[MatterComplianceExtractionRun, list[MatterComplianceItem]]:
    lock_compliance_participants(
        session,
        company_id=context.company.id,
        matter_id=matter_id,
        actor_membership_id=context.membership.id,
        context=context,
        required_capability="matters:write",
    )
    matter = _load_accessible_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="retry compliance extraction",
        lock_for_write=False,
    )
    order = session.scalar(
        select(MatterCourtOrder).where(
            MatterCourtOrder.id == order_id,
            MatterCourtOrder.matter_id == matter.id,
        )
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Court order not found.",
        )
    run, items = run_compliance_extraction_for_order(
        session,
        matter=matter,
        order=order,
        trigger=MatterComplianceTrigger.MANUAL_RETRY,
        actor_membership_id=context.membership.id,
        context=context,
        required_capability="matters:write",
    )
    session.commit()
    return run, items


__all__ = [
    "_item_record",
    "_run_record",
    "list_compliance",
    "retry_order_compliance_extraction",
    "run_compliance_extraction_for_attachment",
    "run_compliance_extraction_for_order",
    "update_compliance_item",
]
