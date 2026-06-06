from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Matter,
    MatterCourtOrder,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterProceedingConfidence,
    MatterProceedingReviewStatus,
    MatterProceedingSignal,
    MatterProceedingSignalType,
    MatterTask,
    MatterTaskPriority,
    MatterTaskStatus,
    utcnow,
)
from caseops_api.schemas.proceeding_intelligence import (
    ProceedingIntelligenceResponse,
    ProceedingOrderIntelligenceRecord,
    ProceedingSignalRecord,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access
from caseops_api.services.next_hearing import apply_next_hearing_update

PARSER_VERSION = "caseops-proceeding-deterministic-v1"
MIN_SOURCE_TEXT_CHARS = 24
DISCLAIMER = (
    "Proceeding intelligence is source-backed decision support for legal teams. "
    "It is not legal advice; counsel must review extracted directions before "
    "external use or client-facing communication."
)

_DATE_NUMERIC_RE = re.compile(
    r"\b(?P<day>\d{1,2})[./-](?P<month>\d{1,2})[./-](?P<year>\d{2,4})\b"
)
_DATE_TEXT_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|sept|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_NEXT_HEARING_RE = re.compile(
    r"\b(?:list|listed|renotify|renotified|re-notify|put up|post|posted|"
    r"adjourn(?:ed)?|next date|next hearing|returnable)\b.{0,80}?"
    r"(?:on|for|to|date\s*:)?\s*"
    r"(?P<date>(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})|"
    r"(?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}))",
    re.IGNORECASE,
)
_RELATIVE_DEADLINE_RE = re.compile(
    r"\bwithin\s+(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|fifteen|thirty)\s+"
    r"(?P<unit>day|days|week|weeks|month|months)\b",
    re.IGNORECASE,
)
_ORDER_DATE_RELATIVE_ANCHOR_RE = re.compile(
    r"\bfrom\s+(?:today|(?:the\s+)?date\s+of\s+(?:this\s+)?order|(?:this\s+)?order)\b",
    re.IGNORECASE,
)
_ACTION_KEYWORDS_RE = re.compile(
    r"\b(file|furnish|remove|removed|cure|cured|clear|cleared|submit|serve|"
    r"place|comply|deposit|pay|produce|supply|rectify|re-file|refile)\b",
    re.IGNORECASE,
)
_DEADLINE_CONTEXT_RE = re.compile(
    r"\b(reply|rejoinder|affidavit|counter affidavit|counter-affidavit|"
    r"compliance|defect|objection|direction|undertaking|report)\b",
    re.IGNORECASE,
)
_COUNSEL_RE = re.compile(
    r"\b(appearance|appearances|for the petitioner|for petitioner|for the respondent|"
    r"for respondent|counsel|advocate)\b",
    re.IGNORECASE,
)
_INTERIM_RE = re.compile(
    r"\b(prima facie|interim|ad-interim|till the next date|until the next date|"
    r"without prejudice|subject to)\b",
    re.IGNORECASE,
)
_ORDER_KIND_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("stay_order", re.compile(r"\bstay\b.{0,40}\b(granted|continued|modified)\b", re.I)),
    ("interim_order", re.compile(r"\b(interim|ad-interim|till the next date)\b", re.I)),
    ("final_judgment", re.compile(r"\b(disposed of|dismissed|allowed|decreed)\b", re.I)),
)
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "thirty": 30,
}
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_AUTO_TASK_SIGNAL_TYPES = {
    MatterProceedingSignalType.FILING_DEFECT,
    MatterProceedingSignalType.COMPLIANCE_DIRECTION,
    MatterProceedingSignalType.REPLY_AFFIDAVIT_DEADLINE,
    MatterProceedingSignalType.ACTION_REQUIRED,
}


@dataclass(frozen=True, slots=True)
class ExtractedProceedingSignal:
    signal_type: str
    signal_text: str
    source_snippet: str
    confidence_label: str
    action_required: str | None = None
    due_on: date | None = None
    hearing_on: date | None = None
    order_kind: str | None = None


