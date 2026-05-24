from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import AuthorityDocument, JudgmentAlert, JudgmentAlertRule
from caseops_api.schemas.authorities import (
    JudgmentAlertAuthorityRecord,
    JudgmentAlertDigestPreviewResponse,
    JudgmentAlertListResponse,
    JudgmentAlertRecord,
    JudgmentAlertRuleCreateRequest,
    JudgmentAlertRuleListResponse,
    JudgmentAlertRuleRecord,
    JudgmentAlertRuleUpdateRequest,
    JudgmentAlertRunRequest,
    JudgmentAlertRunResponse,
    JudgmentAlertUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext

_ALLOWED_DOCUMENT_TYPES = {"judgment", "order"}
_MAX_TERM_LENGTH = 80
_MAX_TERMS = 8
_MAX_SNIPPET_LENGTH = 280
_CANDIDATE_SCAN_LIMIT = 300


@dataclass(frozen=True)
class _Match:
    document: AuthorityDocument
    reason: str
    snippet: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_value(value: object) -> str:
    blob = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _compact_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    compacted = re.sub(r"\s+", " ", value).strip()
    if not compacted:
        return None
    return compacted[:max_length]


def _normalize_terms(value: Iterable[str] | None) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for raw in value or []:
        term = _compact_text(str(raw), max_length=_MAX_TERM_LENGTH)
        if term is None:
            continue
        folded = term.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        terms.append(term)
        if len(terms) >= _MAX_TERMS:
            break
    return terms


def _normalize_document_types(value: Iterable[str] | None) -> list[str]:
    cleaned: list[str] = []
    for raw in value or ["judgment", "order"]:
        doc_type = str(raw).strip()
        if doc_type not in _ALLOWED_DOCUMENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Judgment alerts support only judgment/order document types.",
            )
        if doc_type not in cleaned:
            cleaned.append(doc_type)
    return cleaned or ["judgment", "order"]


def _require_valid_dates(rule: JudgmentAlertRule | JudgmentAlertRuleCreateRequest) -> None:
    if rule.since_date and rule.until_date and rule.since_date > rule.until_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since_date must be on or before until_date.",
        )


def _require_bounded_filters(rule: JudgmentAlertRule) -> None:
    if any(
        (
            rule.query_terms_json,
            rule.court_name,
            rule.forum_level,
            rule.judge_name,
            rule.practice_area,
            rule.statute_terms_json,
            rule.since_date,
            rule.until_date,
        )
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Judgment alert rules require at least one bounded filter.",
    )


def _rule_record(rule: JudgmentAlertRule) -> JudgmentAlertRuleRecord:
    return JudgmentAlertRuleRecord(
        id=rule.id,
        company_id=rule.company_id,
        name=rule.name,
        query_terms=list(rule.query_terms_json or []),
        court_name=rule.court_name,
        forum_level=rule.forum_level,  # type: ignore[arg-type]
        judge_name=rule.judge_name,
        practice_area=rule.practice_area,
        statute_terms=list(rule.statute_terms_json or []),
        document_types=_normalize_document_types(rule.document_types_json),  # type: ignore[arg-type]
        since_date=rule.since_date,
        until_date=rule.until_date,
        is_archived=rule.is_archived,
        created_by_membership_id=rule.created_by_membership_id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        archived_at=rule.archived_at,
    )


def _rule_filter_keys(rule: JudgmentAlertRule) -> list[str]:
    keys: list[str] = []
    if rule.query_terms_json:
        keys.append("query_terms")
    if rule.court_name:
        keys.append("court_name")
    if rule.forum_level:
        keys.append("forum_level")
    if rule.judge_name:
        keys.append("judge_name")
    if rule.practice_area:
        keys.append("practice_area")
    if rule.statute_terms_json:
        keys.append("statute_terms")
    if rule.document_types_json:
        keys.append("document_types")
    if rule.since_date or rule.until_date:
        keys.append("date_range")
    return keys


def _rule_audit_metadata(
    rule: JudgmentAlertRule,
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "filter_keys": _rule_filter_keys(rule),
        "query_term_count": len(rule.query_terms_json or []),
        "query_terms_sha256": _hash_value(rule.query_terms_json or []),
        "statute_term_count": len(rule.statute_terms_json or []),
        "statute_terms_sha256": _hash_value(rule.statute_terms_json or []),
        "document_type_count": len(rule.document_types_json or []),
        "has_court_filter": bool(rule.court_name or rule.forum_level),
        "has_judge_filter": bool(rule.judge_name),
        "has_date_filter": bool(rule.since_date or rule.until_date),
        "is_archived": bool(rule.is_archived),
    }
    if extra:
        metadata.update(extra)
    return metadata


