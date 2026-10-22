"""Manager-only bounded projection of public admissions, not billing accounts."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session, load_only

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.db.models import BillingEnrollment
from caseops_api.schemas.platform_leads import (
    ConsoleLead,
    ConsoleLeadNotification,
    ConsoleLeadsResponse,
)
from caseops_api.services.billing_demo import _notification_eligible, _state
from caseops_api.services.platform_console_reports import _cursor, _decode

_KIND = "public-leads-v1"
_ERRORS = {
    "sender_approval_pending",
    "configuration_unavailable",
    "provider_rejected",
    "provider_rate_limited",
    "transport_outcome_unknown",
    "claim_expired",
    "attempt_limit",
    "timeout",
    "smtp_failure",
    "transport_failure",
    "automated_request_blocked",
    "transport_fence_closed",
    "test_transport_not_admitted",
}


def lead_record(row: BillingEnrollment) -> ConsoleLead:
    attribution = row.utm_json if isinstance(row.utm_json, dict) else {}
    state = _state(row)
    status = state.get("notification_status", "not_requested")
    status = "accepted" if status == "sent" else status
    if status not in {
        "not_requested",
        "pending",
        "sending",
        "accepted",
        "retry_pending",
        "exhausted",
        "outcome_unknown",
    }:
        status = "outcome_unknown"
    created = (
        row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
    )
    return ConsoleLead(
        id=row.id,
        submitted_at=created,
        contact_name=row.contact_name,
        contact_email=row.contact_email,
        contact_mobile=row.contact_mobile,
        company_name=row.company_name,
        segment=row.segment,
        selected_plan=row.selected_plan,
        source=row.source,
        role=attribution.get("role"),
        intent=attribution.get("intent"),
        notes=row.notes,
        privacy_notice_version=attribution.get("privacy_notice_version"),
        notification=ConsoleLeadNotification(
            status=status,
            attempts=max(0, int(state.get("attempts", 0))),
            last_error_code=state.get("last_error_code")
            if state.get("last_error_code") in _ERRORS
            else None,
            eligible=_notification_eligible(row) and not bool(state.get("automated_request")),
        ),
    )


def leads_page(session: Session, *, cursor: str | None, limit: int) -> ConsoleLeadsResponse:
    if not 1 <= limit <= 100:
        raise ValueError("Lead page limit must be between 1 and 100.")
    after = _decode(cursor, _KIND, 2)
    query = select(BillingEnrollment).where(BillingEnrollment.is_public_lead.is_(True))
    if after:
        try:
            timestamp = datetime.fromisoformat(after[0])
            if timestamp.tzinfo is None:
                raise ValueError("Missing cursor timezone.")
            UUID(after[1])
        except ValueError as exc:
            raise ProblemHTTPException(
                400, problem_type="console_cursor_invalid", detail="Invalid lead cursor."
            ) from exc
        query = query.where(
            tuple_(BillingEnrollment.created_at, BillingEnrollment.id) < (timestamp, after[1])
        )
    rows = list(
        session.scalars(
            query.options(
                load_only(
                    BillingEnrollment.id,
                    BillingEnrollment.is_public_lead,
                    BillingEnrollment.created_at,
                    BillingEnrollment.contact_name,
                    BillingEnrollment.contact_email,
                    BillingEnrollment.contact_mobile,
                    BillingEnrollment.company_name,
                    BillingEnrollment.segment,
                    BillingEnrollment.selected_plan,
                    BillingEnrollment.source,
                    BillingEnrollment.notes,
                    BillingEnrollment.utm_json,
                    BillingEnrollment.status_timestamps_json,
                    raiseload=True,
                )
            )
            .order_by(BillingEnrollment.created_at.desc(), BillingEnrollment.id.desc())
            .limit(limit + 1)
        )
    )
    items = [lead_record(row) for row in rows[:limit]]
    more = len(rows) > limit
    next_cursor = (
        _cursor(_KIND, [items[-1].submitted_at.isoformat(), items[-1].id]) if more else None
    )
    return ConsoleLeadsResponse(items=items, next_cursor=next_cursor, has_more=more)