def list_proceeding_intelligence(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> ProceedingIntelligenceResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    orders = _load_orders(session, matter.id)
    signals = _load_signals(session, matter.id)
    return _response(matter_id=matter.id, orders=orders, signals=signals)


def extract_order_proceeding_intelligence(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    order_id: str,
) -> ProceedingIntelligenceResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    order = _load_order(session, matter_id=matter.id, order_id=order_id)
    _extract_and_persist(
        session,
        matter=matter,
        order=order,
        actor_membership_id=context.membership.id,
        context=context,
    )
    session.commit()
    return list_proceeding_intelligence(session, context=context, matter_id=matter.id)


def extract_imported_order_proceeding_intelligence(
    session: Session,
    *,
    matter: Matter,
    order: MatterCourtOrder,
    actor_membership_id: str | None,
) -> None:
    _extract_and_persist(
        session,
        matter=matter,
        order=order,
        actor_membership_id=actor_membership_id,
        context=None,
    )


def extract_order_signals_from_text(
    *,
    order_text: str | None,
    order_date: date,
) -> list[ExtractedProceedingSignal]:
    text = _usable_source_text(order_text)
    if text is None:
        return []

    signals: list[ExtractedProceedingSignal] = []
    seen_keys: set[str] = set()
    for sentence in _sentences(text):
        _append_next_hearing(signals, seen_keys, sentence)
        _append_deadline_or_direction(signals, seen_keys, sentence, order_date)
        _append_counsel(signals, seen_keys, sentence)
        _append_interim_observation(signals, seen_keys, sentence)
        _append_order_kind(signals, seen_keys, sentence)
    return signals


def _load_matter(
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return matter


def _load_order(session: Session, *, matter_id: str, order_id: str) -> MatterCourtOrder:
    order = session.scalar(
        select(MatterCourtOrder).where(
            MatterCourtOrder.id == order_id,
            MatterCourtOrder.matter_id == matter_id,
        )
    )
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Court order not found.")
    return order


def _load_orders(session: Session, matter_id: str) -> list[MatterCourtOrder]:
    return list(
        session.scalars(
            select(MatterCourtOrder)
            .where(MatterCourtOrder.matter_id == matter_id)
            .order_by(MatterCourtOrder.order_date.desc(), MatterCourtOrder.created_at.desc())
        )
    )


def _load_signals(session: Session, matter_id: str) -> list[MatterProceedingSignal]:
    return list(
        session.scalars(
            select(MatterProceedingSignal)
            .where(MatterProceedingSignal.matter_id == matter_id)
            .order_by(
                MatterProceedingSignal.due_on.is_(None),
                MatterProceedingSignal.due_on.asc(),
                MatterProceedingSignal.hearing_on.is_(None),
                MatterProceedingSignal.hearing_on.asc(),
                MatterProceedingSignal.created_at.desc(),
                MatterProceedingSignal.id.asc(),
            )
        )
    )


def _extract_and_persist(
    session: Session,
    *,
    matter: Matter,
    order: MatterCourtOrder,
    actor_membership_id: str | None,
    context: SessionContext | None,
) -> list[MatterProceedingSignal]:
    source_text = _usable_source_text(order.order_text)
    if source_text is None:
        _audit(
            session,
            context=context,
            company_id=matter.company_id,
            actor_membership_id=actor_membership_id,
            action="proceeding_intelligence.extraction.skipped",
            target_type="matter_court_order",
            target_id=order.id,
            matter_id=matter.id,
            metadata={"reason": "insufficient_source_text"},
        )
        return []

    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    extracted = extract_order_signals_from_text(
        order_text=order.order_text,
        order_date=order.order_date,
    )
    existing = {
        row.dedupe_key: row
        for row in session.scalars(
            select(MatterProceedingSignal).where(
                MatterProceedingSignal.matter_id == matter.id,
                MatterProceedingSignal.court_order_id == order.id,
            )
        )
    }
    persisted: list[MatterProceedingSignal] = []
    for item in extracted:
        dedupe_key = _dedupe_key(item)
        row = existing.get(dedupe_key)
        if row is None:
            row = MatterProceedingSignal(
                company_id=matter.company_id,
                matter_id=matter.id,
                court_order_id=order.id,
                sync_run_id=order.sync_run_id,
                signal_type=item.signal_type,
                signal_text=item.signal_text,
                action_required=item.action_required,
                due_on=item.due_on,
                hearing_on=item.hearing_on,
                order_kind=item.order_kind,
                confidence_label=item.confidence_label,
                source_snippet=item.source_snippet,
                review_status=MatterProceedingReviewStatus.REVIEW_REQUIRED,
                extraction_method="deterministic",
                parser_version=PARSER_VERSION,
                source_hash=source_hash,
                dedupe_key=dedupe_key,
            )
        else:
            row.sync_run_id = order.sync_run_id
            row.signal_text = item.signal_text
            row.action_required = item.action_required
            row.due_on = item.due_on
            row.hearing_on = item.hearing_on
            row.order_kind = item.order_kind
            row.confidence_label = item.confidence_label
            row.source_snippet = item.source_snippet
            row.extraction_method = "deterministic"
            row.parser_version = PARSER_VERSION
            row.source_hash = source_hash
            row.updated_at = utcnow()
        session.add(row)
        session.flush()
        if _eligible_for_task_and_deadline(row):
            _ensure_task_and_deadline(
                session,
                matter=matter,
                order=order,
                signal=row,
                actor_membership_id=actor_membership_id,
                context=context,
            )
        persisted.append(row)

    _apply_next_hearing(
        session,
        matter=matter,
        order=order,
        signals=persisted,
        actor_membership_id=actor_membership_id,
        context=context,
    )
    _audit(
        session,
        context=context,
        company_id=matter.company_id,
        actor_membership_id=actor_membership_id,
        action="proceeding_intelligence.extracted",
        target_type="matter_court_order",
        target_id=order.id,
        matter_id=matter.id,
        metadata={
            "signal_count": len(persisted),
            "parser_version": PARSER_VERSION,
            "source_hash": source_hash,
        },
    )
    return persisted


def _eligible_for_task_and_deadline(signal: MatterProceedingSignal) -> bool:
    return (
        signal.signal_type in {item.value for item in _AUTO_TASK_SIGNAL_TYPES}
        and signal.confidence_label == MatterProceedingConfidence.HIGH
        and signal.due_on is not None
        and bool((signal.action_required or "").strip())
    )


def _ensure_task_and_deadline(
    session: Session,
    *,
    matter: Matter,
    order: MatterCourtOrder,
    signal: MatterProceedingSignal,
    actor_membership_id: str | None,
    context: SessionContext | None,
) -> None:
    title = _task_title(signal)
    description = _task_description(order, signal)
    task = session.get(MatterTask, signal.generated_task_id) if signal.generated_task_id else None
    if task is not None and task.matter_id == matter.id:
        changed = False
        if task.title != title:
            task.title = title
            changed = True
        if task.description != description:
            task.description = description
            changed = True
        if task.due_on != signal.due_on:
            task.due_on = signal.due_on
            changed = True
        if changed:
            session.add(task)
            _audit(
                session,
                context=context,
                company_id=matter.company_id,
                actor_membership_id=actor_membership_id,
                action="matter_task.proceeding_intelligence.updated",
                target_type="matter_task",
                target_id=task.id,
                matter_id=matter.id,
                metadata={"signal_id": signal.id, "court_order_id": order.id},
            )
    else:
        task = MatterTask(
            matter_id=matter.id,
            created_by_membership_id=actor_membership_id,
            title=title,
            description=description,
            due_on=signal.due_on,
            status=MatterTaskStatus.TODO,
            priority=_priority_for_due_date(signal.due_on),
        )
        session.add(task)
        session.flush()
        signal.generated_task_id = task.id
        _audit(
            session,
            context=context,
            company_id=matter.company_id,
            actor_membership_id=actor_membership_id,
            action="matter_task.proceeding_intelligence.created",
            target_type="matter_task",
            target_id=task.id,
            matter_id=matter.id,
            metadata={"signal_id": signal.id, "court_order_id": order.id},
        )

    deadline = (
        session.get(MatterDeadline, signal.generated_deadline_id)
        if signal.generated_deadline_id
        else None
    )
    if deadline is None:
        deadline = session.scalar(
            select(MatterDeadline).where(
                MatterDeadline.matter_id == matter.id,
                MatterDeadline.source_ref_type == "matter_proceeding_signal",
                MatterDeadline.source_ref_id == signal.id,
            )
        )
    if deadline is not None:
        changed = False
        if deadline.title != title:
            deadline.title = title
            changed = True
        if deadline.notes != description:
            deadline.notes = description
            changed = True
        if deadline.due_on != signal.due_on:
            deadline.due_on = signal.due_on
            changed = True
        if changed:
            session.add(deadline)
            _audit(
                session,
                context=context,
                company_id=matter.company_id,
                actor_membership_id=actor_membership_id,
                action="matter_deadline.proceeding_intelligence.updated",
                target_type="matter_deadline",
                target_id=deadline.id,
                matter_id=matter.id,
                metadata={"signal_id": signal.id, "court_order_id": order.id},
            )
    else:
        deadline = MatterDeadline(
            matter_id=matter.id,
            source="proceeding",
            kind=signal.signal_type[:64],
            title=title,
            notes=description,
            due_on=signal.due_on,
            status=MatterDeadlineStatus.OPEN,
            source_ref_type="matter_proceeding_signal",
            source_ref_id=signal.id,
            created_by_membership_id=actor_membership_id,
        )
        session.add(deadline)
        session.flush()
        _audit(
            session,
            context=context,
            company_id=matter.company_id,
            actor_membership_id=actor_membership_id,
            action="matter_deadline.proceeding_intelligence.created",
            target_type="matter_deadline",
            target_id=deadline.id,
            matter_id=matter.id,
            metadata={"signal_id": signal.id, "court_order_id": order.id},
        )
    signal.generated_deadline_id = deadline.id
    session.add(signal)


def _apply_next_hearing(
    session: Session,
    *,
    matter: Matter,
    order: MatterCourtOrder,
    signals: list[MatterProceedingSignal],
    actor_membership_id: str | None,
    context: SessionContext | None,
) -> None:
    hearing_dates = [
        signal.hearing_on
        for signal in signals
        if signal.signal_type == MatterProceedingSignalType.NEXT_HEARING
        and signal.confidence_label == MatterProceedingConfidence.HIGH
        and signal.hearing_on is not None
    ]
    if not hearing_dates:
        return
    next_hearing = min(hearing_dates)
    result = apply_next_hearing_update(
        session,
        matter=matter,
        new_date=next_hearing,
        source="proceeding_intelligence",
        actor_membership_id=actor_membership_id,
        context=context,
        source_ref_type="matter_court_order",
        source_ref_id=order.id,
        reason="high_confidence_order_signal",
        confidence_label="high",
    )
    if result.reason != "unchanged":
        _audit(
            session,
            context=context,
            company_id=matter.company_id,
            actor_membership_id=actor_membership_id,
            action=(
                "matter.next_hearing.proceeding_intelligence.updated"
                if result.applied
                else "matter.next_hearing.proceeding_intelligence.suggested"
            ),
            target_type="matter",
            target_id=matter.id,
            matter_id=matter.id,
            metadata={
                "after": next_hearing.isoformat(),
                "court_order_id": order.id,
                "suggestion_id": result.suggestion_id,
                "reason": result.reason,
            },
        )


def _response(
    *,
    matter_id: str,
    orders: list[MatterCourtOrder],
    signals: list[MatterProceedingSignal],
) -> ProceedingIntelligenceResponse:
    by_order: dict[str, list[MatterProceedingSignal]] = {}
    for signal in signals:
        by_order.setdefault(signal.court_order_id, []).append(signal)
    order_records = [
        _order_record(order, by_order.get(order.id, []))
        for order in orders
    ]
    pending = [
        _signal_record(signal)
        for signal in signals
        if signal.due_on is not None
        and signal.review_status
        in {
            MatterProceedingReviewStatus.REVIEW_REQUIRED,
            MatterProceedingReviewStatus.AUTO_PROMOTED,
        }
    ]
    return ProceedingIntelligenceResponse(
        matter_id=matter_id,
        generated_at=datetime.now(UTC),
        disclaimer=DISCLAIMER,
        orders=order_records,
        pending_compliance_items=pending,
    )


def _order_record(
    order: MatterCourtOrder,
    signals: list[MatterProceedingSignal],
) -> ProceedingOrderIntelligenceRecord:
    if signals:
        status_value = "supported"
        missing: list[str] = []
    elif _usable_source_text(order.order_text) is None:
        status_value = "insufficient_source_text"
        missing = ["raw_order_text"]
    else:
        status_value = "insufficient_evidence"
        missing = ["detectable_proceeding_directions"]
    return ProceedingOrderIntelligenceRecord(
        court_order_id=order.id,
        sync_run_id=order.sync_run_id,
        title=order.title,
        order_date=order.order_date,
        source=order.source,
        source_reference=order.source_reference,
        order_attachment_id=order.order_attachment_id,
        extraction_status=status_value,  # type: ignore[arg-type]
        missing_data=missing,
        signals=[_signal_record(signal) for signal in signals],
    )


def _signal_record(signal: MatterProceedingSignal) -> ProceedingSignalRecord:
    return ProceedingSignalRecord(
        id=signal.id,
        matter_id=signal.matter_id,
        court_order_id=signal.court_order_id,
        sync_run_id=signal.sync_run_id,
        signal_type=signal.signal_type,  # type: ignore[arg-type]
        signal_text=signal.signal_text,
        action_required=signal.action_required,
        due_on=signal.due_on,
        hearing_on=signal.hearing_on,
        order_kind=signal.order_kind,
        confidence_label=signal.confidence_label,  # type: ignore[arg-type]
        source_snippet=signal.source_snippet,
        review_status=signal.review_status,  # type: ignore[arg-type]
        generated_task_id=signal.generated_task_id,
        generated_deadline_id=signal.generated_deadline_id,
        extraction_method=signal.extraction_method,  # type: ignore[arg-type]
        parser_version=signal.parser_version,
        created_at=signal.created_at,
        updated_at=signal.updated_at,
    )


def _usable_source_text(order_text: str | None) -> str | None:
    if order_text is None:
        return None
    cleaned = _normalize_space(order_text)
    if len(cleaned) < MIN_SOURCE_TEXT_CHARS:
        return None
    return cleaned


def _sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.;:])\s+|\n+", text)
    out: list[str] = []
    for piece in pieces:
        cleaned = _normalize_space(piece)
        if len(cleaned) >= 8:
            out.append(cleaned[:800])
    return out


