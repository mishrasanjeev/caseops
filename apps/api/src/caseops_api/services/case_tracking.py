from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    ModelRun,
    NotificationDeliveryChannel,
    TrackedCase,
    TrackedCaseBookmark,
    TrackedCasePollRun,
    TrackedCaseProviderOperation,
    TrackedCaseProviderSnapshot,
    TrackedCaseUpdate,
    User,
)
from caseops_api.schemas.case_tracking import (
    CaseTrackingBookmarkCreateRequest,
    CaseTrackingBookmarkListResponse,
    CaseTrackingBookmarkRecord,
    CaseTrackingBookmarkUpdateRequest,
    CaseTrackingPollRunRecord,
    CaseTrackingProviderStatusResponse,
    CaseTrackingRefreshResponse,
    CaseTrackingSearchRequest,
    CaseTrackingSearchResponse,
    CaseTrackingSearchResultRecord,
    CaseTrackingUpdateListResponse,
    CaseTrackingUpdateRecord,
    TrackedCaseRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProvider,
    CaseTrackingProviderError,
    CaseTrackingProviderUnavailable,
    ProviderCaseEvent,
    ProviderCaseSnapshot,
    get_case_tracking_provider,
    provider_status,
)
from caseops_api.services.http_retries import request_with_retries
from caseops_api.services.llm import (
    LLMCallContext,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    build_provider,
    generate_structured,
)
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import (
    matter_is_operational,
    require_operational_matter,
)
from caseops_api.services.next_hearing import apply_next_hearing_update
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
    redact_provider_error,
)
from caseops_api.services.session_context import SessionContext

_MAX_BODY_LENGTH = 500
_RED_PROVIDER_RESPONSE_CLASSES = {
    "authentication",
    "parse_error",
    "provider_error",
    "rate_limit",
    "timeout",
}
_TENANT_METADATA_BLOCKLIST = (
    "secret",
    "token",
    "signature",
    "raw",
    "payload",
    "url",
    "pdf",
    "authorization",
)


class CaseUpdateSummaryPayload(BaseModel):
    concise_summary: str = Field(min_length=1, max_length=1200)
    procedural_impact: str = Field(min_length=1, max_length=1200)
    next_hearing_or_action_signals: list[str] = Field(default_factory=list, max_length=8)
    risks_or_unknowns: list[str] = Field(default_factory=list, max_length=8)
    source_reference: str | None = None
    confidence: str = "low"
    summary_source: str = Field(default="caseops", max_length=40)
    review_framing: str = "Source-backed case update summary for lawyer review."


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CaseTrackingWindowState:
    timezone: str
    window_start: str
    window_end: str
    local_now: datetime
    inside_window: bool
    seconds_until_end: int

    def metadata(self) -> dict[str, object]:
        return {
            "timezone": self.timezone,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "local_now": self.local_now.isoformat(),
            "inside_window": self.inside_window,
            "seconds_until_end": self.seconds_until_end,
        }


@dataclass(frozen=True, slots=True)
class BookmarkMutationResult:
    bookmark: TrackedCaseBookmark
    tracked_case: TrackedCase
    created: bool


@dataclass(frozen=True, slots=True)
class MatterCaseTrackingAutoLinkResult:
    status: str
    reason: str | None = None
    bookmark_id: str | None = None
    tracked_case_id: str | None = None

    def metadata(self) -> dict[str, object]:
        data: dict[str, object] = {"status": self.status}
        if self.reason:
            data["reason"] = self.reason
        if self.bookmark_id:
            data["bookmark_id_sha256"] = _hash_value(self.bookmark_id)
        if self.tracked_case_id:
            data["tracked_case_id_sha256"] = _hash_value(self.tracked_case_id)
        return data


def _parse_window_time(value: str, *, field: str) -> datetime_time:
    try:
        hour, minute = value.split(":", 1)
        return datetime_time(hour=int(hour), minute=int(minute))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must use HH:MM 24-hour format.") from exc


def case_tracking_window_state(now: datetime | None = None) -> CaseTrackingWindowState:
    settings = get_settings()
    start = _parse_window_time(
        settings.case_tracking_daily_window_start,
        field="CASEOPS_CASE_TRACKING_DAILY_WINDOW_START",
    )
    end = _parse_window_time(
        settings.case_tracking_daily_window_end,
        field="CASEOPS_CASE_TRACKING_DAILY_WINDOW_END",
    )
    if start >= end:
        raise ValueError("Case tracking daily window start must be before end.")
    try:
        timezone = ZoneInfo(settings.case_tracking_daily_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            "CASEOPS_CASE_TRACKING_DAILY_TIMEZONE must be a valid IANA timezone.",
        ) from exc
    local_now = (now or _now()).astimezone(timezone)
    inside = start <= local_now.time() < end
    end_at = local_now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    seconds_until_end = max(0, int((end_at - local_now).total_seconds()))
    return CaseTrackingWindowState(
        timezone=settings.case_tracking_daily_timezone,
        window_start=settings.case_tracking_daily_window_start,
        window_end=settings.case_tracking_daily_window_end,
        local_now=local_now,
        inside_window=inside,
        seconds_until_end=seconds_until_end,
    )


def should_enforce_case_tracking_window(*, force: bool = False) -> bool:
    if force:
        return False
    return is_non_local_env(get_settings().env)


def _hash_value(value: object) -> str:
    blob = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _next_refresh_at(now: datetime | None = None) -> datetime:
    """Return the next configured window start without requiring elapsed-day proof."""
    state = case_tracking_window_state(now)
    settings = get_settings()
    start = _parse_window_time(
        settings.case_tracking_daily_window_start,
        field="CASEOPS_CASE_TRACKING_DAILY_WINDOW_START",
    )
    local_target = state.local_now.replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    if local_target <= state.local_now:
        local_target += timedelta(days=1)
    return local_target.astimezone(UTC)


def _response_class(exc: BaseException) -> str:
    value = f"{type(exc).__name__} {exc}".lower()
    if "timeout" in value:
        return "timeout"
    if any(token in value for token in ("401", "403", "auth", "token", "credential")):
        return "authentication"
    if any(token in value for token in ("429", "rate", "quota")):
        return "rate_limit"
    if any(token in value for token in ("parse", "schema", "malformed", "decode")):
        return "parse_error"
    return "provider_error"


def _manual_refresh_cost(session: Session, tracked_case: TrackedCase) -> tuple[int, str]:
    from caseops_api.services.production_safety import support_matrix_match

    row = support_matrix_match(
        session,
        provider=tracked_case.provider,
        court_code=tracked_case.court_code,
        court_name=tracked_case.court_name,
    )
    if row is not None:
        return int(row.refresh_cost_minor), row.currency
    from caseops_api.services.provider_costs import effective_cost_minor

    amount, _ = effective_cost_minor(
        session,
        category="case_refresh",
        provider=tracked_case.provider,
    )
    return amount, "INR"


