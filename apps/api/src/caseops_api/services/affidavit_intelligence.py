from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AffidavitIntelligenceReviewStatus,
    AffidavitIntelligenceRun,
    AffidavitIntelligenceRunStatus,
    AffidavitQuestion,
    AffidavitQuestionCategory,
    AffidavitStatement,
    AffidavitStatementType,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    MatterProceedingConfidence,
)
from caseops_api.schemas.affidavit_intelligence import (
    AffidavitIntelligenceResponse,
    AffidavitIntelligenceRunRecord,
    AffidavitQuestionRecord,
    AffidavitStatementRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext

PARSER_VERSION = "caseops-affidavit-deterministic-v1"
MIN_SOURCE_TEXT_CHARS = 80
DISCLAIMER = (
    "Affidavit intelligence is source-backed hearing-preparation decision support. "
    "It is not legal advice; counsel must review extracted statements, gaps, "
    "and questions before external use or client-facing preparation."
)

_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"\b(?:Rs\.?|INR)\s*[\d,]+(?:\.\d+)?\b|"
    r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|"
    r"\b[\d,]+(?:\.\d+)?\s*(?:lakh|lakhs|crore|crores)\b",
    re.IGNORECASE,
)
_EXHIBIT_RE = re.compile(
    r"\b(?:annexure|annexed|exhibit|marked|invoice|receipt|agreement|ledger|"
    r"statement of account|purchase order|document)\b",
    re.IGNORECASE,
)
_FACT_RE = re.compile(
    r"\b(?:i state|i submit|deponent states|petitioner|respondent|paid|received|"
    r"delivered|defaulted|entered into|executed|served|refused|issued|acknowledged)\b",
    re.IGNORECASE,
)
_SUPPORT_REQUIRED_RE = re.compile(
    r"\b(?:paid|payment|received|delivered|served|loan|invoice|agreement|transfer|"
    r"default|notice|receipt|cash|cheque|bank|goods|services)\b",
    re.IGNORECASE,
)
_INTENT_RE = re.compile(
    r"\b(?:intent|intention|motive|deliberate|fraud|fraudulent|malafide|wilful)\b",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"\b(?:not paid|never paid|no payment|not received)\b", re.IGNORECASE)
_PAYMENT_RE = re.compile(r"\b(?:paid|payment|received)\b", re.IGNORECASE)
_ENTITY_RE = re.compile(
    r"\b(?:M/s\.?\s+)?[A-Z][A-Za-z&.,'-]+(?:\s+[A-Z][A-Za-z&.,'-]+){1,4}\b"
)
_PAGE_RE = re.compile(r"\bpage\s+(\d{1,4})\b", re.IGNORECASE)


@dataclass(frozen=True)
class SourceSentence:
    text: str
    chunk_id: str | None
    chunk_index: int | None
    page_reference: str | None


@dataclass(frozen=True)
class ExtractedStatement:
    statement_type: str
    statement_text: str
    source_quote: str
    confidence_label: str
    chunk_id: str | None
    chunk_index: int | None
    page_reference: str | None
    dedupe_key: str


@dataclass(frozen=True)
class ExtractedQuestion:
    category: str
    question_text: str
    reason: str
    source_quote: str
    confidence_label: str
    review_required: bool
    statement_key: str | None
    chunk_id: str | None
    chunk_index: int | None
    page_reference: str | None
    dedupe_key: str