def _append_next_hearing(
    signals: list[ExtractedProceedingSignal],
    seen_keys: set[str],
    sentence: str,
) -> None:
    for match in _NEXT_HEARING_RE.finditer(sentence):
        parsed = _parse_date(match.group("date"))
        if parsed is None:
            continue
        _append_signal(
            signals,
            seen_keys,
            ExtractedProceedingSignal(
                signal_type=MatterProceedingSignalType.NEXT_HEARING,
                signal_text=f"Next hearing listed for {parsed.isoformat()}",
                hearing_on=parsed,
                source_snippet=_snippet(sentence),
                confidence_label=MatterProceedingConfidence.HIGH,
            ),
        )


def _append_deadline_or_direction(
    signals: list[ExtractedProceedingSignal],
    seen_keys: set[str],
    sentence: str,
    order_date: date,
) -> None:
    has_action = _ACTION_KEYWORDS_RE.search(sentence) is not None
    has_context = _DEADLINE_CONTEXT_RE.search(sentence) is not None
    if not (has_action or has_context):
        return
    due_on = _first_date(sentence) or _relative_deadline(sentence, order_date)
    signal_type = _direction_signal_type(sentence)
    confidence = (
        MatterProceedingConfidence.HIGH
        if due_on is not None and has_action
        else MatterProceedingConfidence.MEDIUM
    )
    _append_signal(
        signals,
        seen_keys,
        ExtractedProceedingSignal(
            signal_type=signal_type,
            signal_text=_direction_label(signal_type, due_on),
            action_required=sentence[:500],
            due_on=due_on,
            source_snippet=_snippet(sentence),
            confidence_label=confidence,
        ),
    )