def _new_operation(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    operation_type: str,
    poll_run_id: str | None = None,
) -> TrackedCaseProviderOperation:
    automatic_retry: TrackedCaseProviderOperation | None = None
    if operation_type == "scheduled":
        queued = session.scalar(
            select(TrackedCaseProviderOperation)
            .where(
                TrackedCaseProviderOperation.company_id == context.company.id,
                TrackedCaseProviderOperation.tracked_case_id == tracked_case.id,
                TrackedCaseProviderOperation.status == "pending",
                or_(
                    TrackedCaseProviderOperation.next_attempt_at.is_(None),
                    TrackedCaseProviderOperation.next_attempt_at <= _now(),
                ),
            )
            .order_by(TrackedCaseProviderOperation.created_at.asc())
            .limit(1)
        )
        if queued is not None:
            queued.status = "running"
            queued.operation_type = "replay"
            queued.poll_run_id = poll_run_id
            queued.started_at = _now()
            queued.completed_at = None
            queued.next_attempt_at = None
            queued.attempts += 1
            session.add(queued)
            session.flush()
            tracked_case.last_provider_attempted_at = queued.started_at
            tracked_case.last_operation_id = queued.id
            tracked_case.next_provider_refresh_at = _next_refresh_at(queued.started_at)
            session.add(tracked_case)
            return queued
        automatic_retry = session.scalar(
            select(TrackedCaseProviderOperation)
            .where(
                TrackedCaseProviderOperation.company_id == context.company.id,
                TrackedCaseProviderOperation.tracked_case_id == tracked_case.id,
                TrackedCaseProviderOperation.status == "failed",
                TrackedCaseProviderOperation.next_attempt_at.is_not(None),
                TrackedCaseProviderOperation.next_attempt_at <= _now(),
                TrackedCaseProviderOperation.attempts
                < TrackedCaseProviderOperation.max_attempts,
            )
            .order_by(TrackedCaseProviderOperation.created_at.desc())
            .limit(1)
        )
    cost_minor, currency = _manual_refresh_cost(session, tracked_case)
    operation = TrackedCaseProviderOperation(
        company_id=context.company.id,
        tracked_case_id=tracked_case.id,
        poll_run_id=poll_run_id,
        requested_by_membership_id=(
            context.membership.id if operation_type in {"manual", "replay", "canary"} else None
        ),
        provider=tracked_case.provider,
        operation_type="retry" if automatic_retry is not None else operation_type,
        correlation_id=uuid4().hex,
        status="running",
        attempts=(automatic_retry.attempts + 1 if automatic_retry is not None else 1),
        max_attempts=(automatic_retry.max_attempts if automatic_retry is not None else 3),
        cost_minor=cost_minor,
        currency=currency,
        started_at=_now(),
        metadata_json={
            "scope": "single_tracked_case",
            "cost_disclosed": True,
            **(
                {"retry_of_operation_id": automatic_retry.id}
                if automatic_retry is not None
                else {}
            ),
        },
    )
    session.add(operation)
    session.flush()
    if automatic_retry is not None:
        automatic_retry.next_attempt_at = None
        automatic_retry.metadata_json = {
            **dict(automatic_retry.metadata_json or {}),
            "automatic_retry_operation_id": operation.id,
        }
        session.add(automatic_retry)
    attempted_at = operation.started_at or _now()
    tracked_case.last_provider_attempted_at = attempted_at
    tracked_case.last_operation_id = operation.id
    tracked_case.next_provider_refresh_at = _next_refresh_at(attempted_at)
    tracked_case.provider_freshness_status = (
        "stale" if tracked_case.last_provider_successful_at else "never_succeeded"
    )
    session.add(tracked_case)
    return operation


def _snapshot_payload(snapshot: ProviderCaseSnapshot) -> dict[str, object]:
    payload = asdict(snapshot)
    payload["metadata"] = _tenant_safe_metadata(snapshot.metadata)
    for collection in ("orders", "judgments", "hearings"):
        for event in payload.get(collection, []):
            if isinstance(event, dict) and isinstance(event.get("metadata"), dict):
                event["metadata"] = _tenant_safe_metadata(event["metadata"])
    return json.loads(json.dumps(payload, default=str))


def _record_operation_snapshot(
    session: Session,
    *,
    tracked_case: TrackedCase,
    operation: TrackedCaseProviderOperation,
    snapshot: ProviderCaseSnapshot,
) -> None:
    raw = _snapshot_payload(snapshot)
    normalized = {
        "cnr_number": normalize_cnr(snapshot.cnr_number),
        "case_number": normalize_case_number(snapshot.case_number),
        "court_code": _normalize_court_code(snapshot.court_code),
        "court_name": snapshot.court_name,
        "case_title": snapshot.case_title,
        "current_status": snapshot.current_status,
        "current_stage": snapshot.current_stage,
        "next_hearing_on": snapshot.next_hearing_on.isoformat()
        if snapshot.next_hearing_on
        else None,
        "orders": [event.source_record_key for event in snapshot.orders],
        "judgments": [event.source_record_key for event in snapshot.judgments],
    }
    previous = {
        "current_status": tracked_case.current_status,
        "current_stage": tracked_case.current_stage,
        "next_hearing_on": tracked_case.next_hearing_on.isoformat()
        if tracked_case.next_hearing_on
        else None,
        "snapshot_hash": tracked_case.last_snapshot_hash,
    }
    current_hash = _hash_value(normalized)
    session.add(
        TrackedCaseProviderSnapshot(
            company_id=tracked_case.company_id,
            tracked_case_id=tracked_case.id,
            operation_id=operation.id,
            raw_hash=_hash_value(raw),
            normalized_hash=current_hash,
            raw_json=raw,
            normalized_json=normalized,
            diff_json={
                "previous": previous,
                "changed_fields": sorted(
                    key
                    for key in ("current_status", "current_stage", "next_hearing_on")
                    if previous.get(key) != normalized.get(key)
                ),
            },
            source_url=snapshot.source_url,
        )
    )


def _complete_operation(
    session: Session,
    *,
    tracked_case: TrackedCase,
    operation: TrackedCaseProviderOperation,
    created_update_count: int,
) -> None:
    completed_at = _now()
    response_class = "success" if created_update_count else "no_change"
    operation.status = "succeeded" if created_update_count else "no_change"
    operation.response_class = response_class
    operation.error_redacted = None
    operation.completed_at = completed_at
    operation.next_attempt_at = None
    tracked_case.last_provider_successful_at = completed_at
    tracked_case.last_provider_checked_at = completed_at
    tracked_case.last_response_class = response_class
    tracked_case.last_error = None
    tracked_case.provider_freshness_status = "fresh"
    tracked_case.quarantined_at = None
    tracked_case.quarantine_reason_redacted = None
    session.add_all([operation, tracked_case])


def _fail_operation(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    operation: TrackedCaseProviderOperation,
    exc: BaseException,
) -> None:
    error = redact_provider_error(exc)
    response_class = _response_class(exc)
    operation.status = "failed"
    operation.response_class = response_class
    operation.error_redacted = error
    operation.completed_at = _now()
    exhausted = operation.attempts >= operation.max_attempts
    operation.status = "quarantined" if exhausted else "failed"
    operation.next_attempt_at = (
        None if exhausted else operation.completed_at + timedelta(minutes=15)
    )
    tracked_case.last_error = error
    tracked_case.last_response_class = response_class
    tracked_case.next_provider_refresh_at = operation.next_attempt_at
    if exhausted:
        tracked_case.quarantined_at = operation.completed_at
        tracked_case.quarantine_reason_redacted = error
        operation.quarantined_at = operation.completed_at
        operation.quarantine_reason_redacted = error
        tracked_case.provider_freshness_status = "blocked"
    else:
        tracked_case.provider_freshness_status = (
            "stale" if tracked_case.last_provider_successful_at else "never_succeeded"
        )
    session.add_all([operation, tracked_case])
    admins = list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.is_active.is_(True),
                CompanyMembership.role.in_(("owner", "admin")),
            )
        )
    )
    for membership in admins:
        enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=membership,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type="case_tracking.provider_unhealthy",
            source_type="tracked_case_provider_operation",
            source_id=operation.id,
            title="Case tracking provider needs attention",
            body=(
                f"{operation.provider} returned {response_class}. "
                "Review the correlated provider operation before replay."
            ),
        )


def normalize_cnr(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return normalized or None


def normalize_case_number(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"\s+", " ", value).strip().upper()
    return normalized or None


def _normalize_court_code(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"\s+", "", value).strip().upper()
    return normalized or None


def _tracked_case_identity_key(
    *,
    cnr_number: str | None,
    case_number: str | None,
    court_code: str | None,
) -> str:
    normalized_cnr = normalize_cnr(cnr_number)
    if normalized_cnr:
        return f"cnr:{normalized_cnr}"
    normalized_case = normalize_case_number(case_number) or "UNKNOWN"
    normalized_court = _normalize_court_code(court_code) or "UNKNOWN"
    return f"case:{normalized_case}|court:{normalized_court}"


def _bookmark_scope_key(matter: Matter | None) -> str:
    return matter.id if matter else "company"


def provider_status_response() -> CaseTrackingProviderStatusResponse:
    enabled, provider, configured, reason = provider_status()
    return CaseTrackingProviderStatusResponse(
        enabled=enabled,
        provider=provider,
        configured=configured,
        reason=reason,
    )


def _safe_provider_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, CaseTrackingProviderUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=redact_provider_error(exc),
    )


def _snapshot_hash(snapshot: ProviderCaseSnapshot) -> str:
    return _hash_value(
        {
            "cnr_number": normalize_cnr(snapshot.cnr_number),
            "case_number": normalize_case_number(snapshot.case_number),
            "court_code": snapshot.court_code,
            "status": snapshot.current_status,
            "stage": snapshot.current_stage,
            "next_hearing_on": snapshot.next_hearing_on,
            "orders": [event.source_record_key for event in snapshot.orders],
            "judgments": [event.source_record_key for event in snapshot.judgments],
        }
    )


def _event_hash(event: ProviderCaseEvent) -> str:
    return _hash_value(
        {
            "key": event.source_record_key,
            "title": event.title,
            "event_date": event.event_date,
            "source_url": event.source_url,
            "summary": event.provider_summary,
        }
    )