def _combined_search_text(document: AuthorityDocument) -> str:
    sections = document.sections_cited_json
    if isinstance(sections, list):
        section_text = " ".join(str(item) for item in sections[:20])
    else:
        section_text = str(sections or "")
    chunk_text = " ".join(
        _compact_text(chunk.content, max_length=800) or ""
        for chunk in list(document.chunks or [])[:4]
    )
    parts = [
        document.title,
        document.summary,
        document.court_name,
        document.forum_level,
        document.document_type,
        document.case_reference,
        document.neutral_citation,
        document.bench_name,
        section_text,
        chunk_text,
    ]
    return " ".join(part for part in parts if part).casefold()


def _terms_match(search_text: str, terms: Iterable[str] | None) -> bool:
    cleaned = _normalize_terms(terms)
    if not cleaned:
        return True
    return all(term.casefold() in search_text for term in cleaned)


def _snippet(document: AuthorityDocument) -> str | None:
    summary = _compact_text(document.summary, max_length=_MAX_SNIPPET_LENGTH)
    if summary:
        return summary
    for chunk in document.chunks or []:
        content = _compact_text(chunk.content, max_length=_MAX_SNIPPET_LENGTH)
        if content:
            return content
    return None


def _match_reason(rule: JudgmentAlertRule) -> str:
    reasons: list[str] = []
    if rule.query_terms_json:
        reasons.append("saved query terms")
    if rule.statute_terms_json:
        reasons.append("statute/section terms")
    if rule.court_name or rule.forum_level:
        reasons.append("court filters")
    if rule.judge_name:
        reasons.append("judge metadata")
    if rule.practice_area:
        reasons.append("practice-area metadata")
    if rule.since_date or rule.until_date:
        reasons.append("date filters")
    if not reasons:
        reasons.append("judgment/order document type")
    return f"Matched {'; '.join(reasons)} against existing authority metadata."


def _authority_record(
    document: AuthorityDocument,
    *,
    reason: str,
    snippet: str | None,
) -> JudgmentAlertAuthorityRecord:
    return JudgmentAlertAuthorityRecord(
        authority_document_id=document.id,
        title=document.title,
        court_name=document.court_name,
        forum_level=document.forum_level,
        document_type=document.document_type,
        citation_reference=document.neutral_citation or document.case_reference,
        decision_date=document.decision_date,
        match_reason=reason[:500],
        source=document.source,
        source_reference=document.source_reference,
        snippet=_compact_text(snippet, max_length=_MAX_SNIPPET_LENGTH),
    )


def _alert_record(alert: JudgmentAlert) -> JudgmentAlertRecord:
    return JudgmentAlertRecord(
        id=alert.id,
        company_id=alert.company_id,
        rule_id=alert.rule_id,
        is_read=alert.is_read,
        read_at=alert.read_at,
        dismissed_at=alert.dismissed_at,
        created_at=alert.created_at,
        authority=_authority_record(
            alert.authority_document,
            reason=alert.match_reason,
            snippet=alert.snippet,
        ),
    )


def _get_rule(session: Session, *, context: SessionContext, rule_id: str) -> JudgmentAlertRule:
    rule = session.scalar(
        select(JudgmentAlertRule).where(
            JudgmentAlertRule.id == rule_id,
            JudgmentAlertRule.company_id == context.company.id,
        )
    )
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Judgment alert rule not found.",
        )
    return rule


def list_judgment_alert_rules(
    session: Session,
    *,
    context: SessionContext,
) -> JudgmentAlertRuleListResponse:
    rows = list(
        session.scalars(
            select(JudgmentAlertRule)
            .where(JudgmentAlertRule.company_id == context.company.id)
            .order_by(JudgmentAlertRule.created_at.desc())
        )
    )
    return JudgmentAlertRuleListResponse(rules=[_rule_record(row) for row in rows])


def create_judgment_alert_rule(
    session: Session,
    *,
    context: SessionContext,
    payload: JudgmentAlertRuleCreateRequest,
) -> JudgmentAlertRuleRecord:
    query_terms = _normalize_terms(payload.query_terms)
    statute_terms = _normalize_terms(payload.statute_terms)
    document_types = _normalize_document_types(payload.document_types)
    _require_valid_dates(payload)
    rule = JudgmentAlertRule(
        company_id=context.company.id,
        created_by_membership_id=context.membership.id,
        name=payload.name,
        query_terms_json=query_terms,
        court_name=payload.court_name,
        forum_level=payload.forum_level,
        judge_name=payload.judge_name,
        practice_area=payload.practice_area,
        statute_terms_json=statute_terms,
        document_types_json=document_types,
        since_date=payload.since_date,
        until_date=payload.until_date,
    )
    _require_bounded_filters(rule)
    session.add(rule)
    session.flush()
    record_from_context(
        session,
        context,
        action="judgment_alert.rule_created",
        target_type="judgment_alert_rule",
        target_id=rule.id,
        metadata=_rule_audit_metadata(rule),
    )
    session.commit()
    return _rule_record(rule)


