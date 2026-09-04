from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.db.models import (
    AuthorityDocument,
    BillingSubscription,
    CaseTrackingSupportMatrix,
    Company,
    CompanyMembership,
    Matter,
    MatterActivity,
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
    CaseTrackingReleaseSmokeResponse,
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
from caseops_api.services.next_hearing import apply_next_hearing_update, clear_next_hearing
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
    redact_provider_error,
)
from caseops_api.services.paid_provider_safety import (
    assert_paid_provider_call_allowed,
    paid_provider_block_reason,
)
from caseops_api.services.provider_spend import (
    provider_spend_rows,
    release_provider_spend,
    release_provider_spend_in_session,
    reserve_provider_spend,
    reserve_provider_spend_in_session,
    settle_provider_spend,
)
from caseops_api.services.session_context import SessionContext

_MAX_BODY_LENGTH = 500
_RELEASE_SMOKE_MAX_SNAPSHOT_EVENTS = 200
_RED_PROVIDER_RESPONSE_CLASSES = {
    "ambiguous_match",
    "authentication",
    "billing",
    "case_not_found",
    "match_validation_failed",
    "parse_error",
    "provider_error",
    "rate_limit",
    "timeout",
}
_TRANSIENT_PROVIDER_RESPONSE_CLASSES = {
    "ambiguous_match",
    "billing",
    "case_not_found",
    "concurrent_refresh",
    "match_validation_failed",
    "provider_error",
    "rate_limit",
    "timeout",
}
_KNOWN_PROVIDER_RESPONSE_CLASSES = (
    _RED_PROVIDER_RESPONSE_CLASSES | _TRANSIENT_PROVIDER_RESPONSE_CLASSES
)
_TRANSIENT_RECOVERY_COOLDOWN = timedelta(hours=1)
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


@dataclass(frozen=True, slots=True)
class MatterCaseTrackingBackfillResult:
    evaluated_count: int = 0
    linked_count: int = 0
    existing_case_link_count: int = 0
    skipped_count: int = 0
    blocked_count: int = 0

    def metadata(self) -> dict[str, int]:
        return {
            "evaluated_count": self.evaluated_count,
            "linked_count": self.linked_count,
            "existing_case_link_count": self.existing_case_link_count,
            "skipped_count": self.skipped_count,
            "blocked_count": self.blocked_count,
        }


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
    explicit = getattr(exc, "response_class", None)
    if explicit in _KNOWN_PROVIDER_RESPONSE_CLASSES:
        return str(explicit)
    value = f"{type(exc).__name__} {exc}".lower()
    if "timeout" in value:
        return "timeout"
    if any(token in value for token in ("401", "403", "auth", "token", "credential")):
        return "authentication"
    if any(token in value for token in ("402", "billing", "payment")):
        return "billing"
    if any(token in value for token in ("429", "rate", "quota")):
        return "rate_limit"
    if any(token in value for token in ("parse", "schema", "malformed", "decode")):
        return "parse_error"
    return "provider_error"


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _is_transient_provider_failure(tracked_case: TrackedCase) -> bool:
    return tracked_case.last_response_class in _TRANSIENT_PROVIDER_RESPONSE_CLASSES


def _transient_recovery_due(tracked_case: TrackedCase) -> bool:
    due_at = _aware_utc(tracked_case.next_provider_refresh_at)
    return due_at is None or due_at <= _now()


def _release_legacy_transient_quarantine(tracked_case: TrackedCase) -> None:
    if tracked_case.quarantined_at is None or not _is_transient_provider_failure(tracked_case):
        return
    tracked_case.quarantined_at = None
    tracked_case.quarantine_reason_redacted = None
    tracked_case.provider_freshness_status = (
        "stale" if tracked_case.last_provider_successful_at else "never_succeeded"
    )


def _case_tracking_call_cost(
    session: Session,
    *,
    provider: str,
    court_code: str | None,
    court_name: str | None,
) -> tuple[int, str]:
    from caseops_api.services.production_safety import support_matrix_match

    row = support_matrix_match(
        session,
        provider=provider,
        court_code=court_code,
        court_name=court_name,
    )
    if row is not None:
        amount, currency = int(row.refresh_cost_minor), row.currency
    else:
        from caseops_api.services.provider_costs import effective_cost_minor

        amount, _ = effective_cost_minor(
            session,
            category="case_refresh",
            provider=provider,
        )
        currency = "INR"
    if amount <= 0 or currency != "INR":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "provider_cost_policy",
                "message": (
                    "The eCourts provider call price is unavailable or is not denominated "
                    "in INR; no external request was made."
                ),
                "provider": provider,
            },
        )
    return amount, currency


def _manual_refresh_cost(session: Session, tracked_case: TrackedCase) -> tuple[int, str]:
    return _case_tracking_call_cost(
        session,
        provider=tracked_case.provider,
        court_code=tracked_case.court_code,
        court_name=tracked_case.court_name,
    )


def _record_case_tracking_provider_usage(
    session: Session,
    *,
    context: SessionContext,
    provider_key: str,
    usage_type: str,
    feature_key: str,
    display_label: str,
    cost_minor: int,
    tracked_case_id: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
) -> None:
    from caseops_api.services.saas_billing import record_usage

    subscription_id = session.scalar(
        select(BillingSubscription.id)
        .where(BillingSubscription.company_id == context.company.id)
        .order_by(BillingSubscription.created_at.desc())
        .limit(1)
    )
    record_usage(
        session,
        company_id=context.company.id,
        subscription_id=subscription_id,
        usage_type=usage_type,
        feature_key=feature_key,
        provider_key=provider_key,
        quantity=1,
        unit="provider_call",
        actor_membership_id=context.membership.id,
        tracked_case_id=tracked_case_id,
        estimated_cost_minor=cost_minor,
        display_label=display_label,
        source_type=source_type,
        source_id=source_id,
        metadata={"provider": provider_key},
    )


def _new_operation(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    operation_type: str,
    poll_run_id: str | None = None,
    correlation_id: str | None = None,
) -> TrackedCaseProviderOperation:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": f"case-tracking:{tracked_case.id}"},
        )
    running = session.scalar(
        select(TrackedCaseProviderOperation.id).where(
            TrackedCaseProviderOperation.tracked_case_id == tracked_case.id,
            TrackedCaseProviderOperation.status == "running",
        )
    )
    if running is not None:
        raise CaseTrackingProviderError(
            "A refresh is already running for this tracked case.",
            response_class="concurrent_refresh",
        )
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
                TrackedCaseProviderOperation.attempts < TrackedCaseProviderOperation.max_attempts,
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
        correlation_id=correlation_id or uuid4().hex,
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
                {"retry_of_operation_id": automatic_retry.id} if automatic_retry is not None else {}
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
            if isinstance(event, dict) and isinstance(event.get("text"), str):
                text = event["text"]
                if len(text) > 4000:
                    event["text"] = text[:4000]
                    event["snapshot_text_preview_truncated"] = True
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