def list_affidavit_intelligence(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> AffidavitIntelligenceResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    runs = _load_runs(session, matter.id)
    record_from_context(
        session,
        context,
        action="affidavit_intelligence.viewed",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={"run_count": len(runs)},
    )
    session.commit()
    return _response(matter_id=matter.id, runs=runs)


def analyze_affidavit_attachment(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    attachment_id: str,
) -> AffidavitIntelligenceResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="analyze an affidavit attachment",
        lock_for_write=False,
    )
    attachment = _load_attachment(session, matter_id=matter.id, attachment_id=attachment_id)
    chunks = _load_chunks(session, attachment.id)
    usable = _usable_source_chunks(chunks)

    if not usable:
        matter = require_operational_matter(
            session,
            matter=matter,
            operation="analyze an affidavit attachment",
        )
        run = _create_run(
            session,
            matter=matter,
            attachment=attachment,
            context=context,
            status_value=AffidavitIntelligenceRunStatus.INSUFFICIENT_SOURCE_TEXT,
            source_hash=hashlib.sha256(b"").hexdigest(),
            source_char_count=0,
            missing_data=["raw_attachment_text_chunks"],
        )
        _audit_analyzed(
            session,
            context=context,
            matter=matter,
            run=run,
            statement_count=0,
            question_count=0,
        )
        session.commit()
        return _response(matter_id=matter.id, runs=_load_runs(session, matter.id))

    source_text = " ".join(chunk.content for chunk in usable)
    source_hash = hashlib.sha256(_normalize_space(source_text).encode("utf-8")).hexdigest()
    sentences = _source_sentences(usable)
    statements = _extract_statements(sentences)
    questions = _questions_for_statements(statements)
    status_value = (
        AffidavitIntelligenceRunStatus.COMPLETED
        if statements or questions
        else AffidavitIntelligenceRunStatus.NO_FINDINGS
    )

    matter = require_operational_matter(
        session,
        matter=matter,
        operation="analyze an affidavit attachment",
    )
    run = _create_run(
        session,
        matter=matter,
        attachment=attachment,
        context=context,
        status_value=status_value,
        source_hash=source_hash,
        source_char_count=len(_normalize_space(source_text)),
        missing_data=[] if statements or questions else ["detectable_affidavit_statements"],
    )
    statement_rows = _persist_statements(
        session,
        run=run,
        matter=matter,
        attachment=attachment,
        statements=statements,
    )
    _persist_questions(
        session,
        run=run,
        matter=matter,
        attachment=attachment,
        questions=questions,
        statements_by_key={statement.dedupe_key: row for statement, row in statement_rows},
    )
    _audit_analyzed(
        session,
        context=context,
        matter=matter,
        run=run,
        statement_count=len(statements),
        question_count=len(questions),
    )
    session.commit()
    return _response(matter_id=matter.id, runs=_load_runs(session, matter.id))


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


def _load_attachment(
    session: Session,
    *,
    matter_id: str,
    attachment_id: str,
) -> MatterAttachment:
    attachment = session.scalar(
        select(MatterAttachment).where(
            MatterAttachment.id == attachment_id,
            MatterAttachment.matter_id == matter_id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    return attachment


def _load_chunks(session: Session, attachment_id: str) -> list[MatterAttachmentChunk]:
    return list(
        session.scalars(
            select(MatterAttachmentChunk)
            .where(MatterAttachmentChunk.attachment_id == attachment_id)
            .order_by(MatterAttachmentChunk.chunk_index.asc())
        )
    )


def _load_runs(session: Session, matter_id: str) -> list[AffidavitIntelligenceRun]:
    return list(
        session.scalars(
            select(AffidavitIntelligenceRun)
            .where(AffidavitIntelligenceRun.matter_id == matter_id)
            .order_by(
                AffidavitIntelligenceRun.created_at.desc(),
                AffidavitIntelligenceRun.id.desc(),
            )
        )
    )


def _usable_source_chunks(
    chunks: list[MatterAttachmentChunk],
) -> list[MatterAttachmentChunk]:
    usable = [chunk for chunk in chunks if len(_normalize_space(chunk.content)) >= 24]
    total_chars = sum(len(_normalize_space(chunk.content)) for chunk in usable)
    if total_chars < MIN_SOURCE_TEXT_CHARS:
        return []
    return usable


def _create_run(
    session: Session,
    *,
    matter: Matter,
    attachment: MatterAttachment,
    context: SessionContext,
    status_value: str,
    source_hash: str,
    source_char_count: int,
    missing_data: list[str],
) -> AffidavitIntelligenceRun:
    run = AffidavitIntelligenceRun(
        company_id=matter.company_id,
        matter_id=matter.id,
        attachment_id=attachment.id,
        created_by_membership_id=context.membership.id,
        status=status_value,
        extraction_method="deterministic",
        parser_version=PARSER_VERSION,
        source_hash=source_hash,
        source_char_count=source_char_count,
        missing_data_json=json.dumps(missing_data),
        disclaimer=DISCLAIMER,
    )
    session.add(run)
    session.flush()
    return run


def _source_sentences(chunks: list[MatterAttachmentChunk]) -> list[SourceSentence]:
    out: list[SourceSentence] = []
    for chunk in chunks:
        page_reference = _page_reference(chunk.content)
        for sentence in _sentences(chunk.content):
            out.append(
                SourceSentence(
                    text=sentence,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    page_reference=page_reference,
                )
            )
    return out


def _extract_statements(sentences: list[SourceSentence]) -> list[ExtractedStatement]:
    statements: list[ExtractedStatement] = []
    seen: set[str] = set()
    has_negated_payment = any(_NEGATION_RE.search(sentence.text) for sentence in sentences)
    has_positive_payment = any(
        _PAYMENT_RE.search(sentence.text) and not _NEGATION_RE.search(sentence.text)
        for sentence in sentences
    )
    for sentence in sentences:
        text = sentence.text
        if _DATE_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.TIMELINE_POINT,
                text,
                MatterProceedingConfidence.MEDIUM,
            )
        if _MONEY_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.MONETARY_FIGURE,
                text,
                MatterProceedingConfidence.MEDIUM,
            )
        if _EXHIBIT_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.EXHIBIT_REFERENCE,
                text,
                MatterProceedingConfidence.MEDIUM,
            )
        if _FACT_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.FACT_ASSERTION,
                text,
                MatterProceedingConfidence.MEDIUM,
            )
        if _SUPPORT_REQUIRED_RE.search(text) and not _EXHIBIT_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.EVIDENCE_GAP,
                f"Supporting document should be reviewed for: {text}",
                MatterProceedingConfidence.LOW,
            )
        if _INTENT_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.KEY_STATEMENT,
                text,
                MatterProceedingConfidence.LOW,
            )
        if _ENTITY_RE.search(text) and _FACT_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.NAMED_ENTITY,
                text,
                MatterProceedingConfidence.LOW,
            )
        if has_negated_payment and has_positive_payment and _PAYMENT_RE.search(text):
            _append_statement(
                statements,
                seen,
                sentence,
                AffidavitStatementType.CONTRADICTION,
                "Potential internal inconsistency around payment or receipt language.",
                MatterProceedingConfidence.LOW,
            )
    return statements


