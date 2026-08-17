from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    LegalUpdateSourceRecord,
    LegalUpdateSourceRun,
    LegalUpdateWatchlist,
    ModelRun,
    Statute,
    StatuteChangeEvent,
    User,
)
from caseops_api.schemas.legal_updates import (
    LegalUpdateRunRequest,
    LegalUpdateSourceRecordListResponse,
    LegalUpdateSourceRecordRecord,
    LegalUpdateSourceRunRecord,
    StatuteAmendmentHistoryResponse,
    StatuteChangeEventRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.http_retries import request_with_retries
from caseops_api.services.legal_updates import run_legal_update_watchlist
from caseops_api.services.llm import (
    LLMCallContext,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    build_provider,
    generate_structured,
)
from caseops_api.services.notification_delivery import redact_provider_error
from caseops_api.services.session_context import SessionContext

logger = logging.getLogger(__name__)

PRS_ACTS_SOURCE_KEY = "prs_acts_parliament"
PRS_SOURCE_CATEGORY = "prs_india"
SOURCE_BACKED_REVIEW_FRAMING = "Source-backed summary for lawyer review."


@dataclass(frozen=True)
class ParsedLegalUpdateSourceRecord:
    source_key: str
    source_record_key: str
    update_type: str
    title: str
    normalized_title: str
    source_url: str
    source_document_url: str | None
    published_date: date | None
    effective_date: date | None
    act_year: int | None
    source_category: str
    provenance_status: str
    content_hash: str
    raw_metadata: dict[str, object]


class LegalUpdateSummaryPayload(BaseModel):
    plain_english_summary: str = Field(min_length=1, max_length=2000)
    affected_acts: list[str] = Field(default_factory=list, max_length=12)
    affected_sections: list[str] = Field(default_factory=list, max_length=20)
    change_kind: str = Field(default="unknown", max_length=80)
    practical_legal_impact: str = Field(min_length=1, max_length=2000)
    suggested_lawyer_review_actions: list[str] = Field(default_factory=list, max_length=8)
    confidence: str = Field(default="low")
    source_url: str
    provenance_status: str
    review_framing: str = SOURCE_BACKED_REVIEW_FRAMING


class _PrsActsParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self._active_href: str | None = None
        self._active_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value for key, value in attrs}
        href = attr_map.get("href")
        if href:
            self._active_href = urljoin(f"{self.base_url}/", href.strip())
            self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_href:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._active_href:
            return
        text = _compact(" ".join(self._active_text), limit=500)
        if text:
            self.links.append((self._active_href, text))
        self._active_href = None
        self._active_text = []


def _now() -> datetime:
    return datetime.now(UTC)