def _append_counsel(
    signals: list[ExtractedProceedingSignal],
    seen_keys: set[str],
    sentence: str,
) -> None:
    if _COUNSEL_RE.search(sentence) is None:
        return
    _append_signal(
        signals,
        seen_keys,
        ExtractedProceedingSignal(
            signal_type=MatterProceedingSignalType.COUNSEL_APPEARANCE,
            signal_text="Counsel appearance noted",
            source_snippet=_snippet(sentence),
            confidence_label=MatterProceedingConfidence.MEDIUM,
        ),
    )


def _append_interim_observation(
    signals: list[ExtractedProceedingSignal],
    seen_keys: set[str],
    sentence: str,
) -> None:
    if _INTERIM_RE.search(sentence) is None:
        return
    _append_signal(
        signals,
        seen_keys,
        ExtractedProceedingSignal(
            signal_type=MatterProceedingSignalType.INTERIM_OBSERVATION,
            signal_text="Interim observation recorded",
            source_snippet=_snippet(sentence),
            confidence_label=MatterProceedingConfidence.MEDIUM,
        ),
    )


def _append_order_kind(
    signals: list[ExtractedProceedingSignal],
    seen_keys: set[str],
    sentence: str,
) -> None:
    for order_kind, pattern in _ORDER_KIND_RULES:
        if pattern.search(sentence) is None:
            continue
        _append_signal(
            signals,
            seen_keys,
            ExtractedProceedingSignal(
                signal_type=MatterProceedingSignalType.ORDER_KIND,
                signal_text=f"Order kind signal: {order_kind}",
                order_kind=order_kind,
                source_snippet=_snippet(sentence),
                confidence_label=MatterProceedingConfidence.MEDIUM,
            ),
        )
        return


