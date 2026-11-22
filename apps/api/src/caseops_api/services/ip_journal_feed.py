"""Automated public Trade Marks Journal feed for journal watch.

Two stages run inside the existing ``caseops-ip-journal-watch`` job:

1. Source: when the platform kill switch is on and at least one workspace has
   opted in, check the public listing (at most every six hours), record new
   PDFs from the last two weeks, download a bounded number of them politely,
   hash and parse them into the shared public store. The store holds only what
   IP India published, with its URL, retrieval time and content hash; no
   tenant data is ever written to it.
2. Workspaces: for each opted-in workspace, compare every parsed entry with
   the workspace's intake watch profiles using the journal-watch similarity
   rules, and record only the matching entries through the canonical
   ``ingest_journal`` writer, as the member who enabled the feed and within
   that member's access. Hits, publications and runs stay tenant-scoped.

Manual intake is unchanged and keeps working with the feed on or off.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import Settings, get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpIncidentKillSwitch,
    IpJournalFeedSetting,
    IpJournalFeedTenantRun,
    IpJournalPublication,
    IpPublicJournalCheck,
    IpPublicJournalDocument,
    IpPublicJournalEntry,
)
from caseops_api.schemas.ip_journal_feed import (
    IpJournalFeedSettingResponse,
    IpJournalFeedSettingUpdateRequest,
    IpJournalFeedStatusResponse,
    IpPublicJournalCheckResponse,
    IpPublicJournalDocumentResponse,
    IpPublicJournalReviewItemResponse,
)
from caseops_api.schemas.ip_watch import IpJournalIngestRequest, IpJournalPublicationCreate
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_docket_access import _lock_ip_writer_context
from caseops_api.services.ip_india_journal_parser import (
    PARSER_VERSION,
    JournalPdfError,
    extract_page_texts,
    parse_journal_pages,
)
from caseops_api.services.ip_india_journal_source import (
    LISTING_URL,
    SOURCE_KEY,
    IpIndiaJournalClient,
    JournalSourceError,
    JournalSourceRefused,
)
from caseops_api.services.ip_watch import (
    MAX_ACTIVE_PROFILES_PER_INGEST,
    MAX_HITS_PER_INGEST,
    MAX_INGEST_PUBLICATIONS,
    MAX_PROFILE_PUBLICATION_COMPARISONS,
    _assert_automated_watch_available,
    _intake_profiles_statement,
    _similarity,
    ingest_journal,
)
from caseops_api.services.session_context import SessionContext

logger = logging.getLogger(__name__)

FEED_PROVIDER_KEY = SOURCE_KEY
LOOKBACK_DAYS = 14
LISTING_CHECK_INTERVAL = timedelta(hours=6)
MAX_DOCUMENTS_PER_RUN = 4
MAX_DOCUMENT_ATTEMPTS = 3
MAX_MATCHES_PER_DOCUMENT = 500
STATUS_DOCUMENT_LIMIT = 24
STATUS_REVIEW_LIMIT = 50
WATCH_FEATURE_ID = "watch_operations"
TERMINAL_WORKSPACE_STATUSES = frozenset({"completed", "match_limit_exceeded"})
PUBLISHER = (
    "Office of the Controller General of Patents, Designs and Trade Marks, "
    "Government of India (ipindia.gov.in)"
)
TERMS_REVIEWED_ON = "2026-11-22"


@dataclass(slots=True)
class JournalFeedRunResult:
    status: str
    listing_checked: bool = False
    check_status: str | None = None
    check_reason: str | None = None
    documents_discovered: int = 0
    documents_fetched: int = 0
    documents_failed: int = 0
    entries_stored: int = 0
    review_entries: int = 0
    external_requests: int = 0
    workspace_runs: dict[str, int] = field(default_factory=dict)
    hits_created: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _journal_digits(journal_number: str) -> str:
    match = re.match(r"\d+", journal_number)
    return match.group(0) if match else journal_number


# --- source stage ---------------------------------------------------------


def _record_check(
    session: Session,
    *,
    now: datetime,
    status: str,
    reason: str | None = None,
    http_status: int | None = None,
    listing_sha256: str | None = None,
    issues: int = 0,
    discovered: int = 0,
) -> None:
    session.add(
        IpPublicJournalCheck(
            source_key=SOURCE_KEY,
            status=status,
            reason_code=reason,
            http_status=http_status,
            listing_sha256=listing_sha256,
            issues_listed=issues,
            documents_discovered=discovered,
            checked_at=now,
        )
    )
    session.commit()


def _record_listing(session: Session, listing: Any, *, now: datetime) -> int:
    window_start = now.date() - timedelta(days=LOOKBACK_DAYS)
    recent = [
        item
        for item in listing.files
        if item.journal_date >= window_start
        and (item.available_on is None or item.available_on <= now.date())
    ]
    if not recent:
        return 0
    known = set(
        session.execute(
            select(IpPublicJournalDocument.journal_number, IpPublicJournalDocument.file_name).where(
                IpPublicJournalDocument.source_key == SOURCE_KEY,
                IpPublicJournalDocument.journal_number.in_(
                    {item.journal_number for item in recent}
                ),
            )
        ).all()
    )
    created = 0
    for item in recent:
        if (item.journal_number, item.file_name) in known:
            continue
        known.add((item.journal_number, item.file_name))
        allowed = item.source_url is not None
        session.add(
            IpPublicJournalDocument(
                source_key=SOURCE_KEY,
                journal_number=item.journal_number,
                journal_date=item.journal_date,
                available_on=item.available_on,
                file_name=item.file_name,
                # A name outside the allowed shape is never requested; it is
                # kept, linked to the listing that named it, for review.
                source_url=item.source_url or LISTING_URL,
                status="pending" if allowed else "failed",
                attempts=0,
                error_code=None if allowed else "file_name_not_allowed",
                entry_count=0,
                review_count=0,
                discovered_at=now,
                updated_at=now,
            )
        )
        created += 1
    return created


def _store_document(
    session: Session, document: IpPublicJournalDocument, data: bytes, *, now: datetime
) -> None:
    document.retrieved_at = now
    document.content_sha256 = sha256(data).hexdigest()
    document.byte_size = len(data)
    document.parser_version = PARSER_VERSION
    document.updated_at = now
    try:
        pages = extract_page_texts(data)
    except JournalPdfError:
        document.status = "failed"
        document.error_code = "pdf_unreadable"
        return
    parsed = parse_journal_pages(
        pages,
        journal_number=_journal_digits(document.journal_number),
        journal_date=document.journal_date,
    )
    for entry in parsed.entries:
        session.add(
            IpPublicJournalEntry(
                document_id=document.id,
                entry_index=entry.entry_index,
                status=entry.status,
                review_reason=(entry.review_reason or "")[:200] or None,
                page_start=entry.page_start,
                page_end=entry.page_end,
                journal_page=entry.journal_page,
                application_number=entry.application_number,
                filing_date=entry.filing_date,
                mark_text=entry.mark_text,
                proprietor_name=entry.proprietor_name,
                class_numbers_json=list(entry.class_numbers),
                goods_services_json=entry.goods_services,
                registry_office=(entry.registry_office or "")[:80] or None,
                text_sha256=entry.text_sha256,
                created_at=now,
            )
        )
    document.page_count = parsed.page_count
    document.entry_count = parsed.parsed_count
    document.review_count = parsed.review_count
    document.status = "needs_review" if parsed.review_count else "parsed"
    document.error_code = None


def _fetch_public_source(
    session: Session, client: IpIndiaJournalClient, *, now: datetime, result: JournalFeedRunResult
) -> None:
    last = session.scalar(
        select(IpPublicJournalCheck)
        .where(IpPublicJournalCheck.source_key == SOURCE_KEY)
        .order_by(IpPublicJournalCheck.checked_at.desc())
        .limit(1)
    )
    recently_checked = last is not None and now - _aware(last.checked_at) < LISTING_CHECK_INTERVAL
    if recently_checked and last is not None and last.status == "refused":
        # The source refused us recently; send nothing until the interval passes.
        result.check_status, result.check_reason = "skipped", "recently_refused"
        return
    if not recently_checked:
        result.listing_checked = True
        try:
            body, listing = client.fetch_listing()
        except JournalSourceRefused as exc:
            result.check_status, result.check_reason = "refused", exc.reason_code
            _record_check(
                session, now=now, status="refused", reason=exc.reason_code,
                http_status=exc.http_status,
            )
            return
        except JournalSourceError as exc:
            result.check_status, result.check_reason = "failed", exc.reason_code
            _record_check(
                session, now=now, status="failed", reason=exc.reason_code,
                http_status=exc.http_status,
            )
            return
        discovered = _record_listing(session, listing, now=now)
        result.documents_discovered = discovered
        result.check_status = "succeeded"
        _record_check(
            session, now=now, status="succeeded", http_status=200,
            listing_sha256=sha256(body).hexdigest(), issues=listing.issues,
            discovered=discovered,
        )
    window_start = now.date() - timedelta(days=LOOKBACK_DAYS)
    pending = list(
        session.scalars(
            select(IpPublicJournalDocument)
            .where(
                IpPublicJournalDocument.source_key == SOURCE_KEY,
                IpPublicJournalDocument.status == "pending",
                IpPublicJournalDocument.journal_date >= window_start,
            )
            .order_by(
                IpPublicJournalDocument.journal_date.desc(), IpPublicJournalDocument.file_name
            )
            .limit(MAX_DOCUMENTS_PER_RUN)
        )
    )
    for document in pending:
        try:
            data = client.fetch_document(document.source_url)
        except JournalSourceRefused as exc:
            document.attempts += 1
            document.error_code = exc.reason_code
            document.status = "failed" if document.attempts >= MAX_DOCUMENT_ATTEMPTS else "pending"
            document.updated_at = now
            result.documents_failed += 1
            result.check_status, result.check_reason = "refused", exc.reason_code
            _record_check(
                session, now=now, status="refused", reason=exc.reason_code,
                http_status=exc.http_status,
            )
            return
        except JournalSourceError as exc:
            document.attempts += 1
            document.error_code = exc.reason_code
            document.status = "failed" if document.attempts >= MAX_DOCUMENT_ATTEMPTS else "pending"
            document.updated_at = now
            result.documents_failed += 1
            session.commit()
            continue
        document.attempts += 1
        _store_document(session, document, data, now=now)
        session.commit()
        result.documents_fetched += 1
        result.entries_stored += document.entry_count
        result.review_entries += document.review_count


# --- workspace stage ------------------------------------------------------


def _run_as_context(session: Session, setting: IpJournalFeedSetting) -> SessionContext | None:
    membership = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == setting.run_as_membership_id,
            CompanyMembership.company_id == setting.company_id,
        )
    )
    company = session.get(Company, setting.company_id)
    if (
        membership is None
        or company is None
        or not membership.is_active
        or not membership.user.is_active
    ):
        return None
    return SessionContext(company=company, user=membership.user, membership=membership)


def _source_page(entry: IpPublicJournalEntry) -> str:
    pages = (
        f"PDF page {entry.page_start}"
        if entry.page_end == entry.page_start
        else f"PDF pages {entry.page_start}-{entry.page_end}"
    )
    return f"{pages}, journal page {entry.journal_page}" if entry.journal_page else pages


def _publication_fields(
    document: IpPublicJournalDocument, entry: IpPublicJournalEntry
) -> dict[str, Any]:
    page_link = f"{document.source_url}#page={entry.page_start}"
    return {
        "application_id": None,
        "journal_number": document.journal_number,
        "journal_date": document.journal_date,
        "publication_kind": "advertisement",
        "application_number": entry.application_number,
        "mark_text": entry.mark_text,
        # A device mark has no extracted words; its image is on this page.
        "device_reference": None if entry.mark_text else page_link,
        "proprietor_name": entry.proprietor_name,
        "office": "IP India",
        "jurisdiction": "IN",
        "class_numbers": list(entry.class_numbers_json),
        "goods_services": dict(entry.goods_services_json),
        "publication_scope": {},
        "source_url": document.source_url,
        "source_page": _source_page(entry),
        "source_status": "available",
        "source_retrieved_at": _aware(document.retrieved_at) if document.retrieved_at else None,
        "parser_version": PARSER_VERSION,
        "attribution": {
            "publisher": PUBLISHER,
            "source": "Trade Marks Journal (public listing)",
            "listing_url": LISTING_URL,
            "capture_method": "automated_public_feed",
            "terms_reviewed_on": TERMS_REVIEWED_ON,
        },
        "raw_evidence": {
            "capture_method": "automated_public_feed",
            "journal_page_reference": page_link,
            "document_content_sha256": document.content_sha256,
            "entry_text_sha256": entry.text_sha256,
            "public_entry_id": entry.id,
            "registry_office": entry.registry_office,
            "filing_date": entry.filing_date.isoformat() if entry.filing_date else None,
        },
    }


def _candidate(fields: dict[str, Any]) -> IpJournalPublication:
    """A transient row for the shared similarity rules; never added to a session."""

    return IpJournalPublication(
        mark_text=fields["mark_text"],
        device_reference=fields["device_reference"],
        proprietor_name=fields["proprietor_name"],
        jurisdiction=fields["jurisdiction"],
        class_numbers_json=fields["class_numbers"],
        raw_evidence_json=fields["raw_evidence"],
    )


def _compare_document(
    session: Session,
    setting: IpJournalFeedSetting,
    document: IpPublicJournalDocument,
) -> dict[str, Any]:
    outcome: dict[str, Any] = {
        "status": "completed",
        "entries_compared": 0,
        "matched_entries": 0,
        "publications_created": 0,
        "hits_created": 0,
        "ingestion_run_ids": [],
        "error_code": None,
    }
    context = _run_as_context(session, setting)
    if context is None:
        return {**outcome, "status": "actor_unavailable"}
    if session.scalar(
        select(IpIncidentKillSwitch.id).where(
            IpIncidentKillSwitch.company_id == setting.company_id,
            IpIncidentKillSwitch.feature_id == WATCH_FEATURE_ID,
            IpIncidentKillSwitch.status == "active",
        )
    ):
        return {**outcome, "status": "incident_kill_switch"}
    try:
        _assert_automated_watch_available(session, context=context)
    except HTTPException as exc:
        reason = exc.detail.get("reason") if isinstance(exc.detail, dict) else None
        return {**outcome, "status": "feature_unavailable", "error_code": reason}
    profiles = list(
        session.scalars(
            _intake_profiles_statement(session, context=context).limit(
                MAX_ACTIVE_PROFILES_PER_INGEST + 1
            )
        )
    )
    if not profiles:
        return {**outcome, "status": "no_active_profiles"}
    if len(profiles) > MAX_ACTIVE_PROFILES_PER_INGEST:
        return {**outcome, "status": "failed", "error_code": "too_many_active_profiles"}
    entries = list(
        session.scalars(
            select(IpPublicJournalEntry)
            .where(
                IpPublicJournalEntry.document_id == document.id,
                IpPublicJournalEntry.status == "parsed",
            )
            .order_by(IpPublicJournalEntry.entry_index)
        )
    )
    outcome["entries_compared"] = len(entries)
    matches: list[IpJournalPublicationCreate] = []
    rejected = 0
    for entry in entries:
        fields = _publication_fields(document, entry)
        candidate = _candidate(fields)
        if not any(_similarity(profile, candidate)["matched"] for profile in profiles):
            continue
        try:
            matches.append(IpJournalPublicationCreate(**fields))
        except ValidationError:
            rejected += 1
    outcome["matched_entries"] = len(matches) + rejected
    if rejected:
        outcome["error_code"] = f"entries_rejected_by_intake:{rejected}"
    if len(matches) + rejected > MAX_MATCHES_PER_DOCUMENT:
        # Fail closed and visibly: the profiles are too broad for automatic
        # recording (a class-only profile matches every entry in its class).
        return {**outcome, "status": "match_limit_exceeded"}
    if not matches:
        return outcome
    batch_size = max(
        1,
        min(
            MAX_INGEST_PUBLICATIONS,
            MAX_PROFILE_PUBLICATION_COMPARISONS // len(profiles),
            MAX_HITS_PER_INGEST // len(profiles),
        ),
    )
    for start in range(0, len(matches), batch_size):
        batch = matches[start : start + batch_size]
        digest = sha256(
            "|".join(item.raw_evidence["public_entry_id"] for item in batch).encode("utf-8")
        ).hexdigest()[:24]
        payload = IpJournalIngestRequest(
            idempotency_key=f"journal-feed:{document.id}:{digest}",
            provider_key=FEED_PROVIDER_KEY,
            external_call=True,
            cost_minor=0,
            currency="INR",
            publications=batch,
        )
        try:
            run, _, hits, replay = ingest_journal(session, context=context, payload=payload)
        except HTTPException as exc:
            session.rollback()
            return {**outcome, "status": "failed", "error_code": f"ingest_http_{exc.status_code}"}
        outcome["ingestion_run_ids"].append(run.id)
        if not replay:
            outcome["publications_created"] += run.publications_created
            outcome["hits_created"] += len(hits)
    return outcome


def _compare_for_workspaces(
    session: Session, *, now: datetime, result: JournalFeedRunResult
) -> None:
    window_start = now.date() - timedelta(days=LOOKBACK_DAYS)
    documents = list(
        session.scalars(
            select(IpPublicJournalDocument)
            .where(
                IpPublicJournalDocument.source_key == SOURCE_KEY,
                IpPublicJournalDocument.status.in_(("parsed", "needs_review")),
                IpPublicJournalDocument.journal_date >= window_start,
            )
            .order_by(IpPublicJournalDocument.journal_date, IpPublicJournalDocument.file_name)
        )
    )
    company_ids = list(
        session.scalars(
            select(IpJournalFeedSetting.company_id)
            .where(IpJournalFeedSetting.enabled.is_(True))
            .order_by(IpJournalFeedSetting.company_id)
        )
    )
    document_ids = [document.id for document in documents]
    for company_id in company_ids:
        for document_id in document_ids:
            setting = session.get(IpJournalFeedSetting, company_id)
            document = session.get(IpPublicJournalDocument, document_id)
            if setting is None or not setting.enabled or document is None:
                break
            existing = session.scalar(
                select(IpJournalFeedTenantRun).where(
                    IpJournalFeedTenantRun.company_id == company_id,
                    IpJournalFeedTenantRun.document_id == document_id,
                )
            )
            if existing is not None and existing.status in TERMINAL_WORKSPACE_STATUSES:
                continue
            started = _now()
            run_as = setting.run_as_membership_id
            try:
                outcome = _compare_document(session, setting, document)
            except Exception:  # noqa: BLE001 - one workspace must not stop the others
                logger.exception("journal feed comparison failed for one workspace")
                session.rollback()
                outcome = {"status": "failed", "error_code": "comparison_error"}
            row = session.scalar(
                select(IpJournalFeedTenantRun).where(
                    IpJournalFeedTenantRun.company_id == company_id,
                    IpJournalFeedTenantRun.document_id == document_id,
                )
            )
            if row is None:
                row = IpJournalFeedTenantRun(
                    company_id=company_id, document_id=document_id, attempts=0, started_at=started
                )
                session.add(row)
            row.run_as_membership_id = run_as
            row.status = outcome["status"]
            row.attempts += 1
            row.entries_compared = outcome.get("entries_compared", 0)
            row.matched_entries = outcome.get("matched_entries", 0)
            row.publications_created = outcome.get("publications_created", 0)
            row.hits_created = outcome.get("hits_created", 0)
            row.ingestion_run_ids_json = outcome.get("ingestion_run_ids", [])
            row.error_code = outcome.get("error_code")
            row.started_at = started
            row.completed_at = _now()
            session.commit()
            result.workspace_runs[row.status] = result.workspace_runs.get(row.status, 0) + 1
            result.hits_created += row.hits_created


def run_ip_india_journal_feed(
    session: Session,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
    client_factory: Callable[[], IpIndiaJournalClient] | None = None,
) -> JournalFeedRunResult:
    """One scheduled pass. Safe to re-run: nothing already fetched is fetched again."""

    current = _aware(now) if now else _now()
    if not (settings or get_settings()).ip_journal_feed_enabled:
        return JournalFeedRunResult(status="disabled")
    subscribed = session.scalar(
        select(func.count())
        .select_from(IpJournalFeedSetting)
        .where(IpJournalFeedSetting.enabled.is_(True))
    )
    if not subscribed:
        # Nobody uses the feed: send no request to the public source.
        return JournalFeedRunResult(status="no_subscribers")
    result = JournalFeedRunResult(status="ran")
    client = client_factory() if client_factory else IpIndiaJournalClient()
    try:
        _fetch_public_source(session, client, now=current, result=result)
    finally:
        result.external_requests = client.requests_made
        client.close()
    _compare_for_workspaces(session, now=current, result=result)
    return result


# --- workspace setting and status ------------------------------------------


def _setting_row(session: Session, company_id: str, *, for_update: bool = False) -> Any:
    statement = select(IpJournalFeedSetting).where(IpJournalFeedSetting.company_id == company_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def get_journal_feed_status(
    session: Session, *, context: SessionContext
) -> IpJournalFeedStatusResponse:
    setting = _setting_row(session, context.company.id)
    last = session.scalar(
        select(IpPublicJournalCheck)
        .where(IpPublicJournalCheck.source_key == SOURCE_KEY)
        .order_by(IpPublicJournalCheck.checked_at.desc())
        .limit(1)
    )
    documents = list(
        session.scalars(
            select(IpPublicJournalDocument)
            .where(IpPublicJournalDocument.source_key == SOURCE_KEY)
            .order_by(
                IpPublicJournalDocument.journal_date.desc(), IpPublicJournalDocument.file_name
            )
            .limit(STATUS_DOCUMENT_LIMIT)
        )
    )
    runs = {
        row.document_id: row
        for row in session.scalars(
            select(IpJournalFeedTenantRun).where(
                IpJournalFeedTenantRun.company_id == context.company.id,
                IpJournalFeedTenantRun.document_id.in_([item.id for item in documents]),
            )
        )
    } if documents else {}
    review_filter = (
        IpPublicJournalEntry.status == "needs_review",
        IpPublicJournalDocument.source_key == SOURCE_KEY,
    )
    review_rows = session.execute(
        select(IpPublicJournalEntry, IpPublicJournalDocument)
        .join(
            IpPublicJournalDocument,
            IpPublicJournalDocument.id == IpPublicJournalEntry.document_id,
        )
        .where(*review_filter)
        .order_by(
            IpPublicJournalDocument.journal_date.desc(),
            IpPublicJournalDocument.file_name,
            IpPublicJournalEntry.entry_index,
        )
        .limit(STATUS_REVIEW_LIMIT)
    ).all()
    review_total = session.scalar(
        select(func.count())
        .select_from(IpPublicJournalEntry)
        .join(
            IpPublicJournalDocument,
            IpPublicJournalDocument.id == IpPublicJournalEntry.document_id,
        )
        .where(*review_filter)
    ) or 0
    return IpJournalFeedStatusResponse(
        source_key=SOURCE_KEY,
        listing_url=LISTING_URL,
        attribution=PUBLISHER,
        global_enabled=get_settings().ip_journal_feed_enabled,
        setting=IpJournalFeedSettingResponse.model_validate(setting) if setting else None,
        last_check=IpPublicJournalCheckResponse.model_validate(last) if last else None,
        documents=[
            IpPublicJournalDocumentResponse(
                id=item.id,
                journal_number=item.journal_number,
                journal_date=item.journal_date,
                available_on=item.available_on,
                file_name=item.file_name,
                source_url=item.source_url,
                status=item.status,
                attempts=item.attempts,
                content_sha256=item.content_sha256,
                byte_size=item.byte_size,
                page_count=item.page_count,
                entry_count=item.entry_count,
                review_count=item.review_count,
                parser_version=item.parser_version,
                error_code=item.error_code,
                retrieved_at=item.retrieved_at,
                workspace_status=runs[item.id].status if item.id in runs else None,
                workspace_entries_compared=(
                    runs[item.id].entries_compared if item.id in runs else None
                ),
            )
            for item in documents
        ],
        review_items=[
            IpPublicJournalReviewItemResponse(
                id=entry.id,
                document_id=document.id,
                journal_number=document.journal_number,
                journal_date=document.journal_date,
                page_start=entry.page_start,
                page_end=entry.page_end,
                journal_page=entry.journal_page,
                review_reason=entry.review_reason,
                application_number=entry.application_number,
                source_url=f"{document.source_url}#page={entry.page_start}",
            )
            for entry, document in review_rows
        ],
        review_total=review_total,
    )


def update_journal_feed_setting(
    session: Session,
    *,
    context: SessionContext,
    payload: IpJournalFeedSettingUpdateRequest,
) -> IpJournalFeedStatusResponse:
    locked = _lock_ip_writer_context(
        session, context=context, required_capability="ip:watch_manage"
    )
    if payload.enabled:
        # The feed is the automated journal-watch feature, not manual intake.
        _assert_automated_watch_available(session, context=locked)
    row = _setting_row(session, locked.company.id, for_update=True)
    now = _now()
    if row is None:
        if payload.expected_version is not None:
            raise HTTPException(status_code=409, detail="Journal feed setting changed; reload.")
        row = IpJournalFeedSetting(
            company_id=locked.company.id,
            enabled=payload.enabled,
            run_as_membership_id=locked.membership.id,
            updated_by_membership_id=locked.membership.id,
            version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        if payload.expected_version != row.version:
            raise HTTPException(status_code=409, detail="Journal feed setting changed; reload.")
        row.enabled = payload.enabled
        if payload.enabled:
            # Comparisons run with the access of the member who turned it on.
            row.run_as_membership_id = locked.membership.id
        row.updated_by_membership_id = locked.membership.id
        row.version += 1
        row.updated_at = now
    session.flush()
    record_from_context(
        session,
        locked,
        action=(
            "ip_watch.journal_feed_enabled"
            if payload.enabled
            else "ip_watch.journal_feed_disabled"
        ),
        target_type="ip_journal_feed_setting",
        target_id=locked.company.id,
        metadata={
            "enabled": row.enabled,
            "version": row.version,
            "run_as_membership_id": row.run_as_membership_id,
            "source_key": SOURCE_KEY,
        },
    )
    session.commit()
    return get_journal_feed_status(session, context=locked)


__all__ = [
    "FEED_PROVIDER_KEY",
    "JournalFeedRunResult",
    "get_journal_feed_status",
    "run_ip_india_journal_feed",
    "update_journal_feed_setting",
]