def _converge_snapshot_identity(
    session: Session,
    *,
    context: SessionContext,
    tracked_case: TrackedCase,
    operation: TrackedCaseProviderOperation,
    snapshot: ProviderCaseSnapshot,
) -> TrackedCase:
    """Converge a verified provider identity without violating uniqueness.

    Case-number bookmarks can legitimately learn their CNR on the first
    provider refresh. If the tenant already has the CNR-form tracked row, a
    blind identity-key update violates ``uq_tracked_cases_provider_identity``
    and poisons the poll transaction. Keep the older row as immutable lineage,
    move its active consumers to the canonical CNR row, and continue the same
    operation there. No user or administrator replay is required.
    """

    target_identity = _tracked_case_identity_key(
        cnr_number=snapshot.cnr_number or tracked_case.cnr_number,
        case_number=snapshot.case_number or tracked_case.case_number,
        court_code=snapshot.court_code or tracked_case.court_code,
        court_name=snapshot.court_name or tracked_case.court_name,
    )
    if target_identity == tracked_case.identity_key:
        return tracked_case
    canonical = session.scalar(
        select(TrackedCase)
        .options(selectinload(TrackedCase.bookmarks))
        .where(
            TrackedCase.company_id == context.company.id,
            TrackedCase.provider == tracked_case.provider,
            TrackedCase.identity_key == target_identity,
            TrackedCase.id != tracked_case.id,
        )
        .with_for_update(of=TrackedCase)
    )
    if canonical is None:
        return tracked_case

    competing_operation = session.scalar(
        select(TrackedCaseProviderOperation.id).where(
            TrackedCaseProviderOperation.tracked_case_id == canonical.id,
            TrackedCaseProviderOperation.status == "running",
            TrackedCaseProviderOperation.id != operation.id,
        )
    )
    if competing_operation is not None:
        raise CaseTrackingProviderError(
            "The canonical tracked case is already being refreshed.",
            response_class="concurrent_refresh",
        )

    now = _now()
    canonical_scopes = {
        (bookmark.created_by_membership_id, bookmark.active_scope_key)
        for bookmark in canonical.bookmarks
        if bookmark.active_scope_key is not None
    }
    moved_bookmark_count = 0
    archived_duplicate_count = 0
    for bookmark in list(tracked_case.bookmarks):
        scope = (bookmark.created_by_membership_id, bookmark.active_scope_key)
        if bookmark.active_scope_key is not None and scope in canonical_scopes:
            bookmark.is_archived = True
            bookmark.active_scope_key = None
            bookmark.archived_at = now
            archived_duplicate_count += 1
            session.add(bookmark)
            continue
        bookmark.tracked_case = canonical
        bookmark.tracked_case_id = canonical.id
        session.add(bookmark)
        moved_bookmark_count += 1
        if bookmark.active_scope_key is not None:
            canonical_scopes.add(scope)

    canonical_update_keys = set(
        session.execute(
            select(TrackedCaseUpdate.source_record_key, TrackedCaseUpdate.update_type).where(
                TrackedCaseUpdate.tracked_case_id == canonical.id
            )
        ).all()
    )
    for update_row in list(tracked_case.updates):
        key = (update_row.source_record_key, update_row.update_type)
        if key not in canonical_update_keys:
            update_row.tracked_case = canonical
            update_row.tracked_case_id = canonical.id
            session.add(update_row)
            canonical_update_keys.add(key)

    from caseops_api.db.models import BillingUsageAttribution, IpTrackedCaseLink

    for attribution in session.scalars(
        select(BillingUsageAttribution).where(
            BillingUsageAttribution.tracked_case_id == tracked_case.id
        )
    ):
        attribution.tracked_case_id = canonical.id
        session.add(attribution)

    canonical_ip_keys = set(
        session.execute(
            select(IpTrackedCaseLink.docket_id, IpTrackedCaseLink.proceeding_id).where(
                IpTrackedCaseLink.tracked_case_id == canonical.id
            )
        ).all()
    )
    for link in session.scalars(
        select(IpTrackedCaseLink).where(IpTrackedCaseLink.tracked_case_id == tracked_case.id)
    ):
        key = (link.docket_id, link.proceeding_id)
        if key in canonical_ip_keys:
            link.link_status = "retired"
        else:
            link.tracked_case_id = canonical.id
            canonical_ip_keys.add(key)
        session.add(link)

    tracked_case.identity_key = f"merged:{tracked_case.id}"
    tracked_case.metadata_json = {
        **dict(tracked_case.metadata_json or {}),
        "identity_state": "merged_into_canonical",
        "canonical_tracked_case_id_sha256": _hash_value(canonical.id),
        "identity_merged_at": now.isoformat(),
    }
    if tracked_case.last_operation_id == operation.id:
        tracked_case.last_operation_id = None
    operation.tracked_case = canonical
    operation.tracked_case_id = canonical.id
    canonical.last_operation_id = operation.id
    canonical.last_provider_attempted_at = tracked_case.last_provider_attempted_at
    canonical.next_provider_refresh_at = tracked_case.next_provider_refresh_at
    session.add_all([tracked_case, canonical, operation])
    session.flush()
    record_from_context(
        session,
        context,
        action="case_tracking.identity_converged",
        target_type="tracked_case",
        target_id=canonical.id,
        metadata={
            "retired_tracked_case_id_sha256": _hash_value(tracked_case.id),
            "canonical_identity_sha256": _hash_value(target_identity),
            "moved_bookmark_count": moved_bookmark_count,
            "archived_duplicate_count": archived_duplicate_count,
        },
    )
    return canonical


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
    transient_failure = response_class in _TRANSIENT_PROVIDER_RESPONSE_CLASSES
    operation.status = "quarantined" if exhausted and not transient_failure else "failed"
    operation.next_attempt_at = operation.completed_at + (
        _TRANSIENT_RECOVERY_COOLDOWN if exhausted and transient_failure else timedelta(minutes=15)
    )
    if exhausted and not transient_failure:
        operation.next_attempt_at = None
    tracked_case.last_error = error
    tracked_case.last_response_class = response_class
    tracked_case.next_provider_refresh_at = operation.next_attempt_at
    if exhausted and not transient_failure:
        tracked_case.quarantined_at = operation.completed_at
        tracked_case.quarantine_reason_redacted = error
        operation.quarantined_at = operation.completed_at
        operation.quarantine_reason_redacted = error
        tracked_case.provider_freshness_status = "blocked"
    else:
        tracked_case.provider_freshness_status = (
            "stale" if tracked_case.last_provider_successful_at else "never_succeeded"
        )
        if exhausted:
            operation.metadata_json = {
                **dict(operation.metadata_json or {}),
                "automatic_recovery_scheduled": True,
                "automatic_recovery_at": operation.next_attempt_at.isoformat(),
            }
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
            title=(
                "Case tracking provider recovery scheduled"
                if transient_failure
                else "Case tracking provider needs attention"
            ),
            body=(
                f"{operation.provider} returned {response_class}. "
                + (
                    f"Automatic recovery is scheduled for {operation.next_attempt_at.isoformat()}."
                    if transient_failure and operation.next_attempt_at is not None
                    else "Review the correlated provider operation before replay."
                )
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


def _normalize_court_name(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]+", " ", value).strip().upper()
    return re.sub(r"\s+", " ", normalized) or None


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
    court_name: str | None = None,
) -> str:
    normalized_cnr = normalize_cnr(cnr_number)
    if normalized_cnr:
        return f"cnr:{normalized_cnr}"
    normalized_case = normalize_case_number(case_number) or "UNKNOWN"
    normalized_court = _normalize_court_code(court_code)
    if normalized_court:
        return f"case:{normalized_case}|court:{normalized_court}"
    normalized_name = _normalize_court_name(court_name)
    if normalized_name:
        court_digest = hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()[:24]
        return f"case:{normalized_case}|court-name:{court_digest}"
    normalized_court = "UNKNOWN"
    return f"case:{normalized_case}|court:{normalized_court}"


def _verified_sync_snapshot_identity(
    tracked_case: TrackedCase,
    snapshots: list[ProviderCaseSnapshot],
) -> ProviderCaseSnapshot:
    """Return exactly one identity-verified provider result or fail closed."""

    expected_cnr = normalize_cnr(tracked_case.cnr_number)
    if expected_cnr:
        if len(snapshots) != 1:
            raise CaseTrackingProviderError(
                "The provider did not return exactly one CNR record.",
                response_class="case_not_found" if not snapshots else "ambiguous_match",
            )
        snapshot = snapshots[0]
        if normalize_cnr(snapshot.cnr_number) != expected_cnr:
            raise CaseTrackingProviderError(
                "The provider CNR did not match the tracked matter.",
                response_class="match_validation_failed",
            )
        return snapshot

    expected_case = normalize_case_number(tracked_case.case_number)
    expected_court_code = _normalize_court_code(tracked_case.court_code)
    expected_court_name = _normalize_court_name(tracked_case.court_name)
    if not expected_case or not (expected_court_code or expected_court_name):
        raise CaseTrackingProviderError(
            "The tracked matter lacks a reliable case-number and court identity.",
            response_class="match_validation_failed",
        )
    verified: list[ProviderCaseSnapshot] = []
    for snapshot in snapshots:
        if normalize_case_number(snapshot.case_number) != expected_case:
            continue
        candidate_code = _normalize_court_code(snapshot.court_code)
        candidate_name = _normalize_court_name(snapshot.court_name)
        if expected_court_code:
            court_matches = candidate_code == expected_court_code
        else:
            court_matches = candidate_name == expected_court_name
        if court_matches:
            verified.append(snapshot)
    if not snapshots:
        response_class = "case_not_found"
    elif not verified:
        response_class = "match_validation_failed"
    elif len(verified) > 1:
        response_class = "ambiguous_match"
    else:
        return verified[0]
    raise CaseTrackingProviderError(
        "The provider search did not produce one verified tracked-matter match.",
        response_class=response_class,
    )