def _append_signal(
    signals: list[ExtractedProceedingSignal],
    seen_keys: set[str],
    signal: ExtractedProceedingSignal,
) -> None:
    key = _dedupe_key(signal)
    if key in seen_keys:
        return
    seen_keys.add(key)
    signals.append(signal)


def _direction_signal_type(sentence: str) -> str:
    lower = sentence.lower()
    if "defect" in lower or "objection" in lower:
        return MatterProceedingSignalType.FILING_DEFECT
    if "reply" in lower or "affidavit" in lower or "rejoinder" in lower:
        return MatterProceedingSignalType.REPLY_AFFIDAVIT_DEADLINE
    if "comply" in lower or "compliance" in lower or "direction" in lower:
        return MatterProceedingSignalType.COMPLIANCE_DIRECTION
    return MatterProceedingSignalType.ACTION_REQUIRED


def _direction_label(signal_type: str, due_on: date | None) -> str:
    label = {
        MatterProceedingSignalType.FILING_DEFECT: "Filing defect direction",
        MatterProceedingSignalType.REPLY_AFFIDAVIT_DEADLINE: "Reply or affidavit deadline",
        MatterProceedingSignalType.COMPLIANCE_DIRECTION: "Compliance direction",
        MatterProceedingSignalType.ACTION_REQUIRED: "Action required",
    }.get(signal_type, "Proceeding direction")
    return f"{label} due {due_on.isoformat()}" if due_on else label