def _search_record(snapshot: ProviderCaseSnapshot) -> CaseTrackingSearchResultRecord:
    return CaseTrackingSearchResultRecord(
        provider=snapshot.provider,
        cnr_number=normalize_cnr(snapshot.cnr_number),
        case_number=snapshot.case_number,
        court_code=snapshot.court_code,
        court_name=snapshot.court_name,
        case_title=snapshot.case_title,
        party_names=snapshot.party_names,
        current_status=snapshot.current_status,
        current_stage=snapshot.current_stage,
        next_hearing_on=snapshot.next_hearing_on,
        # Source documents/case links can require provider bearer auth. Tenant
        # browsers must use CaseOps-controlled routes, not provider URLs.
        source_url=None,
    )


def search_cases(
    session: Session,
    *,
    context: SessionContext,
    payload: CaseTrackingSearchRequest,
    provider: CaseTrackingProvider | None = None,
) -> CaseTrackingSearchResponse:
    query = CaseSearchQuery(
        query=payload.query,
        cnr_number=normalize_cnr(payload.cnr_number),
        case_number=payload.case_number,
        court_code=payload.court_code,
        state=payload.state,
        court_name=payload.court_name,
    )
    try:
        active_provider = provider or get_case_tracking_provider()
        from caseops_api.services.production_safety import assert_case_tracking_supported

        assert_case_tracking_supported(
            session,
            provider=active_provider.provider_key,
            court_code=payload.court_code,
            court_name=payload.court_name,
        )
        snapshots = active_provider.search_cases(query=query)
    except (CaseTrackingProviderUnavailable, CaseTrackingProviderError) as exc:
        raise _safe_provider_error(exc) from exc
    record_from_context(
        session,
        context,
        action="case_tracking.search",
        target_type="case_tracking_provider",
        target_id=active_provider.provider_key,
        metadata={
            "provider": active_provider.provider_key,
            "has_general_query": bool(query.query),
            "has_cnr": bool(query.cnr_number),
            "has_case_number": bool(query.case_number),
            "has_court_filter": bool(query.court_code or query.state or query.court_name),
            "result_count": len(snapshots),
        },
    )
    session.commit()
    return CaseTrackingSearchResponse(
        provider=active_provider.provider_key,
        results=[_search_record(snapshot) for snapshot in snapshots],
    )


def _matter_or_none(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
) -> Matter | None:
    if matter_id is None:
        return None
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


def _tracked_case_record(session: Session, case: TrackedCase) -> TrackedCaseRecord:
    enabled, _provider, configured, provider_reason = provider_status()
    cost_minor, currency = _manual_refresh_cost(session, case)
    freshness = case.provider_freshness_status or "never_succeeded"
    last_success = case.last_provider_successful_at or case.last_provider_checked_at
    if last_success is not None:
        aware = last_success if last_success.tzinfo else last_success.replace(tzinfo=UTC)
        freshness = "fresh" if (_now() - aware) <= timedelta(hours=24) else "stale"
    if case.quarantined_at is not None:
        freshness = "quarantined"
    elif not enabled or not configured:
        freshness = "disabled"
    provider_health_red = case.last_response_class in _RED_PROVIDER_RESPONSE_CLASSES
    manual_allowed = bool(
        enabled and configured and case.quarantined_at is None and not provider_health_red
    )
    disabled_reason = None
    if case.quarantined_at is not None:
        disabled_reason = "Provider work is quarantined; an administrator must review it."
    elif provider_health_red:
        disabled_reason = (
            "Provider health is red after the latest failed operation; "
            "an administrator must review or replay it."
        )
    elif not enabled or not configured:
        disabled_reason = provider_reason or "Case tracking provider health is red."
    return TrackedCaseRecord(
        id=case.id,
        provider=case.provider,
        cnr_number=case.cnr_number,
        case_number=case.case_number,
        court_code=case.court_code,
        court_name=case.court_name,
        case_title=case.case_title,
        party_names=list(case.party_names_json or []),
        current_status=case.current_status,
        current_stage=case.current_stage,
        next_hearing_on=case.next_hearing_on,
        last_provider_checked_at=case.last_provider_checked_at,
        last_provider_attempted_at=case.last_provider_attempted_at,
        last_provider_successful_at=last_success,
        next_provider_refresh_at=case.next_provider_refresh_at,
        freshness_status=freshness,
        response_class=case.last_response_class,
        last_operation_id=case.last_operation_id,
        provider_health=(
            "quarantined"
            if case.quarantined_at is not None
            else "disabled"
            if not enabled or not configured
            else "unhealthy"
            if provider_health_red
            else "healthy"
            if freshness == "fresh"
            else "degraded"
        ),
        manual_refresh_allowed=manual_allowed,
        manual_refresh_disabled_reason=disabled_reason,
        refresh_cost_minor=cost_minor,
        refresh_currency=currency,
        last_error=case.last_error,
        metadata=_tenant_safe_metadata(case.metadata_json or {}),
    )


def _bookmark_record(session: Session, bookmark: TrackedCaseBookmark) -> CaseTrackingBookmarkRecord:
    update_count = session.scalar(
        select(func.count()).where(
            TrackedCaseUpdate.company_id == bookmark.company_id,
            TrackedCaseUpdate.tracked_case_id == bookmark.tracked_case_id,
        )
    )
    return CaseTrackingBookmarkRecord(
        id=bookmark.id,
        company_id=bookmark.company_id,
        tracked_case_id=bookmark.tracked_case_id,
        created_by_membership_id=bookmark.created_by_membership_id,
        matter_id=bookmark.matter_id,
        name=bookmark.name,
        notification_enabled=bookmark.notification_enabled,
        is_archived=bookmark.is_archived,
        created_at=bookmark.created_at,
        updated_at=bookmark.updated_at,
        archived_at=bookmark.archived_at,
        tracked_case=_tracked_case_record(session, bookmark.tracked_case),
        update_count=int(update_count or 0),
    )


def _find_tracked_case(
    session: Session,
    *,
    company_id: str,
    provider: str,
    cnr_number: str | None,
    case_number: str | None,
    court_code: str | None,
) -> TrackedCase | None:
    statement = select(TrackedCase).where(
        TrackedCase.company_id == company_id,
        TrackedCase.provider == provider,
        TrackedCase.identity_key
        == _tracked_case_identity_key(
            cnr_number=cnr_number,
            case_number=case_number,
            court_code=court_code,
        ),
    )
    return session.scalar(statement)


def _create_or_get_bookmark(
    session: Session,
    *,
    context: SessionContext,
    payload: CaseTrackingBookmarkCreateRequest,
    matter: Matter | None,
) -> BookmarkMutationResult:
    if matter is not None:
        matter = require_operational_matter(
            session,
            matter=matter,
            operation="link case tracking",
        )
    normalized_cnr = normalize_cnr(payload.cnr_number)
    normalized_case = normalize_case_number(payload.case_number)
    normalized_court = _normalize_court_code(payload.court_code)
    identity_key = _tracked_case_identity_key(
        cnr_number=payload.cnr_number,
        case_number=payload.case_number,
        court_code=payload.court_code,
    )
    tracked_case = _find_tracked_case(
        session,
        company_id=context.company.id,
        provider=payload.provider,
        cnr_number=payload.cnr_number,
        case_number=payload.case_number,
        court_code=payload.court_code,
    )
    scope_key = _bookmark_scope_key(matter)
    if tracked_case is not None:
        existing = session.scalar(
            select(TrackedCaseBookmark).where(
                TrackedCaseBookmark.company_id == context.company.id,
                TrackedCaseBookmark.tracked_case_id == tracked_case.id,
                TrackedCaseBookmark.created_by_membership_id == context.membership.id,
                TrackedCaseBookmark.active_scope_key == scope_key,
            )
        )
        if existing is not None:
            return BookmarkMutationResult(
                bookmark=existing,
                tracked_case=tracked_case,
                created=False,
            )

    from caseops_api.services.saas_billing import assert_tracked_case_limit

    assert_tracked_case_limit(session, context=context)
    if tracked_case is None:
        tracked_case = TrackedCase(
            company_id=context.company.id,
            provider=payload.provider,
            identity_key=identity_key,
            cnr_number=normalized_cnr,
            normalized_cnr_number=normalized_cnr,
            case_number=payload.case_number,
            normalized_case_number=normalized_case,
            court_code=normalized_court,
            court_name=payload.court_name,
            case_title=payload.case_title,
            party_names_json=payload.party_names,
            current_status=payload.current_status,
            current_stage=payload.current_stage,
            next_hearing_on=payload.next_hearing_on,
            last_snapshot_hash=_hash_value(
                {
                    "status": payload.current_status,
                    "stage": payload.current_stage,
                    "next_hearing_on": payload.next_hearing_on,
                }
            ),
            metadata_json=payload.metadata,
        )
        session.add(tracked_case)
        session.flush()
    bookmark = TrackedCaseBookmark(
        company_id=context.company.id,
        tracked_case_id=tracked_case.id,
        created_by_membership_id=context.membership.id,
        matter_id=matter.id if matter else None,
        scope_key=scope_key,
        active_scope_key=scope_key,
        name=payload.name,
        notification_enabled=payload.notification_enabled,
    )
    session.add(bookmark)
    session.flush()
    return BookmarkMutationResult(bookmark=bookmark, tracked_case=tracked_case, created=True)


