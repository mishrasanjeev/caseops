"""Deterministic drafting data extraction review queue for ADP-15.

The foundation intentionally avoids provider calls. It reads only existing
uploaded matter document text/chunks already present in the database, proposes
bounded drafting fields, and requires a lawyer review action before fields feed
draft generation.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    DraftingDataConfidenceBand,
    DraftingDataExtractionField,
    DraftingDataExtractionStatus,
    Matter,
    MatterAttachment,
)
from caseops_api.schemas.drafting_data import (
    DraftingDataExtractionResponse,
    DraftingDataFieldRecord,
    DraftingDataReviewRequest,
    DraftingDataStatusCounts,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext

MAX_SCAN_CHARS_PER_ATTACHMENT = 80_000
MAX_SOURCE_SNIPPET_CHARS = 280
MAX_FIELD_VALUE_CHARS = 500

SUPPORTED_FIELD_LABELS: dict[str, str] = {
    "fir_number": "FIR number",
    "case_number": "Case number",
    "police_station": "Police station",
    "complainant_name": "Complainant name",
    "accused_name": "Accused name",
    "petitioner_name": "Petitioner name",
    "respondent_name": "Respondent name",
    "incident_date": "Incident date",
    "filing_date": "Filing date",
    "notice_date": "Notice date",
    "statute_sections": "Statute / section references",
}


@dataclass(frozen=True)
class _Candidate:
    field_key: str
    label: str
    proposed_value: str
    confidence_band: str
    source_attachment_id: str | None
    source_snippet: str | None
    source_verified: bool
    source_char_start: int | None
    source_char_end: int | None


@dataclass(frozen=True)
class _PatternSpec:
    field_key: str
    pattern: re.Pattern[str]
    confidence_band: str
    value_template: str | None = None


_DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,12}\s+\d{4})"
_VALUE_STOP = r"(?=,|;|\n|\r|\.| Accused\b| Complainant\b| Petitioner\b| Respondent\b|$)"
_NAME_VALUE = r"([A-Z][A-Za-z .'-]{1,100})"
_ACT_VALUE = (
    r"(IPC|BNS|BNSS|CrPC|NI Act|Negotiable Instruments Act|"
    r"Bharatiya Nyaya Sanhita|Bharatiya Nagarik Suraksha Sanhita)\b"
)

_PATTERNS: tuple[_PatternSpec, ...] = (
    _PatternSpec(
        "fir_number",
        re.compile(
            r"\bFIR\s*(?:No\.?|Number)?\s*[:#-]?\s*"
            r"([A-Z0-9][A-Z0-9/-]{1,48})",
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "case_number",
        re.compile(
            r"\b(?:Case|Complaint Case|Criminal Case|Crl\.?\s*Case)"
            r"\s*(?:No\.?|Number)?\s*[:#-]?\s*"
            r"([A-Z0-9][A-Z0-9 ./-]{1,80})"
            + _VALUE_STOP,
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "case_number",
        re.compile(
            r"\b(?:CC|CNR|CRL\.?A\.?|WP\(C\))\s*[-:]?"
            r"\s*([A-Z0-9/-]{2,48})\b",
            re.I,
        ),
        DraftingDataConfidenceBand.LOW,
    ),
    _PatternSpec(
        "police_station",
        re.compile(
            r"\b(?:Police Station|P\.S\.|PS)\s*[:#-]?"
            r"\s*([A-Z][A-Za-z .'-]{2,80})" + _VALUE_STOP,
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "complainant_name",
        re.compile(
            r"\bComplainant(?:'s)?(?:\s+Name)?\s*[:#-]\s*"
            + _NAME_VALUE
            + _VALUE_STOP,
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "accused_name",
        re.compile(
            r"\bAccused(?:'s)?(?:\s+Name)?\s*[:#-]\s*"
            + _NAME_VALUE
            + _VALUE_STOP,
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "petitioner_name",
        re.compile(
            r"\bPetitioner(?:'s)?(?:\s+Name)?\s*[:#-]\s*"
            + _NAME_VALUE
            + _VALUE_STOP,
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "respondent_name",
        re.compile(
            r"\bRespondent(?:'s)?(?:\s+Name)?\s*[:#-]\s*"
            + _NAME_VALUE
            + _VALUE_STOP,
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "incident_date",
        re.compile(rf"\bIncident\s+Date\s*[:#-]\s*({_DATE})", re.I),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "filing_date",
        re.compile(rf"\bFiling\s+Date\s*[:#-]\s*({_DATE})", re.I),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "notice_date",
        re.compile(
            rf"\b(?:Notice\s+Date|Notice\s+sent\s+on|Notice\s+dated)"
            rf"\s*[:#-]?\s*({_DATE})",
            re.I,
        ),
        DraftingDataConfidenceBand.HIGH,
    ),
    _PatternSpec(
        "statute_sections",
        re.compile(
            r"\b(?:Section|Sections|Sec\.?|Ss\.)\s+"
            r"([0-9A-Za-z(),./\-\s]{1,90})\s+(?:of\s+(?:the\s+)?)?"
            + _ACT_VALUE,
            re.I,
        ),
        DraftingDataConfidenceBand.MEDIUM,
        value_template="Sections {0} of {1}",
    ),
)


def extract_drafting_data(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> DraftingDataExtractionResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="extract drafting data",
        lock_for_write=False,
    )
    attachments = _load_text_attachments(session, matter.id)
    candidates = _extract_candidates(attachments)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="extract drafting data",
    )
    created_count = 0
    updated_count = 0
    for candidate in candidates:
        existing = _find_existing_candidate(session, matter.id, candidate)
        if existing is None:
            session.add(
                DraftingDataExtractionField(
                    company_id=context.company.id,
                    matter_id=matter.id,
                    source_attachment_id=candidate.source_attachment_id,
                    created_by_membership_id=context.membership.id,
                    field_key=candidate.field_key,
                    label=candidate.label,
                    proposed_value=candidate.proposed_value,
                    value_hash=_value_hash(candidate.proposed_value),
                    confidence_band=candidate.confidence_band,
                    status=_initial_status(candidate),
                    source_snippet=candidate.source_snippet,
                    source_verified=candidate.source_verified,
                    source_char_start=candidate.source_char_start,
                    source_char_end=candidate.source_char_end,
                )
            )
            created_count += 1
            continue
        if existing.status in (
            DraftingDataExtractionStatus.CONFIRMED,
            DraftingDataExtractionStatus.OVERRIDDEN,
            DraftingDataExtractionStatus.REJECTED,
        ):
            continue
        existing.confidence_band = candidate.confidence_band
        existing.status = _initial_status(candidate)
        existing.source_snippet = candidate.source_snippet
        existing.source_verified = candidate.source_verified
        existing.source_char_start = candidate.source_char_start
        existing.source_char_end = candidate.source_char_end
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        updated_count += 1

    record_from_context(
        session,
        context,
        action="drafting_data.extracted",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={
            "created_count": created_count,
            "updated_count": updated_count,
            "candidate_count": len(candidates),
            "source_attachment_count": len(attachments),
            "field_keys": sorted({candidate.field_key for candidate in candidates}),
            "status_counts": _status_count_mapping(
                _list_fields(session, context.company.id, matter.id)
            ),
        },
    )
    session.commit()
    return _response(
        session,
        company_id=context.company.id,
        matter_id=matter.id,
        created_count=created_count,
        updated_count=updated_count,
        source_attachment_count=len(attachments),
    )


def list_drafting_data(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> DraftingDataExtractionResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    return _response(
        session,
        company_id=context.company.id,
        matter_id=matter.id,
    )


def review_drafting_data_field(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    field_id: str,
    payload: DraftingDataReviewRequest,
) -> DraftingDataFieldRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="review drafting data",
    )
    field = session.scalar(
        select(DraftingDataExtractionField).where(
            DraftingDataExtractionField.id == field_id,
            DraftingDataExtractionField.company_id == context.company.id,
            DraftingDataExtractionField.matter_id == matter.id,
        )
    )
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drafting data field not found.",
        )

    previous_status = field.status
    override_value_hash: str | None = None
    if payload.action == "confirm":
        field.status = DraftingDataExtractionStatus.CONFIRMED
        field.reviewed_value = field.proposed_value
    elif payload.action == "override":
        if not payload.override_value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="override_value is required for override.",
            )
        field.status = DraftingDataExtractionStatus.OVERRIDDEN
        field.reviewed_value = _clean_value(payload.override_value)
        override_value_hash = _value_hash(field.reviewed_value)
    elif payload.action == "reject":
        field.status = DraftingDataExtractionStatus.REJECTED
        field.reviewed_value = None
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported review action.",
        )

    field.reviewed_by_membership_id = context.membership.id
    field.reviewed_at = datetime.now(UTC)
    field.updated_at = field.reviewed_at
    session.add(field)
    session.flush()
    record_from_context(
        session,
        context,
        action="drafting_data.reviewed",
        target_type="drafting_data_field",
        target_id=field.id,
        matter_id=matter.id,
        metadata={
            "field_key": field.field_key,
            "previous_status": previous_status,
            "new_status": field.status,
            "confidence_band": field.confidence_band,
            "has_override": payload.action == "override",
            "override_value_hash": override_value_hash,
            "override_value_length": len(field.reviewed_value or "")
            if payload.action == "override"
            else 0,
            "proposed_value_hash": field.value_hash,
            "source_attachment_present": field.source_attachment_id is not None,
            "source_snippet_present": bool(field.source_snippet),
            "source_verified": field.source_verified,
        },
    )
    session.commit()
    session.refresh(field)
    return _record(field)


def reviewed_fields_for_prompt(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
) -> list[DraftingDataExtractionField]:
    return list(
        session.scalars(
            select(DraftingDataExtractionField)
            .where(
                DraftingDataExtractionField.company_id == company_id,
                DraftingDataExtractionField.matter_id == matter_id,
                DraftingDataExtractionField.status.in_(
                    [
                        DraftingDataExtractionStatus.CONFIRMED,
                        DraftingDataExtractionStatus.OVERRIDDEN,
                    ]
                ),
            )
            .order_by(DraftingDataExtractionField.field_key.asc())
        )
    )


def _load_matter(session: Session, *, context: SessionContext, matter_id: str) -> Matter:
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


def _load_text_attachments(session: Session, matter_id: str) -> list[MatterAttachment]:
    return list(
        session.scalars(
            select(MatterAttachment)
            .where(MatterAttachment.matter_id == matter_id)
            .options(selectinload(MatterAttachment.chunks))
            .order_by(MatterAttachment.created_at.asc())
        )
    )


def _extract_candidates(attachments: list[MatterAttachment]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    seen: set[tuple[str, str, str | None]] = set()
    for attachment in attachments:
        text = _attachment_text(attachment)
        if not text:
            continue
        scan_text = text[:MAX_SCAN_CHARS_PER_ATTACHMENT]
        for spec in _PATTERNS:
            for match in spec.pattern.finditer(scan_text):
                candidate = _candidate_from_match(attachment, scan_text, spec, match)
                if candidate is None:
                    continue
                key = (
                    candidate.field_key,
                    _value_hash(candidate.proposed_value),
                    candidate.source_attachment_id,
                )
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(candidate)
    return candidates


def _candidate_from_match(
    attachment: MatterAttachment,
    text: str,
    spec: _PatternSpec,
    match: re.Match[str],
) -> _Candidate | None:
    if spec.value_template:
        proposed = spec.value_template.format(
            *[_clean_value(group) for group in match.groups()]
        )
    else:
        proposed = _clean_value(match.group(1))
    if not proposed or len(proposed) > MAX_FIELD_VALUE_CHARS:
        return None
    snippet = _bounded_source_snippet(text, match.start(), match.end())
    source_verified = _snippet_verified(text, snippet)
    return _Candidate(
        field_key=spec.field_key,
        label=SUPPORTED_FIELD_LABELS[spec.field_key],
        proposed_value=proposed,
        confidence_band=str(spec.confidence_band),
        source_attachment_id=attachment.id,
        source_snippet=snippet if source_verified else None,
        source_verified=source_verified,
        source_char_start=match.start() if source_verified else None,
        source_char_end=match.end() if source_verified else None,
    )


def _attachment_text(attachment: MatterAttachment) -> str:
    if attachment.extracted_text and attachment.extracted_text.strip():
        return attachment.extracted_text
    chunks = [
        chunk.content
        for chunk in sorted(attachment.chunks, key=lambda row: row.chunk_index)
        if chunk.content and chunk.content.strip()
    ]
    return "\n".join(chunks)


def _bounded_source_snippet(text: str, start: int, end: int) -> str:
    span = max(0, end - start)
    budget = max(MAX_SOURCE_SNIPPET_CHARS - span, 0)
    left = max(0, start - budget // 2)
    right = min(len(text), max(end + budget // 2, left + 1))
    if right - left > MAX_SOURCE_SNIPPET_CHARS:
        right = left + MAX_SOURCE_SNIPPET_CHARS
    return " ".join(text[left:right].split())[:MAX_SOURCE_SNIPPET_CHARS]


def _snippet_verified(text: str, snippet: str | None) -> bool:
    if not snippet:
        return False
    normalized_text = " ".join(text.split()).casefold()
    return snippet.casefold() in normalized_text


def _clean_value(value: str) -> str:
    cleaned = " ".join(str(value).strip(" \t\r\n:;,.").split())
    return cleaned[:MAX_FIELD_VALUE_CHARS]


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.strip().casefold().encode("utf-8")).hexdigest()


def _initial_status(candidate: _Candidate) -> str:
    if (
        not candidate.source_verified
        or candidate.confidence_band == DraftingDataConfidenceBand.LOW
    ):
        return DraftingDataExtractionStatus.NEEDS_REVIEW
    return DraftingDataExtractionStatus.SUGGESTED


def _find_existing_candidate(
    session: Session,
    matter_id: str,
    candidate: _Candidate,
) -> DraftingDataExtractionField | None:
    return session.scalar(
        select(DraftingDataExtractionField)
        .where(
            DraftingDataExtractionField.matter_id == matter_id,
            DraftingDataExtractionField.field_key == candidate.field_key,
            DraftingDataExtractionField.value_hash
            == _value_hash(candidate.proposed_value),
            DraftingDataExtractionField.source_attachment_id
            == candidate.source_attachment_id,
        )
        .limit(1)
    )


def _list_fields(
    session: Session,
    company_id: str,
    matter_id: str,
) -> list[DraftingDataExtractionField]:
    return list(
        session.scalars(
            select(DraftingDataExtractionField)
            .where(
                DraftingDataExtractionField.company_id == company_id,
                DraftingDataExtractionField.matter_id == matter_id,
            )
            .order_by(
                DraftingDataExtractionField.status.asc(),
                DraftingDataExtractionField.field_key.asc(),
                DraftingDataExtractionField.created_at.asc(),
            )
        )
    )


def _response(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    created_count: int = 0,
    updated_count: int = 0,
    source_attachment_count: int = 0,
) -> DraftingDataExtractionResponse:
    fields = _list_fields(session, company_id, matter_id)
    return DraftingDataExtractionResponse(
        matter_id=matter_id,
        fields=[_record(field) for field in fields],
        counts=DraftingDataStatusCounts(**_status_count_mapping(fields)),
        created_count=created_count,
        updated_count=updated_count,
        source_attachment_count=source_attachment_count,
    )


def _status_count_mapping(
    fields: list[DraftingDataExtractionField],
) -> dict[str, int]:
    counts = {
        "suggested": 0,
        "needs_review": 0,
        "confirmed": 0,
        "overridden": 0,
        "rejected": 0,
    }
    for field in fields:
        if field.status in counts:
            counts[field.status] += 1
    return counts


def _record(field: DraftingDataExtractionField) -> DraftingDataFieldRecord:
    effective_value = None
    if field.status == DraftingDataExtractionStatus.CONFIRMED:
        effective_value = field.reviewed_value or field.proposed_value
    elif field.status == DraftingDataExtractionStatus.OVERRIDDEN:
        effective_value = field.reviewed_value
    return DraftingDataFieldRecord(
        id=field.id,
        matter_id=field.matter_id,
        source_attachment_id=field.source_attachment_id,
        field_key=field.field_key,
        label=field.label,
        proposed_value=field.proposed_value,
        reviewed_value=field.reviewed_value,
        effective_value=effective_value,
        confidence_band=field.confidence_band,
        status=field.status,
        source_snippet=field.source_snippet,
        source_verified=field.source_verified,
        reviewed_by_membership_id=field.reviewed_by_membership_id,
        reviewed_at=field.reviewed_at,
        created_at=field.created_at,
        updated_at=field.updated_at,
    )