def _append_statement(
    statements: list[ExtractedStatement],
    seen: set[str],
    sentence: SourceSentence,
    statement_type: str,
    statement_text: str,
    confidence_label: str,
) -> None:
    source_quote = sentence.text[:700]
    dedupe_key = _hash_key(statement_type, source_quote, str(sentence.chunk_index or 0))
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    statements.append(
        ExtractedStatement(
            statement_type=statement_type,
            statement_text=statement_text[:1000],
            source_quote=source_quote,
            confidence_label=confidence_label,
            chunk_id=sentence.chunk_id,
            chunk_index=sentence.chunk_index,
            page_reference=sentence.page_reference,
            dedupe_key=dedupe_key,
        )
    )


def _questions_for_statements(
    statements: list[ExtractedStatement],
) -> list[ExtractedQuestion]:
    questions: list[ExtractedQuestion] = []
    seen: set[str] = set()
    for statement in statements:
        if statement.statement_type == AffidavitStatementType.NAMED_ENTITY:
            continue
        category, prompt, reason, confidence = _question_parts(statement)
        _append_question(
            questions,
            seen,
            statement,
            category=category,
            question_text=prompt,
            reason=reason,
            confidence_label=confidence,
        )
        if _INTENT_RE.search(statement.source_quote):
            _append_question(
                questions,
                seen,
                statement,
                category=AffidavitQuestionCategory.INTENT_MOTIVE,
                question_text=(
                    "What source fact in the affidavit supports the stated intention "
                    "or motive, and who can independently verify it?"
                ),
                reason=(
                    "Intent or motive wording appears in the affidavit text "
                    "and requires source review."
                ),
                confidence_label=MatterProceedingConfidence.LOW,
            )
    return questions