def _tenant_safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in metadata.items():
        lowered = key.lower()
        if any(blocked in lowered for blocked in _TENANT_METADATA_BLOCKLIST):
            continue
        safe_value = _tenant_safe_value(value)
        if safe_value is not _UNSAFE_METADATA_VALUE:
            safe[key] = safe_value
    return safe


_UNSAFE_METADATA_VALUE = object()


def _tenant_safe_value(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        cleaned = []
        for item in value[:20]:
            safe_item = _tenant_safe_value(item)
            if safe_item is not _UNSAFE_METADATA_VALUE:
                cleaned.append(safe_item)
        return cleaned
    if isinstance(value, dict):
        return _tenant_safe_metadata(value)
    return _UNSAFE_METADATA_VALUE


def _source_proxy_path(*, bookmark_id: str | None, update_id: str) -> str | None:
    if not bookmark_id:
        return None
    return f"/api/case-tracking/bookmarks/{bookmark_id}/updates/{update_id}/source"


def _safe_ai_summary(
    update: TrackedCaseUpdate,
    *,
    bookmark_id: str | None,
) -> dict[str, object] | None:
    if not update.ai_summary_json:
        return None
    summary = dict(update.ai_summary_json)
    if "source_reference" in summary:
        summary["source_reference"] = (
            _source_proxy_path(bookmark_id=bookmark_id, update_id=update.id)
            if update.source_url
            else None
        )
    return _tenant_safe_metadata(summary)


def create_bookmark(
    session: Session,
    *,
    context: SessionContext,
    payload: CaseTrackingBookmarkCreateRequest,
) -> CaseTrackingBookmarkRecord:
    from caseops_api.services.production_safety import assert_case_tracking_supported

    assert_case_tracking_supported(
        session,
        provider=payload.provider,
        court_code=payload.court_code,
        court_name=payload.court_name,
    )
    matter = _matter_or_none(session, context=context, matter_id=payload.matter_id)
    mutation = _create_or_get_bookmark(
        session,
        context=context,
        payload=payload,
        matter=matter,
    )
    bookmark = mutation.bookmark
    tracked_case = mutation.tracked_case
    if not mutation.created:
        return _bookmark_record(session, bookmark)
    record_from_context(
        session,
        context,
        action="case_tracking.bookmark_created",
        target_type="tracked_case_bookmark",
        target_id=bookmark.id,
        matter_id=bookmark.matter_id,
        metadata={
            "tracked_case_id_sha256": _hash_value(tracked_case.id),
            "provider": tracked_case.provider,
            "has_cnr": bool(tracked_case.cnr_number),
            "has_case_number": bool(tracked_case.case_number),
            "notification_enabled": bookmark.notification_enabled,
        },
    )
    session.commit()
    session.refresh(bookmark)
    return _bookmark_record(session, bookmark)


def auto_link_matter_case_tracking(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
) -> MatterCaseTrackingAutoLinkResult:
    if str(matter.status) in {"closed", "disposed"} or not matter.is_active:
        return MatterCaseTrackingAutoLinkResult(
            status="skipped",
            reason="matter_disposed",
        )
    enabled, provider, configured, reason = provider_status()
    if not enabled:
        return MatterCaseTrackingAutoLinkResult(
            status="skipped",
            reason="case_tracking_disabled",
        )
    if not configured or provider != "ecourtsindia":
        return MatterCaseTrackingAutoLinkResult(
            status="skipped",
            reason=reason or "case_tracking_provider_unconfigured",
        )

    normalized_cnr = normalize_cnr(matter.cnr_number)
    cnr_number = matter.cnr_number if normalized_cnr and len(normalized_cnr) >= 8 else None
    case_number = matter.case_number if normalize_case_number(matter.case_number) else None
    if not cnr_number and not case_number:
        return MatterCaseTrackingAutoLinkResult(
            status="skipped",
            reason="missing_case_identity",
        )

    party_names = [
        value for value in [matter.client_name, matter.opposing_party] if value and value.strip()
    ]
    payload = CaseTrackingBookmarkCreateRequest(
        provider=provider,
        cnr_number=cnr_number,
        case_number=case_number,
        court_name=matter.court_name,
        case_title=matter.title,
        party_names=party_names,
        next_hearing_on=matter.next_hearing_on,
        matter_id=matter.id,
        name=matter.matter_code,
        notification_enabled=True,
        metadata={
            "source": "matter_create_auto_link",
            "matter_code": matter.matter_code,
        },
    )
    try:
        from caseops_api.services.production_safety import assert_case_tracking_supported

        assert_case_tracking_supported(
            session,
            provider=payload.provider,
            court_code=payload.court_code,
            court_name=payload.court_name,
        )
        mutation = _create_or_get_bookmark(
            session,
            context=context,
            payload=payload,
            matter=matter,
        )
    except HTTPException as exc:
        return MatterCaseTrackingAutoLinkResult(
            status="blocked",
            reason=str(exc.detail),
        )

    if mutation.created:
        record_from_context(
            session,
            context,
            action="case_tracking.bookmark_created",
            target_type="tracked_case_bookmark",
            target_id=mutation.bookmark.id,
            matter_id=mutation.bookmark.matter_id,
            metadata={
                "tracked_case_id_sha256": _hash_value(mutation.tracked_case.id),
                "provider": mutation.tracked_case.provider,
                "has_cnr": bool(mutation.tracked_case.cnr_number),
                "has_case_number": bool(mutation.tracked_case.case_number),
                "notification_enabled": mutation.bookmark.notification_enabled,
                "origin": "matter_create_auto_link",
            },
        )
    return MatterCaseTrackingAutoLinkResult(
        status="linked" if mutation.created else "already_linked",
        bookmark_id=mutation.bookmark.id,
        tracked_case_id=mutation.tracked_case.id,
    )


def _get_bookmark(
    session: Session,
    *,
    context: SessionContext,
    bookmark_id: str,
) -> TrackedCaseBookmark:
    bookmark = session.scalar(
        select(TrackedCaseBookmark)
        .options(joinedload(TrackedCaseBookmark.tracked_case))
        .where(
            TrackedCaseBookmark.id == bookmark_id,
            TrackedCaseBookmark.company_id == context.company.id,
            TrackedCaseBookmark.created_by_membership_id == context.membership.id,
        )
    )
    if bookmark is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case tracking bookmark not found.",
        )
    if bookmark.matter_id:
        _matter_or_none(session, context=context, matter_id=bookmark.matter_id)
    return bookmark


def list_bookmarks(
    session: Session,
    *,
    context: SessionContext,
) -> CaseTrackingBookmarkListResponse:
    rows = list(
        session.scalars(
            select(TrackedCaseBookmark)
            .options(joinedload(TrackedCaseBookmark.tracked_case))
            .where(
                TrackedCaseBookmark.company_id == context.company.id,
                TrackedCaseBookmark.created_by_membership_id == context.membership.id,
                TrackedCaseBookmark.is_archived.is_(False),
            )
            .order_by(TrackedCaseBookmark.updated_at.desc())
        )
    )
    return CaseTrackingBookmarkListResponse(
        bookmarks=[_bookmark_record(session, row) for row in rows]
    )