def _resolved_next_hearing_snapshot(
    snapshot: ProviderCaseSnapshot,
    *,
    as_of: date | None = None,
) -> ProviderCaseSnapshot:
    """Resolve the nearest evidenced upcoming date without prediction."""

    today = as_of or datetime.now(UTC).date()
    candidates = [
        value
        for value in [snapshot.next_hearing_on, *(event.event_date for event in snapshot.hearings)]
        if value is not None and value >= today
    ]
    resolved = min(candidates) if candidates else None
    evidence = snapshot.metadata.get("next_hearing_evidence")
    evidence_state = str(evidence.get("state")) if isinstance(evidence, dict) else None
    if resolved is not None:
        resolution = "verified_upcoming"
    elif evidence_state == "confirmed_absent":
        resolution = "confirmed_absent"
    else:
        resolution = "unavailable"
    return replace(
        snapshot,
        next_hearing_on=resolved,
        metadata={
            **snapshot.metadata,
            "next_hearing_resolution": {
                "state": resolution,
                "as_of": today.isoformat(),
                "candidate_count": len(candidates),
            },
        },
    )


def _validated_sync_snapshot(
    tracked_case: TrackedCase,
    snapshots: list[ProviderCaseSnapshot],
) -> ProviderCaseSnapshot:
    return _resolved_next_hearing_snapshot(
        _verified_sync_snapshot_identity(tracked_case, snapshots)
    )


def _bookmark_scope_key(matter: Matter | None) -> str:
    return matter.id if matter else "company"


def provider_status_response(
    session: Session,
    *,
    context: SessionContext,
) -> CaseTrackingProviderStatusResponse:
    enabled, provider, configured, reason = provider_status()
    spend = next(
        row
        for row in provider_spend_rows(session, company=context.company)
        if row.provider_key == "ecourtsindia"
    )
    return CaseTrackingProviderStatusResponse(
        enabled=enabled,
        provider=provider,
        configured=configured,
        reason=reason,
        workspace_monthly_spend_minor=spend.spent_minor,
        workspace_monthly_limit_minor=spend.monthly_limit_minor,
        workspace_monthly_remaining_minor=spend.remaining_minor,
        workspace_monthly_limit_unlimited=spend.unlimited,
        workspace_monthly_limit_currency=spend.currency,
        workspace_monthly_limit_policy_source=spend.policy_source,
    )


def _safe_provider_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, CaseTrackingProviderUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if _response_class(exc) == "billing":
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Case search is temporarily unavailable because the provider "
                "prepaid balance is exhausted. The service owner must replenish "
                "the provider account before retrying."
            ),
        )
    if _response_class(exc) == "case_not_found":
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No verified provider case matched this tracked matter.",
        )
    if _response_class(exc) in {
        "ambiguous_match",
        "concurrent_refresh",
        "match_validation_failed",
    }:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=redact_provider_error(exc),
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
    reservation_id: str | None = None
    try:
        active_provider = provider or get_case_tracking_provider()
        from caseops_api.services.production_safety import assert_case_tracking_supported

        assert_case_tracking_supported(
            session,
            provider=active_provider.provider_key,
            court_code=payload.court_code,
            court_name=payload.court_name,
        )
        assert_paid_provider_call_allowed(
            context=context,
            provider=active_provider.provider_key,
            base_url=getattr(active_provider, "base_url", None),
            transport_is_mocked=getattr(active_provider, "transport", None) is not None,
        )
        cost_minor, _currency = _case_tracking_call_cost(
            session,
            provider=active_provider.provider_key,
            court_code=payload.court_code,
            court_name=payload.court_name,
        )
        reservation_id = reserve_provider_spend(
            company_id=context.company.id,
            actor_membership_id=context.membership.id,
            provider_key=active_provider.provider_key,
            operation_key="case_tracking_search",
            amount_minor=cost_minor,
        )
        snapshots = active_provider.search_cases(query=query)
    except (CaseTrackingProviderUnavailable, CaseTrackingProviderError, HTTPException) as exc:
        release_provider_spend(reservation_id=reservation_id)
        if isinstance(exc, HTTPException):
            raise exc
        raise _safe_provider_error(exc) from exc
    _record_case_tracking_provider_usage(
        session,
        context=context,
        provider_key=active_provider.provider_key,
        usage_type="case_tracking_search",
        feature_key="case_tracking_search",
        display_label="eCourts case search",
        cost_minor=cost_minor,
        source_type="case_tracking_provider",
        source_id=active_provider.provider_key,
    )
    settle_provider_spend(session, reservation_id=reservation_id)
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
    transient_failure = _is_transient_provider_failure(case)
    transient_recovery_due = _transient_recovery_due(case)
    effective_quarantine = case.quarantined_at is not None and not transient_failure
    if transient_failure:
        freshness = "stale" if last_success else "never_succeeded"
    if effective_quarantine:
        freshness = "quarantined"
    elif not enabled or not configured:
        freshness = "disabled"
    provider_health_red = (
        case.last_response_class in _RED_PROVIDER_RESPONSE_CLASSES and not transient_failure
    )
    manual_allowed = bool(
        enabled
        and configured
        and not effective_quarantine
        and not provider_health_red
        and (not transient_failure or transient_recovery_due)
    )
    disabled_reason = None
    if effective_quarantine:
        disabled_reason = "Provider work is quarantined; an administrator must review it."
    elif transient_failure and not transient_recovery_due:
        recovery_at = _aware_utc(case.next_provider_refresh_at)
        disabled_reason = (
            "The provider is temporarily unavailable. Automatic recovery is scheduled"
            + (f" for {recovery_at.isoformat()}." if recovery_at else ".")
        )
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
            if effective_quarantine
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
    court_name: str | None = None,
) -> TrackedCase | None:
    statement = select(TrackedCase).where(
        TrackedCase.company_id == company_id,
        TrackedCase.provider == provider,
        TrackedCase.identity_key
        == _tracked_case_identity_key(
            cnr_number=cnr_number,
            case_number=case_number,
            court_code=court_code,
            court_name=court_name,
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
        court_name=payload.court_name,
    )
    tracked_case = _find_tracked_case(
        session,
        company_id=context.company.id,
        provider=payload.provider,
        cnr_number=payload.cnr_number,
        case_number=payload.case_number,
        court_code=payload.court_code,
        court_name=payload.court_name,
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

    if tracked_case is None:
        from caseops_api.services.saas_billing import assert_tracked_case_limit

        assert_tracked_case_limit(session, context=context)
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
        if (
            event
            and event.text
            and (
                existing.source_text is None
                or (existing.source_text_truncated and not event.text_truncated)
            )
        ):
            existing.source_text = event.text
            existing.source_text_sha256 = hashlib.sha256(event.text.encode("utf-8")).hexdigest()
            existing.source_text_truncated = event.text_truncated
            if not existing.source_url and event.source_url:
                existing.source_url = event.source_url
            record_from_context(
                session,
                context,
                action="case_tracking.source_text_backfilled",
                target_type="tracked_case_update",
                target_id=existing.id,
                metadata={
                    "tracked_case_id_sha256": _hash_value(tracked_case.id),
                    "source_record_key_sha256": _hash_value(source_record_key),
                    "source_text_sha256": existing.source_text_sha256,
                    "source_text_truncated": existing.source_text_truncated,
                },
            )
            session.add(existing)
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
        source_text=event.text if event else None,
        source_text_sha256=(
            hashlib.sha256(event.text.encode("utf-8")).hexdigest() if event and event.text else None
        ),
        source_text_truncated=event.text_truncated if event else False,
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
    hearing_resolution = snapshot.metadata.get("next_hearing_resolution")
    if isinstance(hearing_resolution, dict):
        hearing_resolution_state = str(hearing_resolution.get("state") or "unavailable")
    elif snapshot.next_hearing_on is not None:
        hearing_resolution_state = "verified_upcoming"
    else:
        hearing_resolution_state = "unavailable"
    effective_next_hearing = (
        snapshot.next_hearing_on
        if hearing_resolution_state in {"verified_upcoming", "confirmed_absent"}
        else tracked_case.next_hearing_on
    )
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
        and hearing_resolution_state != "unavailable"
        and tracked_case.next_hearing_on != effective_next_hearing
    ):
        hearing_hash = _hash_value({"next_hearing_on": effective_next_hearing})
        update = _create_update(
            session,
            context=context,
            tracked_case=tracked_case,
            update_type="hearing_update",
            source_record_key=f"hearing:{hearing_hash}",
            title=f"Next hearing changed to {effective_next_hearing or 'no upcoming date'}",
            current_hash=hearing_hash,
            previous_hash=_hash_value({"next_hearing_on": tracked_case.next_hearing_on}),
            event=None,
            hearing_date=effective_next_hearing,
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
        court_name=snapshot.court_name or tracked_case.court_name,
    )
    tracked_case.court_name = snapshot.court_name or tracked_case.court_name
    tracked_case.case_title = snapshot.case_title or tracked_case.case_title
    tracked_case.party_names_json = snapshot.party_names or tracked_case.party_names_json
    tracked_case.current_status = snapshot.current_status
    tracked_case.current_stage = snapshot.current_stage
    tracked_case.next_hearing_on = effective_next_hearing
    tracked_case.last_snapshot_hash = _snapshot_hash(snapshot)
    tracked_case.last_provider_checked_at = _now()
    tracked_case.last_error = None
    tracked_case.metadata_json = {
        **(tracked_case.metadata_json or {}),
        **snapshot.metadata,
        "source_url": snapshot.source_url,
    }
    session.add(tracked_case)
    if operational_linked_matters:
        for matter in operational_linked_matters:
            if hearing_resolution_state == "verified_upcoming" and snapshot.next_hearing_on:
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
                    authoritative_automatic=True,
                )
            elif hearing_resolution_state == "confirmed_absent":
                clear_next_hearing(
                    session,
                    matter=matter,
                    source="case_tracking",
                    actor_membership_id=context.membership.id,
                    context=context,
                    source_ref_type="tracked_case",
                    source_ref_id=tracked_case.id,
                    reason="provider_confirmed_no_upcoming_hearing",
                    respect_manual_lock=True,
                )
    session.flush()
    return created