def update_judgment_alert_rule(
    session: Session,
    *,
    context: SessionContext,
    rule_id: str,
    payload: JudgmentAlertRuleUpdateRequest,
) -> JudgmentAlertRuleRecord:
    rule = _get_rule(session, context=context, rule_id=rule_id)
    fields = payload.model_fields_set
    if "name" in fields and payload.name:
        rule.name = payload.name
    if "query_terms" in fields:
        rule.query_terms_json = _normalize_terms(payload.query_terms)
    if "court_name" in fields:
        rule.court_name = payload.court_name
    if "forum_level" in fields:
        rule.forum_level = payload.forum_level
    if "judge_name" in fields:
        rule.judge_name = payload.judge_name
    if "practice_area" in fields:
        rule.practice_area = payload.practice_area
    if "statute_terms" in fields:
        rule.statute_terms_json = _normalize_terms(payload.statute_terms)
    if "document_types" in fields:
        rule.document_types_json = _normalize_document_types(payload.document_types)
    if "since_date" in fields:
        rule.since_date = payload.since_date
    if "until_date" in fields:
        rule.until_date = payload.until_date
    if "is_archived" in fields and payload.is_archived is not None:
        rule.is_archived = payload.is_archived
        rule.archived_at = _now() if payload.is_archived else None
    _require_valid_dates(rule)
    _require_bounded_filters(rule)
    session.add(rule)
    record_from_context(
        session,
        context,
        action="judgment_alert.rule_updated",
        target_type="judgment_alert_rule",
        target_id=rule.id,
        metadata=_rule_audit_metadata(rule, extra={"updated_field_count": len(fields)}),
    )
    session.commit()
    return _rule_record(rule)


def _candidate_query(rule: JudgmentAlertRule):
    document_types = _normalize_document_types(rule.document_types_json)
    statement = (
        select(AuthorityDocument)
        .options(selectinload(AuthorityDocument.chunks))
        .where(AuthorityDocument.document_type.in_(document_types))
    )
    if rule.forum_level:
        statement = statement.where(AuthorityDocument.forum_level == rule.forum_level)
    if rule.court_name:
        statement = statement.where(AuthorityDocument.court_name.ilike(f"%{rule.court_name}%"))
    if rule.since_date:
        statement = statement.where(AuthorityDocument.decision_date >= rule.since_date)
    if rule.until_date:
        statement = statement.where(AuthorityDocument.decision_date <= rule.until_date)
    return statement.order_by(
        AuthorityDocument.decision_date.desc().nullslast(),
        AuthorityDocument.created_at.desc(),
    ).limit(_CANDIDATE_SCAN_LIMIT)


def _rule_matches(rule: JudgmentAlertRule, documents: Iterable[AuthorityDocument]) -> list[_Match]:
    matches: list[_Match] = []
    for document in documents:
        search_text = _combined_search_text(document)
        if rule.judge_name and rule.judge_name.casefold() not in search_text:
            continue
        if rule.practice_area and rule.practice_area.casefold() not in search_text:
            continue
        if not _terms_match(search_text, rule.query_terms_json):
            continue
        if not _terms_match(search_text, rule.statute_terms_json):
            continue
        matches.append(
            _Match(
                document=document,
                reason=_match_reason(rule),
                snippet=_snippet(document),
            )
        )
    return matches