def update_bookmark(
    session: Session,
    *,
    context: SessionContext,
    bookmark_id: str,
    payload: CaseTrackingBookmarkUpdateRequest,
) -> CaseTrackingBookmarkRecord:
    bookmark = _get_bookmark(session, context=context, bookmark_id=bookmark_id)
    fields = payload.model_fields_set
    if "name" in fields:
        bookmark.name = payload.name
    if "notification_enabled" in fields and payload.notification_enabled is not None:
        bookmark.notification_enabled = payload.notification_enabled
    if "is_archived" in fields and payload.is_archived is not None:
        if payload.is_archived:
            bookmark.is_archived = True
            bookmark.active_scope_key = None
            bookmark.archived_at = _now()
        else:
            existing = session.scalar(
                select(TrackedCaseBookmark).where(
                    TrackedCaseBookmark.company_id == context.company.id,
                    TrackedCaseBookmark.tracked_case_id == bookmark.tracked_case_id,
                    TrackedCaseBookmark.created_by_membership_id
                    == bookmark.created_by_membership_id,
                    TrackedCaseBookmark.active_scope_key == bookmark.scope_key,
                    TrackedCaseBookmark.id != bookmark.id,
                )
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An active bookmark already exists for this case scope.",
                )
            bookmark.is_archived = False
            bookmark.active_scope_key = bookmark.scope_key
            bookmark.archived_at = None
    session.add(bookmark)
    record_from_context(
        session,
        context,
        action="case_tracking.bookmark_updated",
        target_type="tracked_case_bookmark",
        target_id=bookmark.id,
        matter_id=bookmark.matter_id,
        metadata={
            "updated_field_count": len(fields),
            "is_archived": bookmark.is_archived,
            "notification_enabled": bookmark.notification_enabled,
        },
    )
    session.commit()
    return _bookmark_record(session, bookmark)


def _summary_for_update(
    session: Session,
    *,
    tracked_case: TrackedCase,
    update_type: str,
    event: ProviderCaseEvent | None,
    title: str,
    provider: LLMProvider | None = None,
) -> tuple[str | None, dict[str, object] | None, str | None]:
    source_text = event.text if event else None
    provider_summary_terms_permitted = bool(
        event and event.provider_summary and event.metadata.get("summary_terms_permitted") is True
    )
    provider_summary = (
        event.provider_summary if event and provider_summary_terms_permitted else None
    )
    source_url = event.source_url if event else None
    fallback = {
        "concise_summary": provider_summary
        or f"Source-backed case update detected for {tracked_case.case_title}: {title}.",
        "procedural_impact": "Review the provider source before relying on this update.",
        "next_hearing_or_action_signals": [],
        "risks_or_unknowns": ["Provider data may be incomplete or delayed."],
        "source_reference": source_url,
        "confidence": "medium" if provider_summary or source_text else "low",
        "summary_source": "provider" if provider_summary and not source_text else "caseops",
        "review_framing": "Source-backed case update summary for lawyer review.",
    }
    if not source_text and not provider_summary:
        return str(fallback["concise_summary"]), fallback, None
    messages = [
        LLMMessage(
            role="system",
            content=(
                "Produce a source-backed case update summary for lawyer review. "
                "Do not infer outcomes beyond the order or judgment text."
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                "Respond with json matching this schema: "
                '{"concise_summary": str, "procedural_impact": str, '
                '"next_hearing_or_action_signals": [str], '
                '"risks_or_unknowns": [str], "source_reference": str|null, '
                '"confidence": "low|medium|high", "summary_source": str, '
                '"review_framing": str}.\n'
                f"CASE_TITLE: {tracked_case.case_title}\n"
                f"UPDATE_TYPE: {update_type}\n"
                f"TITLE: {title}\n"
                f"SOURCE_URL: {source_url}\n"
                f"PROVIDER_SUMMARY: {provider_summary}\n"
                f"TEXT: {(source_text or '')[:4000]}"
            ),
        ),
    ]
    llm = provider or build_provider(purpose="case_tracking:update_summary")
    prompt_hash = hashlib.sha256(
        "\n".join(f"{message.role}:{message.content}" for message in messages).encode("utf-8")
    ).hexdigest()
    try:
        payload, completion = generate_structured(
            llm,
            session=session,
            schema=CaseUpdateSummaryPayload,
            messages=messages,
            context=LLMCallContext(purpose="case_tracking:update_summary"),
            temperature=get_settings().llm_temperature,
            max_tokens=1200,
        )
    except LLMProviderError:
        return str(fallback["concise_summary"]), fallback, None
    model_run = ModelRun(
        company_id=tracked_case.company_id,
        matter_id=None,
        actor_membership_id=None,
        purpose="case_tracking:update_summary",
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
    summary = payload.model_dump()
    return summary["concise_summary"], summary, model_run.id


def _update_record(
    update: TrackedCaseUpdate,
    *,
    bookmark_id: str | None = None,
) -> CaseTrackingUpdateRecord:
    return CaseTrackingUpdateRecord(
        id=update.id,
        company_id=update.company_id,
        tracked_case_id=update.tracked_case_id,
        update_type=update.update_type,  # type: ignore[arg-type]
        source_record_key=update.source_record_key,
        title=update.title,
        summary=update.summary,
        ai_summary=_safe_ai_summary(update, bookmark_id=bookmark_id),
        source_url=_source_proxy_path(bookmark_id=bookmark_id, update_id=update.id)
        if update.source_url
        else None,
        order_date=update.order_date,
        hearing_date=update.hearing_date,
        provider_metadata=_tenant_safe_metadata(update.provider_metadata_json or {}),
        created_at=update.created_at,
    )


def _notification_event_type(update_type: str) -> str:
    return {
        "new_order": "case_tracking.new_order",
        "new_judgment": "case_tracking.new_judgment",
        "hearing_update": "case_tracking.hearing_updated",
        "status_change": "case_tracking.status_changed",
        "case_metadata_change": "case_tracking.status_changed",
    }.get(update_type, "case_tracking.status_changed")


def _notification_title(update: TrackedCaseUpdate, tracked_case: TrackedCase) -> str:
    if update.update_type == "new_order":
        return f"New order detected for {tracked_case.case_title}"[:255]
    if update.update_type == "new_judgment":
        return f"New judgment detected for {tracked_case.case_title}"[:255]
    if update.update_type == "hearing_update":
        return f"Next hearing changed for {tracked_case.case_title}"[:255]
    return f"Case status updated for {tracked_case.case_title}"[:255]


def _notification_body(update: TrackedCaseUpdate, tracked_case: TrackedCase) -> str:
    parts = [
        update.summary or update.title,
        tracked_case.court_name,
        "Open the source from the CaseOps case-tracking update. In-app only.",
    ]
    text = " ".join(part for part in parts if part)
    return text[: _MAX_BODY_LENGTH - 3].rstrip() + "..." if len(text) > _MAX_BODY_LENGTH else text


def _notify_bookmark_users(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    update: TrackedCaseUpdate,
) -> int:
    bookmarks = list(
        session.scalars(
            select(TrackedCaseBookmark)
            .options(
                joinedload(TrackedCaseBookmark.created_by_membership),
                joinedload(TrackedCaseBookmark.matter),
            )
            .where(
                TrackedCaseBookmark.company_id == tracked_case.company_id,
                TrackedCaseBookmark.tracked_case_id == tracked_case.id,
                TrackedCaseBookmark.is_archived.is_(False),
                TrackedCaseBookmark.notification_enabled.is_(True),
            )
        )
    )
    count = 0
    for bookmark in bookmarks:
        if bookmark.matter is not None and (
            str(bookmark.matter.status) in {"closed", "disposed"} or not bookmark.matter.is_active
        ):
            continue
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=bookmark.created_by_membership,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type=_notification_event_type(update.update_type),
            source_type="tracked_case_update",
            source_id=update.id,
            matter=bookmark.matter,
            title=_notification_title(update, tracked_case),
            body=_notification_body(update, tracked_case),
        )
        if intent is not None:
            count += 1
            record_from_context(
                session,
                context,
                action="case_tracking.notification_enqueued",
                target_type="notification_delivery_intent",
                target_id=intent.id,
                matter_id=bookmark.matter_id,
                metadata={
                    "tracked_case_id_sha256": _hash_value(tracked_case.id),
                    "tracked_case_update_id_sha256": _hash_value(update.id),
                    "recipient_membership_id_sha256": _hash_value(
                        bookmark.created_by_membership_id
                    ),
                    "event_type": _notification_event_type(update.update_type),
                },
            )
    return count