def _question_parts(
    statement: ExtractedStatement,
) -> tuple[str, str, str, str]:
    if statement.statement_type == AffidavitStatementType.TIMELINE_POINT:
        return (
            AffidavitQuestionCategory.TIMELINE_INCONSISTENCY,
            "Which contemporaneous record supports the date or sequence stated here?",
            (
                "The affidavit contains a dated timeline assertion that should be "
                "checked against records."
            ),
            MatterProceedingConfidence.MEDIUM,
        )
    if statement.statement_type == AffidavitStatementType.MONETARY_FIGURE:
        return (
            AffidavitQuestionCategory.FINANCIAL_SCRUTINY,
            "Which account, invoice, receipt, or bank record supports this monetary figure?",
            "The affidavit states a monetary figure that should be tied to primary records.",
            MatterProceedingConfidence.MEDIUM,
        )
    if statement.statement_type == AffidavitStatementType.EXHIBIT_REFERENCE:
        return (
            AffidavitQuestionCategory.DOCUMENT_SUPPORT,
            "Where is the referenced annexure or exhibit, and does it prove the stated fact?",
            "The affidavit refers to a document or annexure that should be matched to the record.",
            MatterProceedingConfidence.MEDIUM,
        )
    if statement.statement_type == AffidavitStatementType.EVIDENCE_GAP:
        return (
            AffidavitQuestionCategory.DOCUMENT_SUPPORT,
            "What primary document supports this assertion, and why is it not identified here?",
            (
                "The statement appears to require supporting evidence but does "
                "not name a clear exhibit."
            ),
            MatterProceedingConfidence.LOW,
        )
    if statement.statement_type == AffidavitStatementType.CONTRADICTION:
        return (
            AffidavitQuestionCategory.EVIDENCE_CONTRADICTION,
            (
                "How should the apparent payment or receipt inconsistency be "
                "reconciled from the record?"
            ),
            (
                "The affidavit uses payment or receipt language that should be "
                "reviewed for internal consistency."
            ),
            MatterProceedingConfidence.LOW,
        )
    return (
        AffidavitQuestionCategory.FACT_BASED,
        "What direct source document or witness supports this statement?",
        (
            "The affidavit contains a material fact assertion that should be "
            "tested against source material."
        ),
        MatterProceedingConfidence.MEDIUM,
    )


def _append_question(
    questions: list[ExtractedQuestion],
    seen: set[str],
    statement: ExtractedStatement,
    *,
    category: str,
    question_text: str,
    reason: str,
    confidence_label: str,
) -> None:
    dedupe_key = _hash_key(category, question_text, statement.source_quote)
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    questions.append(
        ExtractedQuestion(
            category=category,
            question_text=question_text,
            reason=reason,
            source_quote=statement.source_quote,
            confidence_label=confidence_label,
            review_required=True,
            statement_key=statement.dedupe_key,
            chunk_id=statement.chunk_id,
            chunk_index=statement.chunk_index,
            page_reference=statement.page_reference,
            dedupe_key=dedupe_key,
        )
    )


def _persist_statements(
    session: Session,
    *,
    run: AffidavitIntelligenceRun,
    matter: Matter,
    attachment: MatterAttachment,
    statements: list[ExtractedStatement],
) -> list[tuple[ExtractedStatement, AffidavitStatement]]:
    rows: list[tuple[ExtractedStatement, AffidavitStatement]] = []
    for statement in statements:
        row = AffidavitStatement(
            run_id=run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            source_chunk_id=statement.chunk_id,
            source_chunk_index=statement.chunk_index,
            page_reference=statement.page_reference,
            statement_type=statement.statement_type,
            statement_text=statement.statement_text,
            source_quote=statement.source_quote,
            confidence_label=statement.confidence_label,
            review_status=AffidavitIntelligenceReviewStatus.REVIEW_REQUIRED,
            dedupe_key=statement.dedupe_key,
        )
        session.add(row)
        session.flush()
        rows.append((statement, row))
    return rows


def _persist_questions(
    session: Session,
    *,
    run: AffidavitIntelligenceRun,
    matter: Matter,
    attachment: MatterAttachment,
    questions: list[ExtractedQuestion],
    statements_by_key: dict[str, AffidavitStatement],
) -> None:
    for question in questions:
        statement = (
            statements_by_key.get(question.statement_key)
            if question.statement_key is not None
            else None
        )
        row = AffidavitQuestion(
            run_id=run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            statement_id=statement.id if statement else None,
            source_chunk_id=question.chunk_id,
            source_chunk_index=question.chunk_index,
            page_reference=question.page_reference,
            category=question.category,
            question_text=question.question_text,
            reason=question.reason,
            source_quote=question.source_quote,
            confidence_label=question.confidence_label,
            review_required=question.review_required,
            review_status=AffidavitIntelligenceReviewStatus.REVIEW_REQUIRED,
            dedupe_key=question.dedupe_key,
        )
        session.add(row)