def _first_date(sentence: str) -> date | None:
    numeric = _DATE_NUMERIC_RE.search(sentence)
    if numeric:
        return _parse_date(numeric.group(0))
    text = _DATE_TEXT_RE.search(sentence)
    if text:
        return _parse_date(text.group(0))
    return None


def _parse_date(raw: str) -> date | None:
    value = raw.strip()
    numeric = _DATE_NUMERIC_RE.fullmatch(value)
    try:
        if numeric:
            day = int(numeric.group("day"))
            month = int(numeric.group("month"))
            year = int(numeric.group("year"))
            if year < 100:
                year += 2000
            return date(year, month, day)
        text = _DATE_TEXT_RE.fullmatch(value)
        if text:
            day = int(text.group("day"))
            month = _MONTHS[text.group("month").lower()]
            year = int(text.group("year"))
            return date(year, month, day)
    except (KeyError, ValueError):
        return None
    return None


def _relative_deadline(sentence: str, order_date: date) -> date | None:
    match = _RELATIVE_DEADLINE_RE.search(sentence)
    if match is None:
        return None
    anchor_window = sentence[match.end() : match.end() + 120]
    if _ORDER_DATE_RELATIVE_ANCHOR_RE.search(anchor_window) is None:
        return None
    count_raw = match.group("count").lower()
    count = int(count_raw) if count_raw.isdigit() else _NUMBER_WORDS.get(count_raw)
    if count is None:
        return None
    unit = match.group("unit").lower()
    if unit.startswith("day"):
        days = count
    elif unit.startswith("week"):
        days = count * 7
    else:
        days = count * 30
    return order_date + timedelta(days=days)