def _create_update(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    update_type: str,
    source_record_key: str,
    title: str,
    current_hash: str,
    previous_hash: str | None = None,
    event: ProviderCaseEvent | None = None,
    order_date=None,
    hearing_date=None,
    provider: LLMProvider | None = None,
) -> TrackedCaseUpdate | None:
    existing = session.scalar(
        select(TrackedCaseUpdate).where(
            TrackedCaseUpdate.tracked_case_id == tracked_case.id,
            TrackedCaseUpdate.source_record_key == source_record_key,
            TrackedCaseUpdate.update_type == update_type,
        )
    )
    if existing is not None:
        return None
    summary, ai_summary, model_run_id = _summary_for_update(
        session,
        tracked_case=tracked_case,
        update_type=update_type,
        event=event,
        title=title,
        provider=provider,
    )
    update = TrackedCaseUpdate(
        company_id=tracked_case.company_id,
        tracked_case_id=tracked_case.id,
        update_type=update_type,
        source_record_key=source_record_key,
        title=title,
        summary=summary,
        ai_summary_json=ai_summary,
        source_url=event.source_url if event else None,
        order_date=order_date,
        hearing_date=hearing_date,
        previous_hash=previous_hash,
        current_hash=current_hash,
        provider_metadata_json=event.metadata if event else {},
        model_run_id=model_run_id,
    )
    session.add(update)
    session.flush()
    record_from_context(
        session,
        context,
        action="case_tracking.update_detected",
        target_type="tracked_case_update",
        target_id=update.id,
        metadata={
            "tracked_case_id_sha256": _hash_value(tracked_case.id),
            "update_type": update_type,
            "source_record_key_sha256": _hash_value(source_record_key),
        },
    )
    _notify_bookmark_users(session, context=context, tracked_case=tracked_case, update=update)
    return update


def apply_snapshot(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    snapshot: ProviderCaseSnapshot,
    provider: LLMProvider | None = None,
) -> list[TrackedCaseUpdate]:
    active_bookmarks = [bookmark for bookmark in tracked_case.bookmarks if not bookmark.is_archived]
    linked_matter_ids = [bookmark.matter_id for bookmark in active_bookmarks if bookmark.matter_id]
    has_unlinked_bookmark = any(bookmark.matter_id is None for bookmark in active_bookmarks)
    locked_linked_matters: list[Matter] = []
    if linked_matter_ids:
        locked_linked_matters = list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == context.company.id,
                    Matter.id.in_(sorted(set(linked_matter_ids))),
                )
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            )
        )
    operational_linked_matters = [
        matter for matter in locked_linked_matters if matter_is_operational(matter)
    ]
    if linked_matter_ids and not has_unlinked_bookmark:
        if not operational_linked_matters:
            record_from_context(
                session,
                context,
                action="case_tracking.snapshot_ignored",
                target_type="tracked_case",
                target_id=tracked_case.id,
                result="denied",
                metadata={"reason": "all_linked_matters_disposed"},
            )
            return []

    created: list[TrackedCaseUpdate] = []
    for event in snapshot.orders:
        update = _create_update(
            session,
            context=context,
            tracked_case=tracked_case,
            update_type="new_order",
            source_record_key=event.source_record_key,
            title=event.title,
            current_hash=_event_hash(event),
            event=event,
            order_date=event.event_date,
            provider=provider,
        )
        if update:
            created.append(update)
    for event in snapshot.judgments:
        update = _create_update(
            session,
            context=context,
            tracked_case=tracked_case,
            update_type="new_judgment",
            source_record_key=event.source_record_key,
            title=event.title,
            current_hash=_event_hash(event),
            event=event,
            order_date=event.event_date,
            provider=provider,
        )
        if update:
            created.append(update)
    previous_status_hash = _hash_value(
        {
            "status": tracked_case.current_status,
            "stage": tracked_case.current_stage,
        }
    )
    current_status_hash = _hash_value(
        {
            "status": snapshot.current_status,
            "stage": snapshot.current_stage,
        }
    )
    if tracked_case.last_provider_checked_at and previous_status_hash != current_status_hash:
        update = _create_update(
            session,
            context=context,
            tracked_case=tracked_case,
            update_type="status_change",
            source_record_key=f"status:{current_status_hash}",
            title=f"Case status changed to {snapshot.current_status or snapshot.current_stage}",
            current_hash=current_status_hash,
            previous_hash=previous_status_hash,
            event=None,
        )
        if update:
            created.append(update)
    if (
        tracked_case.last_provider_checked_at
        and tracked_case.next_hearing_on != snapshot.next_hearing_on
    ):
        hearing_hash = _hash_value({"next_hearing_on": snapshot.next_hearing_on})
        update = _create_update(
            session,
            context=context,
            tracked_case=tracked_case,
            update_type="hearing_update",
            source_record_key=f"hearing:{hearing_hash}",
            title=f"Next hearing changed to {snapshot.next_hearing_on}",
            current_hash=hearing_hash,
            previous_hash=_hash_value({"next_hearing_on": tracked_case.next_hearing_on}),
            event=None,
            hearing_date=snapshot.next_hearing_on,
        )
        if update:
            created.append(update)
    tracked_case.cnr_number = normalize_cnr(snapshot.cnr_number) or tracked_case.cnr_number
    tracked_case.normalized_cnr_number = normalize_cnr(tracked_case.cnr_number)
    tracked_case.case_number = snapshot.case_number or tracked_case.case_number
    tracked_case.normalized_case_number = normalize_case_number(tracked_case.case_number)
    tracked_case.court_code = _normalize_court_code(snapshot.court_code) or tracked_case.court_code
    tracked_case.identity_key = _tracked_case_identity_key(
        cnr_number=tracked_case.cnr_number,
        case_number=tracked_case.case_number,
        court_code=tracked_case.court_code,
    )
    tracked_case.court_name = snapshot.court_name or tracked_case.court_name
    tracked_case.case_title = snapshot.case_title or tracked_case.case_title
    tracked_case.party_names_json = snapshot.party_names or tracked_case.party_names_json
    tracked_case.current_status = snapshot.current_status
    tracked_case.current_stage = snapshot.current_stage
    tracked_case.next_hearing_on = snapshot.next_hearing_on
    tracked_case.last_snapshot_hash = _snapshot_hash(snapshot)
    tracked_case.last_provider_checked_at = _now()
    tracked_case.last_error = None
    tracked_case.metadata_json = {
        **(tracked_case.metadata_json or {}),
        **snapshot.metadata,
        "source_url": snapshot.source_url,
    }
    session.add(tracked_case)
    if snapshot.next_hearing_on is not None:
        if operational_linked_matters:
            for matter in operational_linked_matters:
                apply_next_hearing_update(
                    session,
                    matter=matter,
                    new_date=snapshot.next_hearing_on,
                    source="case_tracking",
                    actor_membership_id=context.membership.id,
                    context=context,
                    source_ref_type="tracked_case",
                    source_ref_id=tracked_case.id,
                    reason="tracked_case_snapshot",
                    confidence_label="high",
                )
    session.flush()
    return created


def refresh_bookmark(
    session: Session,
    *,
    context: SessionContext,
    bookmark_id: str,
    provider: CaseTrackingProvider | None = None,
) -> CaseTrackingRefreshResponse:
    bookmark = _get_bookmark(session, context=context, bookmark_id=bookmark_id)
    tracked_case = bookmark.tracked_case
    if tracked_case.quarantined_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Case tracking provider work is quarantined pending administrator review.",
        )
    if tracked_case.last_response_class in _RED_PROVIDER_RESPONSE_CLASSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Case tracking provider health is red after the latest failed operation; "
                "an administrator must review or replay it."
            ),
        )
    if bookmark.matter_id:
        linked_matter = _matter_or_none(
            session,
            context=context,
            matter_id=bookmark.matter_id,
        )
        if linked_matter is not None and (
            str(linked_matter.status) in {"closed", "disposed"} or not linked_matter.is_active
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot refresh case tracking for a disposed matter.",
            )
    from caseops_api.services.saas_billing import assert_manual_refresh_limit

    assert_manual_refresh_limit(
        session,
        context=context,
        tracked_case_id=tracked_case.id,
    )
    tracked_case.last_provider_refresh_requested_at = _now()
    operation = _new_operation(
        session,
        context=context,
        tracked_case=tracked_case,
        operation_type="manual",
    )
    try:
        active_provider = provider or get_case_tracking_provider()
        from caseops_api.services.production_safety import assert_case_tracking_supported

        assert_case_tracking_supported(
            session,
            provider=active_provider.provider_key,
            court_code=tracked_case.court_code,
            court_name=tracked_case.court_name,
        )
        if tracked_case.cnr_number:
            snapshot = active_provider.get_case_by_cnr(cnr=tracked_case.cnr_number)
        else:
            results = active_provider.search_cases(
                query=CaseSearchQuery(
                    case_number=tracked_case.case_number,
                    court_code=tracked_case.court_code,
                    court_name=tracked_case.court_name,
                )
            )
            if not results:
                raise CaseTrackingProviderError("Case tracking provider returned no cases.")
            snapshot = results[0]
    except (CaseTrackingProviderUnavailable, CaseTrackingProviderError, HTTPException) as exc:
        _fail_operation(
            session,
            context=context,
            tracked_case=tracked_case,
            operation=operation,
            exc=exc,
        )
        session.commit()
        if isinstance(exc, HTTPException):
            raise exc
        raise _safe_provider_error(exc) from exc
    _record_operation_snapshot(
        session,
        tracked_case=tracked_case,
        operation=operation,
        snapshot=snapshot,
    )
    created = apply_snapshot(
        session,
        context=context,
        tracked_case=tracked_case,
        snapshot=snapshot,
    )
    _complete_operation(
        session,
        tracked_case=tracked_case,
        operation=operation,
        created_update_count=len(created),
    )
    record_from_context(
        session,
        context,
        action="case_tracking.refresh",
        target_type="tracked_case_bookmark",
        target_id=bookmark.id,
        matter_id=bookmark.matter_id,
        metadata={
            "tracked_case_id_sha256": _hash_value(tracked_case.id),
            "created_update_count": len(created),
            "provider": active_provider.provider_key,
            "operation_id": operation.id,
            "correlation_id": operation.correlation_id,
            "response_class": operation.response_class,
            "cost_minor": operation.cost_minor,
            "currency": operation.currency,
        },
    )
    from caseops_api.services.saas_billing import record_manual_refresh_usage

    record_manual_refresh_usage(
        session,
        context=context,
        tracked_case_id=tracked_case.id,
    )
    session.commit()
    return CaseTrackingRefreshResponse(
        bookmark=_bookmark_record(session, bookmark),
        created_updates=[_update_record(update, bookmark_id=bookmark.id) for update in created],
    )