def refresh_bookmark(
    session: Session,
    *,
    context: SessionContext,
    bookmark_id: str,
    provider: CaseTrackingProvider | None = None,
    operation_type: str = "manual",
    correlation_id: str | None = None,
    enforce_manual_limit: bool = True,
) -> CaseTrackingRefreshResponse:
    bookmark = _get_bookmark(session, context=context, bookmark_id=bookmark_id)
    tracked_case = bookmark.tracked_case
    transient_failure = _is_transient_provider_failure(tracked_case)
    if tracked_case.quarantined_at is not None and not transient_failure:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Case tracking provider work is quarantined pending administrator review.",
        )
    if transient_failure and not _transient_recovery_due(tracked_case):
        recovery_at = _aware_utc(tracked_case.next_provider_refresh_at)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "The provider is temporarily unavailable; automatic recovery is scheduled"
                + (f" for {recovery_at.isoformat()}." if recovery_at else ".")
            ),
        )
    if tracked_case.last_response_class in _RED_PROVIDER_RESPONSE_CLASSES and not transient_failure:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Case tracking provider health is red after the latest failed operation; "
                "an administrator must review or replay it."
            ),
        )
    _release_legacy_transient_quarantine(tracked_case)
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
    if enforce_manual_limit:
        from caseops_api.services.saas_billing import assert_manual_refresh_limit

        assert_manual_refresh_limit(
            session,
            context=context,
            tracked_case_id=tracked_case.id,
        )
    reservation_id: str | None = None
    try:
        active_provider = provider or get_case_tracking_provider()
        from caseops_api.services.production_safety import assert_case_tracking_supported

        assert_case_tracking_supported(
            session,
            provider=active_provider.provider_key,
            court_code=tracked_case.court_code,
            court_name=tracked_case.court_name,
        )
        assert_paid_provider_call_allowed(
            context=context,
            provider=active_provider.provider_key,
            base_url=getattr(active_provider, "base_url", None),
            transport_is_mocked=getattr(active_provider, "transport", None) is not None,
        )
        cost_minor, _currency = _manual_refresh_cost(session, tracked_case)
        reservation_id = reserve_provider_spend(
            company_id=context.company.id,
            actor_membership_id=context.membership.id,
            provider_key=active_provider.provider_key,
            operation_key=f"case_tracking_{operation_type}_refresh",
            amount_minor=cost_minor,
        )
    except (CaseTrackingProviderUnavailable, CaseTrackingProviderError, HTTPException) as exc:
        release_provider_spend(reservation_id=reservation_id)
        if isinstance(exc, HTTPException):
            raise exc
        raise _safe_provider_error(exc) from exc
    tracked_case.last_provider_refresh_requested_at = _now()
    try:
        operation = _new_operation(
            session,
            context=context,
            tracked_case=tracked_case,
            operation_type=operation_type,
            correlation_id=correlation_id,
        )
    except CaseTrackingProviderError as exc:
        session.rollback()
        release_provider_spend(reservation_id=reservation_id)
        raise _safe_provider_error(exc) from exc
    try:
        if tracked_case.cnr_number:
            snapshot = _validated_sync_snapshot(
                tracked_case,
                [active_provider.get_case_by_cnr(cnr=tracked_case.cnr_number)],
            )
        else:
            results = active_provider.search_cases(
                query=CaseSearchQuery(
                    case_number=tracked_case.case_number,
                    court_code=tracked_case.court_code,
                    court_name=tracked_case.court_name,
                )
            )
            snapshot = _validated_sync_snapshot(tracked_case, results)
    except (CaseTrackingProviderUnavailable, CaseTrackingProviderError, HTTPException) as exc:
        release_provider_spend_in_session(session, reservation_id=reservation_id)
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
    original_tracked_case = tracked_case
    try:
        with session.begin_nested():
            tracked_case = _converge_snapshot_identity(
                session,
                context=context,
                tracked_case=tracked_case,
                operation=operation,
                snapshot=snapshot,
            )
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
    except Exception as exc:
        _fail_operation(
            session,
            context=context,
            tracked_case=original_tracked_case,
            operation=operation,
            exc=exc,
        )
        session.commit()
        if isinstance(exc, HTTPException):
            raise exc
        raise _safe_provider_error(exc) from exc
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
    _record_case_tracking_provider_usage(
        session,
        context=context,
        provider_key=active_provider.provider_key,
        usage_type="case_refresh",
        feature_key=(
            "case_tracking_manual_refresh" if enforce_manual_limit else "case_tracking_refresh"
        ),
        display_label=("Manual case refresh" if enforce_manual_limit else "Case tracking refresh"),
        cost_minor=cost_minor,
        tracked_case_id=tracked_case.id,
        source_type="tracked_case",
        source_id=tracked_case.id,
    )
    settle_provider_spend(session, reservation_id=reservation_id)
    session.commit()
    return CaseTrackingRefreshResponse(
        bookmark=_bookmark_record(session, bookmark),
        created_updates=[_update_record(update, bookmark_id=bookmark.id) for update in created],
    )


def _release_smoke_source_update(
    session: Session,
    *,
    bookmark: TrackedCaseBookmark,
    update_id: str | None = None,
    require_verified_cache: bool = False,
    allow_missing: bool = False,
) -> TrackedCaseUpdate | None:
    filters = [
        TrackedCaseUpdate.company_id == bookmark.company_id,
        TrackedCaseUpdate.tracked_case_id == bookmark.tracked_case_id,
        TrackedCaseUpdate.source_url.is_not(None),
    ]
    if update_id is not None:
        filters.append(TrackedCaseUpdate.id == update_id)
    if require_verified_cache:
        filters.extend(
            [
                TrackedCaseUpdate.source_text.is_not(None),
                TrackedCaseUpdate.source_text_sha256.is_not(None),
                TrackedCaseUpdate.source_text_truncated.is_(False),
            ]
        )
    source_update = session.scalar(
        select(TrackedCaseUpdate)
        .where(*filters)
        .order_by(TrackedCaseUpdate.created_at.desc())
        .limit(1)
    )
    if source_update is None:
        if allow_missing:
            return None
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The release-smoke fixture has no complete provider source evidence; "
                "production release proof remains incomplete."
            ),
        )
    if require_verified_cache:
        _verified_cached_source(source_update)
    return source_update


def _verified_provider_snapshot(
    session: Session,
    *,
    bookmark: TrackedCaseBookmark,
    operation_id: str | None = None,
) -> tuple[TrackedCaseProviderOperation, TrackedCaseProviderSnapshot] | None:
    filters = [
        TrackedCaseProviderOperation.company_id == bookmark.company_id,
        TrackedCaseProviderOperation.tracked_case_id == bookmark.tracked_case_id,
        TrackedCaseProviderOperation.status.in_(("succeeded", "no_change")),
        TrackedCaseProviderOperation.response_class.in_(("success", "no_change")),
        TrackedCaseProviderOperation.completed_at.is_not(None),
    ]
    if operation_id is not None:
        filters.append(TrackedCaseProviderOperation.id == operation_id)
    operation = session.scalar(
        select(TrackedCaseProviderOperation)
        .join(
            TrackedCaseProviderSnapshot,
            TrackedCaseProviderSnapshot.operation_id == TrackedCaseProviderOperation.id,
        )
        .where(*filters)
        .order_by(TrackedCaseProviderOperation.completed_at.desc())
        .limit(1)
    )
    if operation is None:
        return None
    snapshot = session.scalar(
        select(TrackedCaseProviderSnapshot).where(
            TrackedCaseProviderSnapshot.operation_id == operation.id,
            TrackedCaseProviderSnapshot.company_id == bookmark.company_id,
            TrackedCaseProviderSnapshot.tracked_case_id == bookmark.tracked_case_id,
        )
    )
    if snapshot is None:  # pragma: no cover - protected by the join
        return None
    if (
        not re.fullmatch(r"[0-9a-f]{64}", snapshot.raw_hash)
        or not re.fullmatch(r"[0-9a-f]{64}", snapshot.normalized_hash)
        or _hash_value(snapshot.raw_json) != snapshot.raw_hash
        or _hash_value(snapshot.normalized_json) != snapshot.normalized_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored provider snapshot failed integrity verification.",
        )
    return operation, snapshot