def _task_title(signal: MatterProceedingSignal) -> str:
    base = signal.signal_text.split(" due ", 1)[0]
    return f"Review proceeding direction: {base}"[:255]


def _task_description(order: MatterCourtOrder, signal: MatterProceedingSignal) -> str:
    due = f"\nDue: {signal.due_on.isoformat()}" if signal.due_on else ""
    return (
        "Extracted from a proceeding/order sheet. Human review is required "
        "before external use or client-facing communication."
        f"\nSource order: {order.title} ({order.order_date.isoformat()})."
        f"{due}\nSnippet: {signal.source_snippet}"
    )[:4000]


def _priority_for_due_date(due_on: date | None) -> str:
    if due_on is None:
        return MatterTaskPriority.MEDIUM
    days = (due_on - date.today()).days
    if days <= 3:
        return MatterTaskPriority.HIGH
    return MatterTaskPriority.MEDIUM


def _dedupe_key(signal: ExtractedProceedingSignal) -> str:
    raw = "|".join(
        [
            signal.signal_type,
            signal.due_on.isoformat() if signal.due_on else "",
            signal.hearing_on.isoformat() if signal.hearing_on else "",
            signal.order_kind or "",
            _normalize_space(signal.action_required or signal.source_snippet).lower()[:180],
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _snippet(sentence: str) -> str:
    return _normalize_space(sentence)[:700]


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _audit(
    session: Session,
    *,
    context: SessionContext | None,
    company_id: str,
    actor_membership_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None,
    matter_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    if context is not None:
        record_from_context(
            session,
            context,
            action=action,
            target_type=target_type,
            target_id=target_id,
            matter_id=matter_id,
            metadata=metadata,
        )
        return
    record_audit(
        session,
        company_id=company_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_membership_id=actor_membership_id,
        matter_id=matter_id,
        metadata=metadata,
    )


__all__ = [
    "DISCLAIMER",
    "PARSER_VERSION",
    "extract_imported_order_proceeding_intelligence",
    "extract_order_proceeding_intelligence",
    "extract_order_signals_from_text",
    "list_proceeding_intelligence",
]