def list_updates(
    session: Session,
    *,
    context: SessionContext,
    bookmark_id: str,
) -> CaseTrackingUpdateListResponse:
    bookmark = _get_bookmark(session, context=context, bookmark_id=bookmark_id)
    rows = list(
        session.scalars(
            select(TrackedCaseUpdate)
            .where(
                TrackedCaseUpdate.company_id == context.company.id,
                TrackedCaseUpdate.tracked_case_id == bookmark.tracked_case_id,
            )
            .order_by(TrackedCaseUpdate.created_at.desc())
        )
    )
    return CaseTrackingUpdateListResponse(
        updates=[_update_record(row, bookmark_id=bookmark.id) for row in rows]
    )


@dataclass(frozen=True, slots=True)
class CaseTrackingSourceDownload:
    content: bytes
    content_type: str
    filename: str


def _get_update_for_bookmark(
    session: Session,
    *,
    context: SessionContext,
    bookmark: TrackedCaseBookmark,
    update_id: str,
) -> TrackedCaseUpdate:
    update = session.scalar(
        select(TrackedCaseUpdate).where(
            TrackedCaseUpdate.id == update_id,
            TrackedCaseUpdate.company_id == context.company.id,
            TrackedCaseUpdate.tracked_case_id == bookmark.tracked_case_id,
        )
    )
    if update is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case tracking update not found.",
        )
    return update


def _validated_ecourts_source_url(raw_url: str, *, base_url: str) -> str:
    base = base_url.rstrip("/")
    parsed_base = urlparse(base)
    if not parsed_base.scheme or not parsed_base.netloc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Case tracking provider base URL is not configured correctly.",
        )
    absolute = raw_url
    if raw_url.startswith("/"):
        absolute = urljoin(f"{parsed_base.scheme}://{parsed_base.netloc}", raw_url)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Case tracking source URL is not downloadable.",
        )
    if parsed.netloc.lower() != parsed_base.netloc.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Case tracking source is outside the configured provider.",
        )
    if "/api/partner/case/" not in parsed.path or "/order/" not in parsed.path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Case tracking source path is not an order document.",
        )
    return absolute


def _filename_from_disposition(disposition: str | None) -> str | None:
    if not disposition:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', disposition, re.I)
    if not match:
        return None
    return unquote(match.group(1)).strip() or None


def _safe_source_filename(update: TrackedCaseUpdate, response: httpx.Response) -> str:
    header_name = _filename_from_disposition(response.headers.get("content-disposition"))
    base_name = header_name or update.title or update.source_record_key or "case-source"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base_name.strip()).strip(".-")
    if not safe:
        safe = "case-source"
    if "." not in safe:
        content_type = response.headers.get("content-type", "").lower()
        safe = f"{safe}.pdf" if "pdf" in content_type else f"{safe}.bin"
    return safe[:180]


def download_case_tracking_source(
    session: Session,
    *,
    context: SessionContext,
    bookmark_id: str,
    update_id: str,
    transport: httpx.BaseTransport | None = None,
) -> CaseTrackingSourceDownload:
    bookmark = _get_bookmark(session, context=context, bookmark_id=bookmark_id)
    update = _get_update_for_bookmark(
        session,
        context=context,
        bookmark=bookmark,
        update_id=update_id,
    )
    if not update.source_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No source document is available for this case tracking update.",
        )
    settings = get_settings()
    enabled, provider, configured, reason = provider_status()
    if not enabled or not configured or provider != "ecourtsindia":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=reason or "Case tracking provider credentials are not configured.",
        )
    if not settings.ecourtsindia_api_base_url or not settings.ecourtsindia_api_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="eCourtsIndia provider credentials are not configured.",
        )
    source_url = _validated_ecourts_source_url(
        update.source_url,
        base_url=settings.ecourtsindia_api_base_url,
    )
    try:
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = request_with_retries(
                "GET",
                source_url,
                client=client,
                headers={
                    "Authorization": f"Bearer {settings.ecourtsindia_api_token}",
                    "Accept": "application/pdf,application/octet-stream,*/*",
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=redact_provider_error(exc),
        ) from exc
    content_type = response.headers.get("content-type") or "application/octet-stream"
    if "application/json" in content_type.lower():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Case tracking provider returned an error instead of a source document.",
        )
    record_from_context(
        session,
        context,
        action="case_tracking.source_downloaded",
        target_type="tracked_case_update",
        target_id=update.id,
        matter_id=bookmark.matter_id,
        metadata={
            "tracked_case_id_sha256": _hash_value(update.tracked_case_id),
            "bookmark_id_sha256": _hash_value(bookmark.id),
            "provider": provider,
            "update_type": update.update_type,
            "source_record_key_sha256": _hash_value(update.source_record_key),
        },
    )
    session.commit()
    return CaseTrackingSourceDownload(
        content=response.content,
        content_type=content_type,
        filename=_safe_source_filename(update, response),
    )


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
    seen: set[str] = set()
    for membership in memberships:
        if membership.company_id in seen:
            continue
        contexts.append(
            SessionContext(
                company=membership.company,
                user=membership.user,
                membership=membership,
            )
        )
        seen.add(membership.company_id)
    return contexts


def _eligible_tracked_case_predicate(*, company_id: str):
    return (
        select(TrackedCaseBookmark.id)
        .outerjoin(Matter, Matter.id == TrackedCaseBookmark.matter_id)
        .where(
            TrackedCaseBookmark.company_id == company_id,
            TrackedCaseBookmark.tracked_case_id == TrackedCase.id,
            TrackedCaseBookmark.is_archived.is_(False),
            or_(
                TrackedCaseBookmark.matter_id.is_(None),
                and_(
                    Matter.company_id == company_id,
                    Matter.is_active.is_(True),
                    Matter.status.notin_(("closed", "disposed")),
                ),
            ),
        )
        .exists()
    )


def _eligible_tracked_case_count(session: Session, *, company_id: str) -> int:
    return int(
        session.scalar(
            select(func.count(TrackedCase.id)).where(
                TrackedCase.company_id == company_id,
                _eligible_tracked_case_predicate(company_id=company_id),
            )
        )
        or 0
    )


def _poll_run_record(run: TrackedCasePollRun) -> CaseTrackingPollRunRecord:
    return CaseTrackingPollRunRecord(
        id=run.id,
        company_id=run.company_id,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        checked_count=run.checked_count,
        update_count=run.update_count,
        error_count=run.error_count,
        skipped_count=run.skipped_count,
        blocked_count=run.blocked_count,
        provider_call_count=run.provider_call_count,
        backlog_remaining_count=run.backlog_remaining_count,
        metadata=dict(run.metadata_json or {}),
    )