@dataclass(frozen=True, slots=True)
class _ReleaseSmokeCachedEvidence:
    operation: TrackedCaseProviderOperation
    snapshot: TrackedCaseProviderSnapshot
    source_update: TrackedCaseUpdate


def _release_smoke_authority_source_text(
    session: Session,
    *,
    bookmark: TrackedCaseBookmark,
    update: TrackedCaseUpdate,
) -> tuple[str, AuthorityDocument, str] | None:
    """Resolve one exact, accessible corpus copy for a legacy provider event."""

    tracked_case = bookmark.tracked_case
    case_number = normalize_case_number(tracked_case.case_number)
    court_name = (tracked_case.court_name or "").strip()
    if update.order_date is None:
        return None
    ecourts_source_reference: str | None = None
    cnr = normalize_cnr(tracked_case.cnr_number)
    if tracked_case.provider == "ecourtsindia" and cnr and update.source_url:
        order_match = re.search(
            rf"/case/{re.escape(cnr)}/order/order-([1-9][0-9]*)\.pdf$",
            unquote(urlparse(update.source_url).path),
            flags=re.IGNORECASE,
        )
        if order_match:
            ecourts_source_reference = (
                f"{cnr}_{order_match.group(1)}_{update.order_date.isoformat()}.pdf"
            )
    # An order-specific eCourts reference is authoritative. Falling back to a
    # generic case/court identity when that reference is available can attach
    # order 1's text to order 2 when the documents share a decision date.
    if ecourts_source_reference:
        identity_predicates = [
            and_(
                AuthorityDocument.source == "ecourts-hc",
                func.upper(func.trim(AuthorityDocument.source_reference))
                == ecourts_source_reference.upper(),
            )
        ]
    elif case_number and court_name:
        identity_predicates = [
            and_(
                func.upper(func.trim(AuthorityDocument.court_name)) == court_name.upper(),
                or_(
                    func.upper(func.trim(AuthorityDocument.case_reference)) == case_number,
                    func.upper(func.trim(AuthorityDocument.case_number)) == case_number,
                ),
            )
        ]
    else:
        identity_predicates = []
    if not identity_predicates:
        return None
    rows = list(
        session.scalars(
            select(AuthorityDocument)
            .where(
                AuthorityDocument.source_access_state == "available",
                AuthorityDocument.document_text.is_not(None),
                AuthorityDocument.decision_date == update.order_date,
                or_(*identity_predicates),
            )
            .order_by(AuthorityDocument.id)
            .limit(3)
        )
    )
    matches: list[tuple[AuthorityDocument, str]] = []
    for row in rows:
        if (
            ecourts_source_reference
            and row.source == "ecourts-hc"
            and (row.source_reference or "").strip().upper() == ecourts_source_reference.upper()
        ):
            matches.append((row, "ecourts_cnr_order_reference"))
        elif not ecourts_source_reference and (
            court_name
            and row.court_name.strip().upper() == court_name.upper()
            and (
                normalize_case_number(row.case_reference) == case_number
                or normalize_case_number(row.case_number) == case_number
            )
        ):
            matches.append((row, "case_number_court"))
    if len(matches) != 1:
        return None
    authority, match_mode = matches[0]
    source_text = authority.document_text or ""
    if not source_text.strip() or not (authority.source_reference or authority.canonical_url):
        return None
    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if authority.content_hash and authority.content_hash != source_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored authority source failed integrity verification.",
        )
    return source_text, authority, match_mode


def _backfill_release_smoke_source_from_snapshot(
    session: Session,
    *,
    context: SessionContext,
    bookmark: TrackedCaseBookmark,
    operation: TrackedCaseProviderOperation,
    snapshot: TrackedCaseProviderSnapshot,
) -> TrackedCaseUpdate | None:
    raw = snapshot.raw_json
    if not isinstance(raw, dict):  # pragma: no cover - verified JSON model invariant
        return None
    candidates: dict[tuple[str, str], dict[str, object]] = {}
    ambiguous: set[tuple[str, str]] = set()
    inspected = 0
    for collection, update_type in (
        ("orders", "new_order"),
        ("judgments", "new_judgment"),
    ):
        events = raw.get(collection)
        if not isinstance(events, list):
            continue
        for event in events:
            if inspected >= _RELEASE_SMOKE_MAX_SNAPSHOT_EVENTS:
                break
            inspected += 1
            if not isinstance(event, dict):
                continue
            source_record_key = event.get("source_record_key")
            source_url = event.get("source_url")
            if (
                not isinstance(source_record_key, str)
                or not source_record_key
                or not isinstance(source_url, str)
                or not source_url
            ):
                continue
            key = (update_type, source_record_key)
            if key in candidates:
                ambiguous.add(key)
                candidates.pop(key, None)
                continue
            if key not in ambiguous:
                candidates[key] = event
        if inspected >= _RELEASE_SMOKE_MAX_SNAPSHOT_EVENTS:
            break
    if not candidates:
        return None

    rows = list(
        session.scalars(
            select(TrackedCaseUpdate)
            .where(
                TrackedCaseUpdate.company_id == bookmark.company_id,
                TrackedCaseUpdate.tracked_case_id == bookmark.tracked_case_id,
                TrackedCaseUpdate.update_type.in_(
                    sorted({update_type for update_type, _ in candidates})
                ),
                TrackedCaseUpdate.source_record_key.in_(
                    sorted({source_key for _, source_key in candidates})
                ),
                TrackedCaseUpdate.source_url.is_not(None),
                TrackedCaseUpdate.source_text.is_(None),
                TrackedCaseUpdate.source_text_sha256.is_(None),
                TrackedCaseUpdate.source_text_truncated.is_(False),
            )
            .order_by(TrackedCaseUpdate.created_at.desc())
            .limit(_RELEASE_SMOKE_MAX_SNAPSHOT_EVENTS)
        )
    )
    for update in rows:
        event = candidates.get((update.update_type, update.source_record_key))
        if event is None or update.source_url != event["source_url"]:
            continue
        authority: AuthorityDocument | None = None
        authority_match_mode: str | None = None
        event_text = event.get("text")
        if (
            isinstance(event_text, str)
            and event_text.strip()
            and event.get("text_truncated") is False
            and event.get("snapshot_text_preview_truncated") is not True
        ):
            source_text = event_text
            provenance = "verified_provider_snapshot"
        else:
            authority_source = _release_smoke_authority_source_text(
                session,
                bookmark=bookmark,
                update=update,
            )
            if authority_source is None:
                continue
            source_text, authority, authority_match_mode = authority_source
            provenance = "verified_authority_document"
        source_text_sha256 = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        update.source_text = source_text
        update.source_text_sha256 = source_text_sha256
        update.source_text_truncated = False
        update.provider_metadata_json = {
            **(update.provider_metadata_json or {}),
            "source_text_provenance": provenance,
            **(
                {
                    "authority_document_id": authority.id,
                    "authority_source": authority.source,
                    "authority_source_reference": authority.source_reference
                    or authority.canonical_url,
                    "authority_content_hash": authority.content_hash or source_text_sha256,
                    "authority_match_mode": authority_match_mode,
                }
                if authority is not None
                else {}
            ),
        }
        session.add(update)
        record_from_context(
            session,
            context,
            action="case_tracking.source_text_backfilled",
            target_type="tracked_case_update",
            target_id=update.id,
            matter_id=bookmark.matter_id,
            metadata={
                "provenance": provenance,
                "tracked_case_id_sha256": _hash_value(bookmark.tracked_case_id),
                "source_record_key_sha256": _hash_value(update.source_record_key),
                "source_text_sha256": source_text_sha256,
                "provider_evidence_operation_id": operation.id,
                "provider_snapshot_id": snapshot.id,
                "provider_snapshot_raw_hash": snapshot.raw_hash,
                **(
                    {
                        "authority_document_id": authority.id,
                        "authority_source": authority.source,
                        "authority_content_hash": authority.content_hash or source_text_sha256,
                        "authority_match_mode": authority_match_mode,
                    }
                    if authority is not None
                    else {}
                ),
            },
        )
        session.flush()
        return update
    return None