def _response(
    *,
    matter_id: str,
    runs: list[AffidavitIntelligenceRun],
) -> AffidavitIntelligenceResponse:
    records = [_run_record(run) for run in runs]
    return AffidavitIntelligenceResponse(
        matter_id=matter_id,
        generated_at=datetime.now(UTC),
        disclaimer=DISCLAIMER,
        runs=records,
        latest_run=records[0] if records else None,
    )


def _run_record(run: AffidavitIntelligenceRun) -> AffidavitIntelligenceRunRecord:
    statements = sorted(run.statements, key=lambda row: (row.created_at, row.id))
    questions = sorted(run.questions, key=lambda row: (row.created_at, row.id))
    return AffidavitIntelligenceRunRecord(
        id=run.id,
        matter_id=run.matter_id,
        attachment_id=run.attachment_id,
        status=run.status,  # type: ignore[arg-type]
        extraction_method=run.extraction_method,  # type: ignore[arg-type]
        parser_version=run.parser_version,
        source_hash=run.source_hash,
        source_char_count=run.source_char_count,
        missing_data=_json_list(run.missing_data_json),
        model_run_id=run.model_run_id,
        created_by_membership_id=run.created_by_membership_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        statements=[_statement_record(statement) for statement in statements],
        questions=[_question_record(question) for question in questions],
    )


def _statement_record(statement: AffidavitStatement) -> AffidavitStatementRecord:
    return AffidavitStatementRecord(
        id=statement.id,
        run_id=statement.run_id,
        matter_id=statement.matter_id,
        attachment_id=statement.attachment_id,
        source_chunk_id=statement.source_chunk_id,
        source_chunk_index=statement.source_chunk_index,
        page_reference=statement.page_reference,
        statement_type=statement.statement_type,  # type: ignore[arg-type]
        statement_text=statement.statement_text,
        source_quote=statement.source_quote,
        confidence_label=statement.confidence_label,  # type: ignore[arg-type]
        review_status=statement.review_status,  # type: ignore[arg-type]
        created_at=statement.created_at,
        updated_at=statement.updated_at,
    )


def _question_record(question: AffidavitQuestion) -> AffidavitQuestionRecord:
    return AffidavitQuestionRecord(
        id=question.id,
        run_id=question.run_id,
        matter_id=question.matter_id,
        attachment_id=question.attachment_id,
        statement_id=question.statement_id,
        source_chunk_id=question.source_chunk_id,
        source_chunk_index=question.source_chunk_index,
        page_reference=question.page_reference,
        category=question.category,  # type: ignore[arg-type]
        question_text=question.question_text,
        reason=question.reason,
        source_quote=question.source_quote,
        confidence_label=question.confidence_label,  # type: ignore[arg-type]
        review_required=question.review_required,
        review_status=question.review_status,  # type: ignore[arg-type]
        created_at=question.created_at,
        updated_at=question.updated_at,
    )


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def _audit_analyzed(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    run: AffidavitIntelligenceRun,
    statement_count: int,
    question_count: int,
) -> None:
    record_from_context(
        session,
        context,
        action="affidavit_intelligence.analyzed",
        target_type="matter_attachment",
        target_id=run.attachment_id,
        matter_id=matter.id,
        metadata={
            "run_id": run.id,
            "status": run.status,
            "statement_count": statement_count,
            "question_count": question_count,
            "parser_version": PARSER_VERSION,
            "source_hash": run.source_hash,
        },
    )


def _sentences(text: str) -> list[str]:
    protected = re.sub(r"\bRs\.\s+", "Rs<DOT> ", text)
    pieces = re.split(r"(?<=[.;:])\s+|\n+", protected)
    out: list[str] = []
    for piece in pieces:
        cleaned = _normalize_space(piece).replace("Rs<DOT>", "Rs.")
        if len(cleaned) >= 16:
            out.append(cleaned[:1000])
    return out


def _page_reference(text: str) -> str | None:
    match = _PAGE_RE.search(text)
    return f"page {match.group(1)}" if match else None


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _hash_key(*parts: str) -> str:
    raw = "|".join(_normalize_space(part).lower() for part in parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


__all__ = [
    "DISCLAIMER",
    "PARSER_VERSION",
    "analyze_affidavit_attachment",
    "list_affidavit_intelligence",
]