def run_judgment_alert_rule(
    session: Session,
    *,
    context: SessionContext,
    rule_id: str,
    payload: JudgmentAlertRunRequest,
) -> JudgmentAlertRunResponse:
    rule = _get_rule(session, context=context, rule_id=rule_id)
    if rule.is_archived:
        record_from_context(
            session,
            context,
            action="judgment_alert.rule_run",
            target_type="judgment_alert_rule",
            target_id=rule.id,
            metadata=_rule_audit_metadata(
                rule,
                extra={
                    "preview_only": payload.preview_only,
                    "matched_count": 0,
                    "created_count": 0,
                    "archived_rule": True,
                },
            ),
        )
        session.commit()
        return JudgmentAlertRunResponse(
            rule_id=rule.id,
            preview_only=payload.preview_only,
            matched_count=0,
            created_count=0,
            matches=[],
        )

    documents = list(session.scalars(_candidate_query(rule)))
    matches = _rule_matches(rule, documents)[: payload.limit]
    created_count = 0
    if not payload.preview_only:
        for match in matches:
            existing = session.scalar(
                select(JudgmentAlert).where(
                    JudgmentAlert.rule_id == rule.id,
                    JudgmentAlert.authority_document_id == match.document.id,
                    JudgmentAlert.company_id == context.company.id,
                )
            )
            if existing is not None:
                continue
            alert = JudgmentAlert(
                company_id=context.company.id,
                rule_id=rule.id,
                authority_document_id=match.document.id,
                match_reason=match.reason,
                snippet=match.snippet,
            )
            session.add(alert)
            created_count += 1
        session.flush()
    records = [
        _authority_record(match.document, reason=match.reason, snippet=match.snippet)
        for match in matches
    ]
    record_from_context(
        session,
        context,
        action="judgment_alert.rule_run",
        target_type="judgment_alert_rule",
        target_id=rule.id,
        metadata=_rule_audit_metadata(
            rule,
            extra={
                "preview_only": payload.preview_only,
                "matched_count": len(matches),
                "created_count": created_count,
                "authority_document_ids_sha256": _hash_value(
                    [match.document.id for match in matches]
                ),
            },
        ),
    )
    session.commit()
    return JudgmentAlertRunResponse(
        rule_id=rule.id,
        preview_only=payload.preview_only,
        matched_count=len(matches),
        created_count=created_count,
        matches=records,
    )


def list_judgment_alerts(
    session: Session,
    *,
    context: SessionContext,
    include_dismissed: bool = False,
    limit: int = 50,
) -> JudgmentAlertListResponse:
    statement = (
        select(JudgmentAlert)
        .options(selectinload(JudgmentAlert.authority_document))
        .where(JudgmentAlert.company_id == context.company.id)
        .order_by(JudgmentAlert.created_at.desc())
        .limit(limit)
    )
    if not include_dismissed:
        statement = statement.where(JudgmentAlert.dismissed_at.is_(None))
    alerts = list(session.scalars(statement))
    return JudgmentAlertListResponse(alerts=[_alert_record(alert) for alert in alerts])


def update_judgment_alert(
    session: Session,
    *,
    context: SessionContext,
    alert_id: str,
    payload: JudgmentAlertUpdateRequest,
) -> JudgmentAlertRecord:
    alert = session.scalar(
        select(JudgmentAlert)
        .options(selectinload(JudgmentAlert.authority_document))
        .where(
            JudgmentAlert.id == alert_id,
            JudgmentAlert.company_id == context.company.id,
        )
    )
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Judgment alert not found.",
        )
    if payload.action == "read":
        alert.is_read = True
        alert.read_at = alert.read_at or _now()
    elif payload.action == "dismiss":
        alert.dismissed_at = alert.dismissed_at or _now()
        alert.is_read = True
        alert.read_at = alert.read_at or alert.dismissed_at
    else:  # pragma: no cover - schema validates actions.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported judgment alert action.",
        )
    session.add(alert)
    record_from_context(
        session,
        context,
        action=f"judgment_alert.alert_{payload.action}",
        target_type="judgment_alert",
        target_id=alert.id,
        metadata={
            "action": payload.action,
            "rule_id_sha256": _hash_value(alert.rule_id),
            "authority_document_id_sha256": _hash_value(alert.authority_document_id),
            "is_read": alert.is_read,
            "dismissed": alert.dismissed_at is not None,
        },
    )
    session.commit()
    return _alert_record(alert)


def preview_judgment_alert_digest(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 10,
) -> JudgmentAlertDigestPreviewResponse:
    visible = list_judgment_alerts(
        session,
        context=context,
        include_dismissed=False,
        limit=limit,
    ).alerts
    unread_count = session.scalar(
        select(func.count())
        .where(
            JudgmentAlert.company_id == context.company.id,
            JudgmentAlert.is_read.is_(False),
            JudgmentAlert.dismissed_at.is_(None),
        )
    )
    dismissed_count = session.scalar(
        select(func.count()).where(
            JudgmentAlert.company_id == context.company.id,
            JudgmentAlert.dismissed_at.is_not(None),
        )
    )
    return JudgmentAlertDigestPreviewResponse(
        generated_at=_now(),
        unread_count=int(unread_count or 0),
        dismissed_count=int(dismissed_count or 0),
        alerts=visible,
    )