def _release_smoke_cached_evidence(
    session: Session,
    *,
    context: SessionContext,
    bookmark: TrackedCaseBookmark,
) -> _ReleaseSmokeCachedEvidence | None:
    provider_evidence = _verified_provider_snapshot(session, bookmark=bookmark)
    if provider_evidence is None:
        return None
    operation, snapshot = provider_evidence
    source_update = _release_smoke_source_update(
        session,
        bookmark=bookmark,
        require_verified_cache=True,
        allow_missing=True,
    )
    if source_update is None:
        source_update = _backfill_release_smoke_source_from_snapshot(
            session,
            context=context,
            bookmark=bookmark,
            operation=operation,
            snapshot=snapshot,
        )
        if source_update is None:
            return None
    return _ReleaseSmokeCachedEvidence(
        operation=operation,
        snapshot=snapshot,
        source_update=source_update,
    )


def _create_cached_release_smoke_operation(
    session: Session,
    *,
    context: SessionContext,
    bookmark: TrackedCaseBookmark,
    correlation_id: str,
    evidence: _ReleaseSmokeCachedEvidence,
) -> TrackedCaseProviderOperation:
    now = _now()
    operation = TrackedCaseProviderOperation(
        company_id=context.company.id,
        tracked_case_id=bookmark.tracked_case_id,
        requested_by_membership_id=context.membership.id,
        provider=bookmark.tracked_case.provider,
        operation_type="canary",
        correlation_id=correlation_id,
        # Keep the durable operation lifecycle on the canonical terminal status;
        # response_class records that no provider call was made.
        status="succeeded",
        response_class="verified_cached",
        cost_minor=0,
        currency=evidence.operation.currency,
        attempts=0,
        max_attempts=1,
        started_at=now,
        completed_at=now,
        metadata_json={
            "scope": "exact_release_stored_provider_evidence",
            "cost_disclosed": True,
            "verification_mode": "verified_cached",
            "provider_call_performed": False,
            "provider_evidence_operation_id": evidence.operation.id,
            "provider_evidence_completed_at": evidence.operation.completed_at.isoformat(),
            "provider_snapshot_id": evidence.snapshot.id,
            "provider_snapshot_raw_hash": evidence.snapshot.raw_hash,
            "provider_snapshot_normalized_hash": evidence.snapshot.normalized_hash,
            "source_update_id": evidence.source_update.id,
            "source_text_sha256": evidence.source_update.source_text_sha256,
        },
    )
    session.add(operation)
    session.flush()
    return operation


def _release_smoke_response(
    session: Session,
    *,
    bookmark: TrackedCaseBookmark,
    operation: TrackedCaseProviderOperation,
    release_sha: str,
    reused: bool,
) -> CaseTrackingReleaseSmokeResponse:
    if operation.response_class not in {"success", "no_change", "verified_cached"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The exact-release canary did not complete successfully; review "
                "the correlated provider operation before replay."
            ),
        )
    metadata = dict(operation.metadata_json or {})
    cached = operation.response_class == "verified_cached"
    evidence_mode = "verified_cached" if cached else "live_provider"
    provider_evidence = operation
    if cached:
        evidence_operation_id = str(metadata.get("provider_evidence_operation_id") or "")
        verified = _verified_provider_snapshot(
            session,
            bookmark=bookmark,
            operation_id=evidence_operation_id,
        )
        if verified is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Stored release evidence no longer resolves to a successful provider snapshot."
                ),
            )
        provider_evidence = verified[0]
    if provider_evidence.completed_at is None:  # pragma: no cover - success invariant
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Provider evidence has no completion timestamp.",
        )
    source_update = _release_smoke_source_update(
        session,
        bookmark=bookmark,
        update_id=(str(metadata.get("source_update_id")) if cached else None),
        require_verified_cache=cached,
    )
    if source_update is None:  # pragma: no cover - allow_missing is false
        raise RuntimeError("release source evidence was not persisted")
    evidence_completed_at = provider_evidence.completed_at
    if evidence_completed_at.tzinfo is None:
        evidence_completed_at = evidence_completed_at.replace(tzinfo=UTC)
    return CaseTrackingReleaseSmokeResponse(
        release_sha=release_sha,
        operation_id=operation.id,
        response_class=operation.response_class,
        evidence_mode=evidence_mode,
        provider_call_performed=not cached,
        provider_evidence_operation_id=provider_evidence.id,
        provider_evidence_completed_at=evidence_completed_at,
        provider_evidence_age_seconds=max(0, int((_now() - evidence_completed_at).total_seconds())),
        source_text_sha256=source_update.source_text_sha256,
        bookmark=_bookmark_record(session, bookmark),
        source_update=_update_record(source_update, bookmark_id=bookmark.id),
        reused=reused,
    )


def run_release_smoke(
    session: Session,
    *,
    context: SessionContext,
    bookmark_id: str,
    release_sha: str,
    provider: CaseTrackingProvider | None = None,
) -> CaseTrackingReleaseSmokeResponse:
    """Verify one exact release without coupling deployment health to provider billing."""
    configured_sha = (get_settings().release_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", configured_sha) or configured_sha != release_sha:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Release-smoke SHA does not match the exact serving API revision.",
        )
    bookmark = _get_bookmark(session, context=context, bookmark_id=bookmark_id)
    tracked_case = bookmark.tracked_case
    if (tracked_case.metadata_json or {}).get("release_smoke_fixture") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Release smoke is restricted to an explicitly approved QA fixture.",
        )
    # Serialize the check-and-create section on the fixture. This makes the
    # provider-cost promise true even if two operators dispatch the same
    # release workflow concurrently; the second transaction observes the
    # first transaction's correlated operation after this lock is released.
    session.scalar(
        select(TrackedCase)
        .where(
            TrackedCase.id == tracked_case.id,
            TrackedCase.company_id == context.company.id,
        )
        .with_for_update()
    )
    correlation_id = f"release:{release_sha}"
    existing = session.scalar(
        select(TrackedCaseProviderOperation).where(
            TrackedCaseProviderOperation.company_id == context.company.id,
            TrackedCaseProviderOperation.correlation_id == correlation_id,
        )
    )
    if existing is not None:
        if existing.tracked_case_id != tracked_case.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This release canary is already bound to another QA fixture.",
            )
        return _release_smoke_response(
            session,
            bookmark=bookmark,
            operation=existing,
            release_sha=release_sha,
            reused=True,
        )

    cached_evidence = _release_smoke_cached_evidence(
        session,
        context=context,
        bookmark=bookmark,
    )
    if cached_evidence is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "release_smoke_evidence_missing",
                "message": (
                    "Release verification requires stored provider evidence. "
                    "No paid provider request was made."
                ),
            },
        )
    operation = _create_cached_release_smoke_operation(
        session,
        context=context,
        bookmark=bookmark,
        correlation_id=correlation_id,
        evidence=cached_evidence,
    )
    record_from_context(
        session,
        context,
        action="case_tracking.release_smoke",
        target_type="tracked_case_bookmark",
        target_id=bookmark.id,
        matter_id=bookmark.matter_id,
        metadata={
            "release_sha": release_sha,
            "operation_id": operation.id,
            "response_class": operation.response_class,
            "cost_minor": operation.cost_minor,
            "currency": operation.currency,
            "verification_mode": dict(operation.metadata_json or {}).get(
                "verification_mode", "live_provider"
            ),
            "provider_call_performed": operation.response_class != "verified_cached",
        },
    )
    session.commit()
    return _release_smoke_response(
        session,
        bookmark=bookmark,
        operation=operation,
        release_sha=release_sha,
        reused=False,
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
    source_format: str


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


def _safe_markdown_filename(update: TrackedCaseUpdate) -> str:
    base_name = update.title or update.source_record_key or "case-source"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base_name.strip()).strip(".-")
    if not safe:
        safe = "case-source"
    if not safe.lower().endswith(".md"):
        safe = f"{safe}.md"
    return safe[:180]


def _provider_payment_required(exc: httpx.HTTPError) -> bool:
    """Recognize the provider's HTTP payment boundary without trusting its body shape."""

    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 402