def _record_safe_poll_run(
    session: Session,
    *,
    context: SessionContext,
    status_value: str,
    reason: str,
    window: CaseTrackingWindowState,
    provider_key: str,
    force: bool,
) -> CaseTrackingPollRunRecord:
    eligible_count = _eligible_tracked_case_count(session, company_id=context.company.id)
    run = TrackedCasePollRun(
        company_id=context.company.id,
        status=status_value,
        started_at=_now(),
        completed_at=_now(),
        skipped_count=eligible_count,
        blocked_count=eligible_count if status_value == "blocked" else 0,
        backlog_remaining_count=eligible_count,
        metadata_json={
            "provider": provider_key,
            "reason": reason,
            "tracked_count": eligible_count,
            "attempted_count": 0,
            "eligibility": "explicit_tracked_bookmarks_only",
            "force": force,
            "window": window.metadata(),
        },
    )
    session.add(run)
    session.flush()
    record_from_context(
        session,
        context,
        action="case_tracking.poll_run",
        target_type="tracked_case_poll_run",
        target_id=run.id,
        metadata=dict(run.metadata_json or {}),
    )
    session.commit()
    return _poll_run_record(run)


def poll_tracked_cases(
    session: Session,
    *,
    provider: CaseTrackingProvider | None = None,
    enforce_window: bool = False,
    force: bool = False,
    now: datetime | None = None,
) -> list[CaseTrackingPollRunRecord]:
    settings = get_settings()
    window = case_tracking_window_state(now)
    contexts = _system_contexts(session)
    runs: list[CaseTrackingPollRunRecord] = []

    if enforce_window and not force and not window.inside_window:
        for context in contexts:
            runs.append(
                _record_safe_poll_run(
                    session,
                    context=context,
                    status_value="blocked",
                    reason="outside_configured_refresh_window",
                    window=window,
                    provider_key=settings.case_tracking_provider,
                    force=force,
                )
            )
        return runs

    if not settings.case_tracking_enabled:
        for context in contexts:
            runs.append(
                _record_safe_poll_run(
                    session,
                    context=context,
                    status_value="skipped",
                    reason="case_tracking_disabled",
                    window=window,
                    provider_key="disabled",
                    force=force,
                )
            )
        return runs

    try:
        active_provider = provider or get_case_tracking_provider()
    except CaseTrackingProviderUnavailable as exc:
        redacted = redact_provider_error(exc)
        for context in contexts:
            runs.append(
                _record_safe_poll_run(
                    session,
                    context=context,
                    status_value="blocked",
                    reason=redacted,
                    window=window,
                    provider_key=settings.case_tracking_provider,
                    force=force,
                )
            )
        return runs

    for context in contexts:
        total_eligible = _eligible_tracked_case_count(session, company_id=context.company.id)
        run = TrackedCasePollRun(
            company_id=context.company.id,
            status="completed",
            started_at=_now(),
            metadata_json={
                "provider": active_provider.provider_key,
                "tracked_count": total_eligible,
                "attempted_count": 0,
                "eligibility": "explicit_tracked_bookmarks_only",
                "force": force,
                "window": window.metadata(),
            },
        )
        session.add(run)
        session.flush()
        cases = list(
            session.scalars(
                select(TrackedCase)
                .options(selectinload(TrackedCase.bookmarks))
                .where(
                    TrackedCase.company_id == context.company.id,
                    _eligible_tracked_case_predicate(company_id=context.company.id),
                    TrackedCase.quarantined_at.is_(None),
                    or_(
                        TrackedCase.next_provider_refresh_at.is_(None),
                        TrackedCase.next_provider_refresh_at <= _now(),
                    ),
                )
                .order_by(
                    TrackedCase.last_provider_checked_at.asc().nullsfirst(),
                    TrackedCase.created_at.asc(),
                )
                .limit(settings.case_tracking_poll_limit)
            )
        )
        run.metadata_json = {
            **dict(run.metadata_json or {}),
            "attempted_count": len(cases),
        }
        run.backlog_remaining_count = max(0, total_eligible - len(cases))
        run.skipped_count = run.backlog_remaining_count
        bulk_snapshots: dict[str, ProviderCaseSnapshot] = {}
        bulk_errors: dict[str, str] = {}
        cnrs = list(
            dict.fromkeys(
                normalized
                for tracked_case in cases
                if (normalized := normalize_cnr(tracked_case.cnr_number))
            )
        )
        if cnrs:
            if enforce_window and not force and not case_tracking_window_state().inside_window:
                run.status = "partial"
                run.backlog_remaining_count += len(cases)
                run.skipped_count += len(cases)
                run.metadata_json = {
                    **dict(run.metadata_json or {}),
                    "partial_reason": "window_closed_before_bulk_refresh",
                }
            else:
                try:
                    run.provider_call_count += 1
                    bulk_result = active_provider.refresh_cases(cnrs=cnrs)
                    bulk_snapshots = {
                        normalized: snapshot
                        for snapshot in bulk_result.snapshots
                        if (normalized := normalize_cnr(snapshot.cnr_number))
                    }
                    bulk_errors = {
                        normalized: message
                        for raw_cnr, message in bulk_result.errors.items()
                        if (normalized := normalize_cnr(raw_cnr))
                    }
                except Exception as exc:
                    bulk_errors = {cnr: redact_provider_error(exc) for cnr in cnrs}
        for index, tracked_case in enumerate(cases):
            if (
                run.status == "partial"
                and dict(run.metadata_json or {}).get("partial_reason")
                == "window_closed_before_bulk_refresh"
            ):
                break
            if enforce_window and not force and not case_tracking_window_state().inside_window:
                remaining = len(cases) - index
                run.status = "partial"
                run.backlog_remaining_count += remaining
                run.skipped_count += remaining
                run.metadata_json = {
                    **dict(run.metadata_json or {}),
                    "partial_reason": "window_closed_before_case_refresh",
                }
                break
            if tracked_case.quarantined_at is not None:
                run.skipped_count += 1
                run.backlog_remaining_count += 1
                continue
            operation = _new_operation(
                session,
                context=context,
                tracked_case=tracked_case,
                operation_type="scheduled",
                poll_run_id=run.id,
            )
            try:
                if tracked_case.cnr_number:
                    normalized_cnr = normalize_cnr(tracked_case.cnr_number)
                    if normalized_cnr and normalized_cnr in bulk_errors:
                        raise CaseTrackingProviderError(bulk_errors[normalized_cnr])
                    snapshot = bulk_snapshots.get(normalized_cnr or "") if normalized_cnr else None
                    if snapshot is None:
                        run.provider_call_count += 1
                        snapshot = active_provider.get_case_by_cnr(cnr=tracked_case.cnr_number)
                else:
                    run.provider_call_count += 1
                    results = active_provider.search_cases(
                        query=CaseSearchQuery(
                            case_number=tracked_case.case_number,
                            court_code=tracked_case.court_code,
                            court_name=tracked_case.court_name,
                        )
                    )
                    if not results:
                        raise CaseTrackingProviderError("No provider result for tracked case.")
                    snapshot = results[0]
                _record_operation_snapshot(
                    session,
                    tracked_case=tracked_case,
                    operation=operation,
                    snapshot=snapshot,
                )
                created = apply_snapshot(
                    session,
                    context=context,
                    tracked_case=tracked_case,
                    snapshot=snapshot,
                )
                run.checked_count += 1
                run.update_count += len(created)
                _complete_operation(
                    session,
                    tracked_case=tracked_case,
                    operation=operation,
                    created_update_count=len(created),
                )
            except Exception as exc:
                _fail_operation(
                    session,
                    context=context,
                    tracked_case=tracked_case,
                    operation=operation,
                    exc=exc,
                )
                run.error_count += 1
                continue
        run.completed_at = _now()
        if run.status != "partial":
            run.status = (
                "partial" if run.error_count or run.backlog_remaining_count else "completed"
            )
        run.metadata_json = {
            **dict(run.metadata_json or {}),
            "checked_count": run.checked_count,
            "update_count": run.update_count,
            "error_count": run.error_count,
            "skipped_count": run.skipped_count,
            "blocked_count": run.blocked_count,
            "provider_call_count": run.provider_call_count,
            "backlog_remaining_count": run.backlog_remaining_count,
            "bulk_cnr_count": len(cnrs),
        }
        session.add(run)
        record_from_context(
            session,
            context,
            action="case_tracking.poll_run",
            target_type="tracked_case_poll_run",
            target_id=run.id,
            metadata=dict(run.metadata_json or {}),
        )
        session.commit()
        runs.append(_poll_run_record(run))
    return runs