def _compact(value: str | None, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _hash_value(value: object) -> str:
    blob = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _infer_year(title: str, href: str) -> int | None:
    for raw in re.findall(r"\b(18\d{2}|19\d{2}|20\d{2})\b", f"{title} {href}"):
        year = int(raw)
        if 1800 <= year <= 2100:
            return year
    return None


def _infer_update_type(title: str) -> str:
    lowered = title.lower()
    if "ordinance" in lowered:
        return "ordinance"
    if "repeal" in lowered or "repealing" in lowered:
        return "repeal"
    if "amendment" in lowered or "amending" in lowered:
        return "amendment"
    if "notification" in lowered:
        return "notification"
    return "act"


def _is_probable_act_link(href: str, title: str) -> bool:
    if len(title) < 4:
        return False
    lowered = f"{href} {title}".lower()
    if any(skip in lowered for skip in ("twitter", "facebook", "linkedin", "mailto:")):
        return False
    return "act" in lowered or "bill" in lowered or re.search(r"\b20\d{2}\b", lowered)


class PrsActsParliamentAdapter:
    source_key = PRS_ACTS_SOURCE_KEY
    source_category = PRS_SOURCE_CATEGORY

    def __init__(self, *, base_url: str | None = None, html: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.legal_update_prs_base_url).rstrip("/")
        self._html = html

    @property
    def acts_url(self) -> str:
        return urljoin(f"{self.base_url}/", "/acts/parliament")

    def fetch_html(self) -> str:
        if self._html is not None:
            return self._html
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = request_with_retries("GET", self.acts_url, client=client)
            return response.text

    def parse(self, html: str) -> list[ParsedLegalUpdateSourceRecord]:
        parser = _PrsActsParser(base_url=self.base_url)
        parser.feed(html)
        records: dict[str, ParsedLegalUpdateSourceRecord] = {}
        for href, title in parser.links:
            title = _compact(title, limit=500)
            if not _is_probable_act_link(href, title):
                continue
            normalized_title = _normalize_title(title)
            if not normalized_title:
                continue
            metadata = {
                "title": title,
                "source_url": href,
                "act_year": _infer_year(title, href),
                "update_type": _infer_update_type(title),
            }
            source_record_key = _hash_value(
                [self.source_key, href.lower(), normalized_title]
            )
            content_hash = _hash_value(metadata)
            records[source_record_key] = ParsedLegalUpdateSourceRecord(
                source_key=self.source_key,
                source_record_key=source_record_key,
                update_type=str(metadata["update_type"]),
                title=title,
                normalized_title=normalized_title,
                source_url=href,
                source_document_url=href,
                published_date=None,
                effective_date=None,
                act_year=metadata["act_year"],  # type: ignore[arg-type]
                source_category=self.source_category,
                provenance_status="source_metadata_available",
                content_hash=content_hash,
                raw_metadata=metadata,
            )
        return list(records.values())

    def fetch_records(self, *, limit: int) -> list[ParsedLegalUpdateSourceRecord]:
        return self.parse(self.fetch_html())[:limit]


def _map_statute(session: Session, parsed: ParsedLegalUpdateSourceRecord) -> str | None:
    statutes = list(session.scalars(select(Statute).where(Statute.is_active.is_(True))))
    for statute in statutes:
        haystack = parsed.normalized_title
        if _normalize_title(statute.short_name) in haystack:
            return statute.id
        if _normalize_title(statute.long_name) in haystack:
            return statute.id
    return None


def deterministic_summary(
    parsed: ParsedLegalUpdateSourceRecord | LegalUpdateSourceRecord,
) -> dict[str, object]:
    title = parsed.title
    source_url = parsed.source_url
    provenance_status = parsed.provenance_status
    update_type = parsed.update_type
    affected_acts = [title]
    return {
        "plain_english_summary": (
            f"{SOURCE_BACKED_REVIEW_FRAMING} PRS India lists {title} as a "
            f"{update_type.replace('_', ' ')} record."
        ),
        "affected_acts": affected_acts,
        "affected_sections": list(getattr(parsed, "sections_changed_json", None) or []),
        "change_kind": update_type,
        "practical_legal_impact": (
            "Review the source record and map any affected sections before relying on "
            "the change in client advice or filings."
        ),
        "suggested_lawyer_review_actions": [
            "Open the source link.",
            "Check affected Acts and sections.",
            "Update matter or contract references if relevant.",
        ],
        "confidence": "medium" if update_type == "act" else "low",
        "source_url": source_url,
        "provenance_status": provenance_status,
        "review_framing": SOURCE_BACKED_REVIEW_FRAMING,
    }


def summarize_source_record(
    session: Session,
    parsed: ParsedLegalUpdateSourceRecord,
    *,
    provider: LLMProvider | None = None,
) -> tuple[dict[str, object] | None, str, str | None]:
    settings = get_settings()
    if not settings.legal_update_summary_enabled:
        return deterministic_summary(parsed), "not_required", None
    messages = [
        LLMMessage(
            role="system",
            content=(
                "You are CaseOps. Produce a source-backed summary for lawyer "
                "review. Do not provide final legal advice or claim completeness."
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                "Respond with json matching this schema: "
                "{\"plain_english_summary\": str, \"affected_acts\": [str], "
                "\"affected_sections\": [str], \"change_kind\": str, "
                "\"practical_legal_impact\": str, "
                "\"suggested_lawyer_review_actions\": [str], "
                "\"confidence\": \"low|medium|high\", \"source_url\": str, "
                "\"provenance_status\": str, \"review_framing\": str}.\n"
                f"TITLE: {parsed.title}\n"
                f"UPDATE_TYPE: {parsed.update_type}\n"
                f"SOURCE_URL: {parsed.source_url}\n"
                f"PROVENANCE_STATUS: {parsed.provenance_status}\n"
                f"RAW_METADATA: {json.dumps(parsed.raw_metadata, default=str)}"
            ),
        ),
    ]
    llm = provider or build_provider(purpose="legal_update:summary")
    prompt_hash = hashlib.sha256(
        "\n".join(f"{message.role}:{message.content}" for message in messages).encode("utf-8")
    ).hexdigest()
    try:
        payload, completion = generate_structured(
            llm,
            session=session,
            schema=LegalUpdateSummaryPayload,
            messages=messages,
            context=LLMCallContext(purpose="legal_update:summary"),
            temperature=settings.llm_temperature,
            max_tokens=1200,
        )
    except LLMProviderError as exc:
        logger.warning("legal update summary failed for %s: %s", parsed.source_record_key, exc)
        return deterministic_summary(parsed), "failed", None
    run = ModelRun(
        company_id=None,
        matter_id=None,
        actor_membership_id=None,
        purpose="legal_update:summary",
        provider=completion.provider,
        model=completion.model,
        prompt_hash=prompt_hash,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        latency_ms=completion.latency_ms,
        status="ok",
    )
    session.add(run)
    session.flush()
    summary = payload.model_dump()
    summary["review_framing"] = SOURCE_BACKED_REVIEW_FRAMING
    return summary, "completed", run.id


def _change_type(update_type: str) -> str:
    if update_type == "act":
        return "new_act"
    if update_type == "amendment":
        return "amendment"
    if update_type == "repeal":
        return "repeal"
    if update_type == "notification":
        return "notification"
    return "unknown"


def upsert_source_records(
    session: Session,
    records: list[ParsedLegalUpdateSourceRecord],
    *,
    provider: LLMProvider | None = None,
) -> tuple[int, int, list[str], list[str]]:
    created_count = 0
    changed_count = 0
    created_ids: list[str] = []
    changed_ids: list[str] = []
    now = _now()
    for parsed in records:
        existing = session.scalar(
            select(LegalUpdateSourceRecord).where(
                LegalUpdateSourceRecord.source_key == parsed.source_key,
                LegalUpdateSourceRecord.source_record_key == parsed.source_record_key,
            )
        )
        statute_id = _map_statute(session, parsed)
        if existing is None:
            summary, summary_status, model_run_id = summarize_source_record(
                session,
                parsed,
                provider=provider,
            )
            existing = LegalUpdateSourceRecord(
                source_key=parsed.source_key,
                source_record_key=parsed.source_record_key,
                update_type=parsed.update_type,
                title=parsed.title,
                normalized_title=parsed.normalized_title,
                source_url=parsed.source_url,
                source_document_url=parsed.source_document_url,
                published_date=parsed.published_date,
                effective_date=parsed.effective_date,
                act_year=parsed.act_year,
                statute_id=statute_id,
                statute_section_ids_json=[],
                sections_changed_json=[],
                source_category=parsed.source_category,
                provenance_status=parsed.provenance_status,
                content_hash=parsed.content_hash,
                raw_metadata_json=parsed.raw_metadata,
                summary_json=summary,
                summary_status=summary_status,
                model_run_id=model_run_id,
                first_seen_at=now,
                last_seen_at=now,
            )
            session.add(existing)
            session.flush()
            created_count += 1
            created_ids.append(existing.id)
        else:
            existing.last_seen_at = now
            if existing.content_hash != parsed.content_hash:
                existing.content_hash = parsed.content_hash
                existing.title = parsed.title
                existing.normalized_title = parsed.normalized_title
                existing.source_url = parsed.source_url
                existing.source_document_url = parsed.source_document_url
                existing.published_date = parsed.published_date
                existing.effective_date = parsed.effective_date
                existing.act_year = parsed.act_year
                existing.statute_id = statute_id
                existing.raw_metadata_json = parsed.raw_metadata
                summary, summary_status, model_run_id = summarize_source_record(
                    session,
                    parsed,
                    provider=provider,
                )
                existing.summary_json = summary
                existing.summary_status = summary_status
                existing.model_run_id = model_run_id
                changed_count += 1
                changed_ids.append(existing.id)
            session.add(existing)
            session.flush()

        if existing.statute_id:
            already = session.scalar(
                select(StatuteChangeEvent).where(
                    StatuteChangeEvent.statute_id == existing.statute_id,
                    StatuteChangeEvent.source_record_id == existing.id,
                    StatuteChangeEvent.change_type == _change_type(existing.update_type),
                )
            )
            if already is None:
                summary_text = None
                if isinstance(existing.summary_json, dict):
                    summary_text = str(existing.summary_json.get("plain_english_summary") or "")
                session.add(
                    StatuteChangeEvent(
                        statute_id=existing.statute_id,
                        source_record_id=existing.id,
                        change_type=_change_type(existing.update_type),
                        title=existing.title,
                        sections_changed_json=existing.sections_changed_json or [],
                        summary=summary_text or None,
                        comparison_json={},
                        published_date=existing.published_date,
                        effective_date=existing.effective_date,
                        source_url=existing.source_url,
                    )
                )
    return created_count, changed_count, created_ids, changed_ids


def source_run_record(run: LegalUpdateSourceRun) -> LegalUpdateSourceRunRecord:
    return LegalUpdateSourceRunRecord(
        id=run.id,
        source_key=run.source_key,
        status=run.status,  # type: ignore[arg-type]
        started_at=run.started_at,
        completed_at=run.completed_at,
        fetched_count=run.fetched_count,
        created_count=run.created_count,
        changed_count=run.changed_count,
        error_message=run.error_message,
        metadata=dict(run.metadata_json or {}),
    )


def source_record_record(record: LegalUpdateSourceRecord) -> LegalUpdateSourceRecordRecord:
    return LegalUpdateSourceRecordRecord(
        id=record.id,
        source_key=record.source_key,
        source_record_key=record.source_record_key,
        update_type=record.update_type,  # type: ignore[arg-type]
        title=record.title,
        normalized_title=record.normalized_title,
        source_url=record.source_url,
        source_document_url=record.source_document_url,
        published_date=record.published_date,
        effective_date=record.effective_date,
        act_year=record.act_year,
        statute_id=record.statute_id,
        statute_section_ids=list(record.statute_section_ids_json or []),
        sections_changed=list(record.sections_changed_json or []),
        source_category=record.source_category,
        provenance_status=record.provenance_status,
        content_hash=record.content_hash,
        summary=record.summary_json,  # type: ignore[arg-type]
        summary_status=record.summary_status,  # type: ignore[arg-type]
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        updated_at=record.updated_at,
    )


def statute_change_event_record(event: StatuteChangeEvent) -> StatuteChangeEventRecord:
    return StatuteChangeEventRecord(
        id=event.id,
        statute_id=event.statute_id,
        source_record_id=event.source_record_id,
        change_type=event.change_type,  # type: ignore[arg-type]
        title=event.title,
        sections_changed=list(event.sections_changed_json or []),
        summary=event.summary,
        comparison=dict(event.comparison_json or {}),
        published_date=event.published_date,
        effective_date=event.effective_date,
        source_url=event.source_url,
        created_at=event.created_at,
    )


def list_source_records(
    session: Session,
    *,
    source_key: str | None = None,
    update_type: str | None = None,
    statute_id: str | None = None,
    summary_status: str | None = None,
    since_date: date | None = None,
    until_date: date | None = None,
    limit: int = 50,
) -> LegalUpdateSourceRecordListResponse:
    statement = select(LegalUpdateSourceRecord).order_by(
        LegalUpdateSourceRecord.published_date.desc().nullslast(),
        LegalUpdateSourceRecord.last_seen_at.desc(),
    )
    if source_key:
        statement = statement.where(LegalUpdateSourceRecord.source_key == source_key)
    if update_type:
        statement = statement.where(LegalUpdateSourceRecord.update_type == update_type)
    if statute_id:
        statement = statement.where(LegalUpdateSourceRecord.statute_id == statute_id)
    if summary_status:
        statement = statement.where(LegalUpdateSourceRecord.summary_status == summary_status)
    if since_date:
        statement = statement.where(
            (
                (LegalUpdateSourceRecord.published_date.is_not(None))
                & (LegalUpdateSourceRecord.published_date >= since_date)
            )
            | (
                (LegalUpdateSourceRecord.published_date.is_(None))
                & (LegalUpdateSourceRecord.effective_date >= since_date)
            )
        )
    if until_date:
        statement = statement.where(
            (
                (LegalUpdateSourceRecord.published_date.is_not(None))
                & (LegalUpdateSourceRecord.published_date <= until_date)
            )
            | (
                (LegalUpdateSourceRecord.published_date.is_(None))
                & (LegalUpdateSourceRecord.effective_date <= until_date)
            )
        )
    rows = list(session.scalars(statement.limit(max(1, min(limit, 100)))))
    return LegalUpdateSourceRecordListResponse(
        records=[source_record_record(record) for record in rows]
    )


def list_statute_amendment_history(
    session: Session,
    *,
    statute_id: str,
    limit: int = 50,
) -> StatuteAmendmentHistoryResponse:
    rows = list(
        session.scalars(
            select(StatuteChangeEvent)
            .where(StatuteChangeEvent.statute_id == statute_id)
            .order_by(
                StatuteChangeEvent.published_date.desc().nullslast(),
                StatuteChangeEvent.created_at.desc(),
            )
            .limit(max(1, min(limit, 100)))
        )
    )
    return StatuteAmendmentHistoryResponse(
        statute_id=statute_id,
        events=[statute_change_event_record(event) for event in rows],
    )


def sync_source(
    session: Session,
    *,
    source_key: str = PRS_ACTS_SOURCE_KEY,
    limit: int | None = None,
    html: str | None = None,
    provider: LLMProvider | None = None,
    context: SessionContext | None = None,
    run_watchlists: bool = False,
) -> LegalUpdateSourceRun:
    settings = get_settings()
    safe_limit = limit or settings.legal_update_sync_default_limit
    run = LegalUpdateSourceRun(
        source_key=source_key,
        status="failed",
        started_at=_now(),
        metadata_json={"frequency": settings.legal_update_sync_frequency},
    )
    session.add(run)
    session.flush()
    if context is not None:
        record_from_context(
            session,
            context,
            action="legal_update.source_sync_started",
            target_type="legal_update_source_run",
            target_id=run.id,
            metadata={
                "source_key": source_key,
                "limit": safe_limit,
                "frequency": settings.legal_update_sync_frequency,
            },
        )
    try:
        if source_key != PRS_ACTS_SOURCE_KEY:
            raise ValueError("Unsupported legal update source.")
        adapter = PrsActsParliamentAdapter(html=html)
        records = adapter.fetch_records(limit=safe_limit)
        created_count, changed_count, created_ids, changed_ids = upsert_source_records(
            session,
            records,
            provider=provider,
        )
        run.fetched_count = len(records)
        run.created_count = created_count
        run.changed_count = changed_count
        run.status = "completed"
        run.completed_at = _now()
        session.add(run)
        session.flush()
        if context is not None:
            for record_id in created_ids:
                record_from_context(
                    session,
                    context,
                    action="legal_update.source_record_created",
                    target_type="legal_update_source_record",
                    target_id=record_id,
                    metadata={"source_key": source_key},
                )
            for record_id in changed_ids:
                record_from_context(
                    session,
                    context,
                    action="legal_update.source_record_changed",
                    target_type="legal_update_source_record",
                    target_id=record_id,
                    metadata={"source_key": source_key},
                )
        if run_watchlists and context is not None:
            run_active_watchlists_for_context(session, context=context)
        return run
    except Exception as exc:
        run.status = "failed"
        run.error_message = redact_provider_error(exc)
        run.completed_at = _now()
        session.add(run)
        session.flush()
        return run


def run_active_watchlists_for_context(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 50,
) -> int:
    watchlists = list(
        session.scalars(
            select(LegalUpdateWatchlist)
            .where(
                LegalUpdateWatchlist.company_id == context.company.id,
                LegalUpdateWatchlist.is_archived.is_(False),
            )
            .order_by(LegalUpdateWatchlist.created_at.asc())
        )
    )
    count = 0
    for watchlist in watchlists:
        run_legal_update_watchlist(
            session,
            context=context,
            watchlist_id=watchlist.id,
            payload=LegalUpdateRunRequest(preview_only=False, limit=limit),
        )
        count += 1
    return count


def _system_contexts(session: Session) -> list[SessionContext]:
    memberships = list(
        session.scalars(
            select(CompanyMembership)
            .options(
                joinedload(CompanyMembership.company),
                joinedload(CompanyMembership.user),
            )
            .join(User, User.id == CompanyMembership.user_id)
            .join(Company, Company.id == CompanyMembership.company_id)
            .where(
                CompanyMembership.is_active.is_(True),
                User.is_active.is_(True),
                Company.is_active.is_(True),
            )
            .order_by(CompanyMembership.company_id, CompanyMembership.created_at.asc())
        )
    )
    contexts: list[SessionContext] = []
    seen_companies: set[str] = set()
    for membership in memberships:
        if membership.company_id in seen_companies:
            continue
        contexts.append(
            SessionContext(
                company=membership.company,
                user=membership.user,
                membership=membership,
            )
        )
        seen_companies.add(membership.company_id)
    return contexts


def sync_configured_legal_update_sources(
    session: Session,
    *,
    limit: int | None = None,
    provider: LLMProvider | None = None,
) -> list[LegalUpdateSourceRun]:
    run = sync_source(
        session,
        source_key=PRS_ACTS_SOURCE_KEY,
        limit=limit,
        provider=provider,
    )
    session.commit()
    if run.status != "completed":
        return [run]
    for context in _system_contexts(session):
        run_active_watchlists_for_context(session, context=context)
    return [run]


__all__ = [
    "PRS_ACTS_SOURCE_KEY",
    "PRS_SOURCE_CATEGORY",
    "PrsActsParliamentAdapter",
    "ParsedLegalUpdateSourceRecord",
    "deterministic_summary",
    "list_source_records",
    "list_statute_amendment_history",
    "source_record_record",
    "source_run_record",
    "sync_configured_legal_update_sources",
    "sync_source",
    "upsert_source_records",
]