def _verified_cached_source(update: TrackedCaseUpdate) -> bytes | None:
    if not update.source_text or update.source_text_truncated:
        return None
    content = update.source_text.encode("utf-8")
    actual_hash = hashlib.sha256(content).hexdigest()
    if not update.source_text_sha256 or actual_hash != update.source_text_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cached provider source failed integrity verification.",
        )
    return content


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
    provider_block = paid_provider_block_reason(
        context=context,
        provider=provider,
        base_url=settings.ecourtsindia_api_base_url,
        transport_is_mocked=transport is not None,
    )
    if provider_block is not None:
        cached_source = _verified_cached_source(update)
        if cached_source is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "paid_provider_blocked_for_test",
                    "message": (
                        "Paid provider source downloads are disabled for tests and this "
                        "record has no complete verified cache. No external request was made."
                    ),
                    "provider": provider,
                    "reason": provider_block,
                },
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
                "provider_response_class": provider_block,
                "source_format": "provider-markdown",
                "update_type": update.update_type,
                "source_record_key_sha256": _hash_value(update.source_record_key),
                "source_text_sha256": update.source_text_sha256,
            },
        )
        session.commit()
        return CaseTrackingSourceDownload(
            content=cached_source,
            content_type="text/markdown; charset=utf-8",
            filename=_safe_markdown_filename(update),
            source_format="provider-markdown",
        )
    download_cost_minor, _currency = _manual_refresh_cost(session, bookmark.tracked_case)
    reservation_id = reserve_provider_spend(
        company_id=context.company.id,
        actor_membership_id=context.membership.id,
        provider_key=provider,
        operation_key="case_tracking_source_download",
        amount_minor=download_cost_minor,
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
        release_provider_spend(reservation_id=reservation_id)
        if _provider_payment_required(exc):
            cached_source = _verified_cached_source(update)
            if cached_source is not None:
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
                        "provider_response_class": "billing",
                        "source_format": "provider-markdown",
                        "update_type": update.update_type,
                        "source_record_key_sha256": _hash_value(update.source_record_key),
                        "source_text_sha256": update.source_text_sha256,
                    },
                )
                session.commit()
                return CaseTrackingSourceDownload(
                    content=cached_source,
                    content_type="text/markdown; charset=utf-8",
                    filename=_safe_markdown_filename(update),
                    source_format="provider-markdown",
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "The certified provider document is temporarily unavailable and "
                    "no complete verified provider text is cached."
                ),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=redact_provider_error(exc),
        ) from exc
    content_type = response.headers.get("content-type") or "application/octet-stream"
    if "application/json" in content_type.lower():
        release_provider_spend(reservation_id=reservation_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Case tracking provider returned an error instead of a source document.",
        )
    _record_case_tracking_provider_usage(
        session,
        context=context,
        provider_key=provider,
        usage_type="case_tracking_source_download",
        feature_key="case_tracking_source_download",
        display_label="eCourts source download",
        cost_minor=download_cost_minor,
        tracked_case_id=bookmark.tracked_case_id,
        source_type="tracked_case_update",
        source_id=update.id,
    )
    settle_provider_spend(session, reservation_id=reservation_id)
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
            "source_format": "provider-document",
            "update_type": update.update_type,
            "source_record_key_sha256": _hash_value(update.source_record_key),
        },
    )
    session.commit()
    return CaseTrackingSourceDownload(
        content=response.content,
        content_type=content_type,
        filename=_safe_source_filename(update, response),
        source_format="provider-document",
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


def _support_row_for_matter(
    rows: list[CaseTrackingSupportMatrix],
    *,
    court_name: str | None,
) -> CaseTrackingSupportMatrix | None:
    normalized_court = (court_name or "").strip().lower()
    exact = [
        row for row in rows if normalized_court and row.court.strip().lower() == normalized_court
    ]
    wildcard = [row for row in rows if row.court.strip() == "*"]
    selected = exact or wildcard
    return selected[0] if len(selected) == 1 else None


def backfill_existing_matter_case_tracking(
    session: Session,
    *,
    context: SessionContext,
    provider_key: str,
) -> MatterCaseTrackingBackfillResult:
    """Link a bounded batch of older eligible matters without provider calls.

    The query plan is constant in the number of candidates: one candidate
    query, one support-matrix query, one existing-case query, plus the billing
    capacity lookup. Provider network calls remain owned by the poll phase.
    """

    settings = get_settings()
    active_link_exists = (
        select(TrackedCaseBookmark.id)
        .where(
            TrackedCaseBookmark.company_id == context.company.id,
            TrackedCaseBookmark.matter_id == Matter.id,
            TrackedCaseBookmark.is_archived.is_(False),
        )
        .exists()
    )
    candidates = list(
        session.scalars(
            select(Matter)
            .where(
                Matter.company_id == context.company.id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("closed", "disposed")),
                or_(
                    Matter.cnr_number.is_not(None),
                    and_(Matter.case_number.is_not(None), Matter.court_name.is_not(None)),
                ),
                ~active_link_exists,
            )
            .order_by(Matter.created_at.asc(), Matter.id.asc())
            .limit(settings.case_tracking_auto_link_limit)
        )
    )
    if not candidates:
        return MatterCaseTrackingBackfillResult()

    support_rows = list(
        session.scalars(
            select(CaseTrackingSupportMatrix).where(
                CaseTrackingSupportMatrix.provider == provider_key,
                CaseTrackingSupportMatrix.tenant_visible.is_(True),
            )
        )
    )
    prepared: list[tuple[Matter, str, str | None, str | None]] = []
    skipped = 0
    blocked = 0
    for matter in candidates:
        normalized_cnr = normalize_cnr(matter.cnr_number)
        cnr = matter.cnr_number if normalized_cnr and len(normalized_cnr) >= 8 else None
        case_number = matter.case_number if normalize_case_number(matter.case_number) else None
        if not cnr and not (case_number and _normalize_court_name(matter.court_name)):
            skipped += 1
            continue
        support_row = _support_row_for_matter(support_rows, court_name=matter.court_name)
        if (
            support_row is None
            or not support_row.enabled
            or support_row.legal_tos_status.strip().lower() != "approved"
        ):
            blocked += 1
            continue
        identity_key = _tracked_case_identity_key(
            cnr_number=cnr,
            case_number=case_number,
            court_code=None,
            court_name=matter.court_name,
        )
        prepared.append((matter, identity_key, cnr, case_number))
    if not prepared:
        return MatterCaseTrackingBackfillResult(
            evaluated_count=len(candidates),
            skipped_count=skipped,
            blocked_count=blocked,
        )

    identity_keys = sorted({identity_key for _, identity_key, _, _ in prepared})
    existing_cases = {
        row.identity_key: row
        for row in session.scalars(
            select(TrackedCase).where(
                TrackedCase.company_id == context.company.id,
                TrackedCase.provider == provider_key,
                TrackedCase.identity_key.in_(identity_keys),
            )
        )
    }
    from caseops_api.services.saas_billing import tracked_case_remaining_capacity

    remaining_capacity = tracked_case_remaining_capacity(session, context=context)
    linked = 0
    existing_case_links = 0
    for matter, identity_key, cnr, case_number in prepared:
        tracked_case = existing_cases.get(identity_key)
        if tracked_case is None:
            if remaining_capacity is not None and remaining_capacity < 1:
                blocked += 1
                continue
            tracked_case = TrackedCase(
                id=str(uuid4()),
                company_id=context.company.id,
                provider=provider_key,
                identity_key=identity_key,
                cnr_number=normalize_cnr(cnr),
                normalized_cnr_number=normalize_cnr(cnr),
                case_number=case_number,
                normalized_case_number=normalize_case_number(case_number),
                court_name=matter.court_name,
                case_title=matter.title,
                party_names_json=[
                    value
                    for value in (matter.client_name, matter.opposing_party)
                    if value and value.strip()
                ],
                next_hearing_on=matter.next_hearing_on,
                last_snapshot_hash=_hash_value(
                    {"next_hearing_on": matter.next_hearing_on, "source": "matter_backfill"}
                ),
                metadata_json={
                    "source": "scheduled_existing_matter_backfill",
                    "matter_code": matter.matter_code,
                },
            )
            session.add(tracked_case)
            existing_cases[identity_key] = tracked_case
            if remaining_capacity is not None:
                remaining_capacity -= 1
        else:
            existing_case_links += 1
        bookmark = TrackedCaseBookmark(
            id=str(uuid4()),
            company_id=context.company.id,
            tracked_case_id=tracked_case.id,
            created_by_membership_id=context.membership.id,
            matter_id=matter.id,
            scope_key=matter.id,
            active_scope_key=matter.id,
            name=matter.matter_code,
            notification_enabled=True,
        )
        session.add(bookmark)
        session.add(
            MatterActivity(
                matter_id=matter.id,
                actor_membership_id=context.membership.id,
                event_type="case_tracking_linked",
                title="Case tracking linked",
                detail="eCourt case tracking was linked by the daily eligibility backfill.",
            )
        )
        record_from_context(
            session,
            context,
            action="case_tracking.bookmark_created",
            target_type="tracked_case_bookmark",
            target_id=bookmark.id,
            matter_id=matter.id,
            metadata={
                "tracked_case_id_sha256": _hash_value(tracked_case.id),
                "provider": provider_key,
                "has_cnr": bool(tracked_case.cnr_number),
                "has_case_number": bool(tracked_case.case_number),
                "notification_enabled": True,
                "origin": "scheduled_existing_matter_backfill",
            },
        )
        linked += 1
    session.flush()
    return MatterCaseTrackingBackfillResult(
        evaluated_count=len(candidates),
        linked_count=linked,
        existing_case_link_count=existing_case_links,
        skipped_count=skipped,
        blocked_count=blocked,
    )


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
    extra_metadata: dict[str, object] | None = None,
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
            "eligibility": "active_matter_links_and_explicit_bookmarks",
            "force": force,
            "window": window.metadata(),
            **(extra_metadata or {}),
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
        try:
            backfill = backfill_existing_matter_case_tracking(
                session,
                context=context,
                provider_key=active_provider.provider_key,
            )
            backfill_metadata: dict[str, object] = {"auto_link_backfill": backfill.metadata()}
        except Exception as exc:
            backfill_metadata = {
                "auto_link_backfill": {
                    "status": "failed",
                    "error": redact_provider_error(exc),
                }
            }
        provider_block = paid_provider_block_reason(
            context=context,
            provider=active_provider.provider_key,
            base_url=getattr(active_provider, "base_url", None),
            transport_is_mocked=getattr(active_provider, "transport", None) is not None,
            scheduled_tenant_filter=True,
        )
        if provider_block is not None:
            runs.append(
                _record_safe_poll_run(
                    session,
                    context=context,
                    status_value="skipped",
                    reason=provider_block,
                    window=window,
                    provider_key=active_provider.provider_key,
                    force=force,
                    extra_metadata=backfill_metadata,
                )
            )
            continue
        total_eligible = _eligible_tracked_case_count(session, company_id=context.company.id)
        cases = list(
            session.scalars(
                select(TrackedCase)
                .options(selectinload(TrackedCase.bookmarks))
                .where(
                    TrackedCase.company_id == context.company.id,
                    _eligible_tracked_case_predicate(company_id=context.company.id),
                    or_(
                        TrackedCase.quarantined_at.is_(None),
                        TrackedCase.last_response_class.in_(
                            tuple(_TRANSIENT_PROVIDER_RESPONSE_CLASSES)
                        ),
                    ),
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
        scheduled_costs = {
            tracked_case.id: _manual_refresh_cost(session, tracked_case)[0]
            for tracked_case in cases
        }
        try:
            provider_reservation_id = reserve_provider_spend_in_session(
                session,
                company_id=context.company.id,
                actor_membership_id=None,
                provider_key=active_provider.provider_key,
                operation_key="case_tracking_scheduled_poll",
                amount_minor=sum(scheduled_costs.values()),
            )
            session.commit()
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            runs.append(
                _record_safe_poll_run(
                    session,
                    context=context,
                    status_value="blocked",
                    reason=str(detail.get("code") or "provider_budget_exhausted"),
                    window=window,
                    provider_key=active_provider.provider_key,
                    force=force,
                )
            )
            continue
        run = TrackedCasePollRun(
            company_id=context.company.id,
            status="completed",
            started_at=_now(),
            metadata_json={
                "provider": active_provider.provider_key,
                "tracked_count": total_eligible,
                "attempted_count": 0,
                "eligibility": "active_matter_links_and_explicit_bookmarks",
                "force": force,
                "window": window.metadata(),
                **backfill_metadata,
            },
        )
        session.add(run)
        session.flush()
        run.metadata_json = {
            **dict(run.metadata_json or {}),
            "attempted_count": len(cases),
        }
        run.backlog_remaining_count = max(0, total_eligible - len(cases))
        run.skipped_count = run.backlog_remaining_count
        bulk_snapshots: dict[str, list[ProviderCaseSnapshot]] = {}
        bulk_errors: dict[str, str] = {}
        charged_case_count = 0
        charged_cost_minor = 0
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
                    bulk_result = active_provider.refresh_cases(cnrs=cnrs)
                    run.provider_call_count += max(1, bulk_result.provider_call_count)
                    for snapshot in bulk_result.snapshots:
                        normalized = normalize_cnr(snapshot.cnr_number)
                        if normalized:
                            bulk_snapshots.setdefault(normalized, []).append(snapshot)
                    bulk_errors = {
                        normalized: message
                        for raw_cnr, message in bulk_result.errors.items()
                        if (normalized := normalize_cnr(raw_cnr))
                    }
                except Exception as exc:
                    run.provider_call_count += 1
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
            if tracked_case.quarantined_at is not None and not _is_transient_provider_failure(
                tracked_case
            ):
                run.skipped_count += 1
                run.backlog_remaining_count += 1
                continue
            _release_legacy_transient_quarantine(tracked_case)
            try:
                operation = _new_operation(
                    session,
                    context=context,
                    tracked_case=tracked_case,
                    operation_type="scheduled",
                    poll_run_id=run.id,
                )
            except CaseTrackingProviderError as exc:
                if _response_class(exc) != "concurrent_refresh":
                    raise
                run.skipped_count += 1
                run.backlog_remaining_count += 1
                run.metadata_json = {
                    **dict(run.metadata_json or {}),
                    "concurrent_refresh_skip_count": int(
                        dict(run.metadata_json or {}).get("concurrent_refresh_skip_count") or 0
                    )
                    + 1,
                }
                continue
            original_tracked_case = tracked_case
            scheduled_cost_minor = scheduled_costs[tracked_case.id]
            try:
                if tracked_case.cnr_number:
                    normalized_cnr = normalize_cnr(tracked_case.cnr_number)
                    if normalized_cnr and normalized_cnr in bulk_errors:
                        bulk_error = bulk_errors[normalized_cnr]
                        classified = re.search(
                            r"\[(authentication|billing|case_not_found|parse_error|provider_error|rate_limit|timeout)\]$",
                            bulk_error,
                        )
                        raise CaseTrackingProviderError(
                            bulk_error,
                            response_class=(
                                classified.group(1) if classified else "provider_error"
                            ),
                        )
                    snapshots = (
                        bulk_snapshots.get(normalized_cnr or "", []) if normalized_cnr else []
                    )
                    if not snapshots:
                        run.provider_call_count += 1
                        snapshots = [active_provider.get_case_by_cnr(cnr=tracked_case.cnr_number)]
                    snapshot = _validated_sync_snapshot(tracked_case, snapshots)
                else:
                    run.provider_call_count += 1
                    results = active_provider.search_cases(
                        query=CaseSearchQuery(
                            case_number=tracked_case.case_number,
                            court_code=tracked_case.court_code,
                            court_name=tracked_case.court_name,
                        )
                    )
                    snapshot = _validated_sync_snapshot(tracked_case, results)
                with session.begin_nested():
                    tracked_case = _converge_snapshot_identity(
                        session,
                        context=context,
                        tracked_case=tracked_case,
                        operation=operation,
                        snapshot=snapshot,
                    )
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
                _record_case_tracking_provider_usage(
                    session,
                    context=context,
                    provider_key=active_provider.provider_key,
                    usage_type="case_refresh",
                    feature_key="case_tracking_scheduled_refresh",
                    display_label="Scheduled case refresh",
                    cost_minor=scheduled_cost_minor,
                    tracked_case_id=tracked_case.id,
                    source_type="tracked_case_poll_run",
                    source_id=run.id,
                )
                charged_case_count += 1
                charged_cost_minor += scheduled_cost_minor
            except Exception as exc:
                _fail_operation(
                    session,
                    context=context,
                    tracked_case=original_tracked_case,
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
            "charged_case_count": charged_case_count,
            "charged_cost_minor": charged_cost_minor,
        }
        if charged_case_count:
            settle_provider_spend(
                session,
                reservation_id=provider_reservation_id,
                amount_minor=charged_cost_minor,
            )
        else:
            release_provider_spend_in_session(
                session,
                reservation_id=provider_reservation_id,
            )
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
