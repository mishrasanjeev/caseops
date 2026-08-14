"""IPLF-030A trademark portfolio listing (IP-PORT-02, IP-PORT-05, UJ-04-EXC-02).

Read-only projection over the existing IP owners. It creates no new record and
no second portfolio store: rows are assembled from ``TrademarkApplication``,
``IpAsset``, ``IpDocketRecord`` and the existing legal-deadline evidence.

Access is delegated to the canonical ``visible_ip_dockets_filter`` policy, so a
restricted record a user cannot open is **omitted entirely** rather than shown
as a redacted teaser.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpAsset,
    IpDeadline,
    IpDocketRecord,
    Matter,
    TrademarkApplication,
)
from caseops_api.schemas.ip_portfolio import (
    IpPortfolioCounts,
    IpPortfolioFilters,
    IpPortfolioListResponse,
    IpPortfolioRow,
)
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
)
from caseops_api.services.session_context import SessionContext

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def _normalize(values: list[str], *, lower: bool = True) -> list[str]:
    seen: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        cleaned = cleaned.lower() if lower else cleaned.upper()
        if cleaned not in seen:
            seen.append(cleaned)
    return seen


def _encode_cursor(updated_at, application_id: str) -> str:
    raw = f"{updated_at.isoformat()}|{application_id}".encode()
    return urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Decode an opaque cursor into a comparable timestamp and tie-break id.

    The timestamp must be parsed back into a ``datetime``; comparing the raw
    string against a ``DateTime`` column silently fails to filter on SQLite.
    """

    try:
        raw = urlsafe_b64decode(cursor.encode()).decode()
        timestamp, application_id = raw.split("|", 1)
        parsed = datetime.fromisoformat(timestamp)
    except Exception as exc:  # noqa: BLE001 - opaque cursor is a client contract
        raise HTTPException(status_code=400, detail="Invalid portfolio cursor.") from exc
    if not application_id:
        raise HTTPException(status_code=400, detail="Invalid portfolio cursor.")
    return parsed, application_id


def _scoped_query(
    session: Session,
    *,
    context: SessionContext,
    filters: IpPortfolioFilters,
) -> Select:
    """Company-scoped, access-filtered application rows joined to mark/docket."""

    statement = (
        select(TrademarkApplication, IpAsset, IpDocketRecord)
        .join(IpDocketRecord, IpDocketRecord.id == TrademarkApplication.docket_id)
        .outerjoin(IpAsset, IpAsset.id == TrademarkApplication.asset_id)
        .where(
            TrademarkApplication.company_id == context.company.id,
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            visible_ip_dockets_filter(session, context=context),
        )
    )
    if not filters.include_inactive:
        statement = statement.where(
            TrademarkApplication.is_active.is_(True),
            IpDocketRecord.is_active.is_(True),
        )
    if filters.matter_id:
        statement = statement.where(IpDocketRecord.matter_id == filters.matter_id)
    if filters.jurisdiction:
        statement = statement.where(
            func.upper(TrademarkApplication.jurisdiction).in_(
                _normalize(filters.jurisdiction, lower=False)
            )
        )
    if filters.office:
        statement = statement.where(TrademarkApplication.office.in_(filters.office))
    if filters.filing_phase:
        statement = statement.where(
            TrademarkApplication.filing_phase.in_(_normalize(filters.filing_phase))
        )
    if filters.asset_kind:
        statement = statement.where(IpAsset.asset_kind.in_(_normalize(filters.asset_kind)))
    if filters.docket_status:
        statement = statement.where(
            IpDocketRecord.status.in_(_normalize(filters.docket_status))
        )
    if filters.query:
        like = f"%{filters.query.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(IpDocketRecord.title).like(like),
                func.lower(func.coalesce(IpAsset.title, "")).like(like),
                func.lower(func.coalesce(IpDocketRecord.primary_identifier, "")).like(like),
            )
        )
    return statement


def _deadline_counts(session: Session, *, company_id: str, docket_ids: list[str]) -> dict:
    if not docket_ids:
        return {}
    today = date.today()
    rows = session.execute(
        select(
            IpDeadline.docket_id,
            func.count().filter(IpDeadline.state.in_(("confirmed", "overdue"))),
            func.count().filter(IpDeadline.state.in_(("candidate", "provisional"))),
            func.count().filter(
                IpDeadline.state.in_(("confirmed", "overdue")),
                IpDeadline.result_on.is_not(None),
                IpDeadline.result_on < today,
            ),
        )
        .where(
            IpDeadline.company_id == company_id,
            IpDeadline.docket_id.in_(docket_ids),
        )
        .group_by(IpDeadline.docket_id)
    ).all()
    return {row[0]: (int(row[1]), int(row[2]), int(row[3])) for row in rows}


def _incomplete_reasons(
    application: TrademarkApplication,
    asset: IpAsset | None,
    docket: IpDocketRecord,
) -> list[str]:
    reasons: list[str] = []
    if asset is None:
        reasons.append("missing_mark")
    elif not (asset.title or "").strip():
        reasons.append("missing_mark_title")
    if not docket.primary_identifier:
        reasons.append("missing_identifier")
    if application.source_pending_identifier_allocation:
        reasons.append("pending_identifier_allocation")
    if not application.office:
        reasons.append("missing_office")
    if not application.jurisdiction:
        reasons.append("missing_jurisdiction")
    return reasons


def list_ip_portfolio(
    session: Session,
    *,
    context: SessionContext,
    filters: IpPortfolioFilters,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> IpPortfolioListResponse:
    if not 1 <= limit <= MAX_LIMIT:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200.")

    statement = _scoped_query(session, context=context, filters=filters)
    page = statement.order_by(
        TrademarkApplication.updated_at.desc(), TrademarkApplication.id.desc()
    )
    if cursor:
        timestamp, application_id = _decode_cursor(cursor)
        page = page.where(
            or_(
                TrademarkApplication.updated_at < timestamp,
                (TrademarkApplication.updated_at == timestamp)
                & (TrademarkApplication.id < application_id),
            )
        )

    # One extra row tells us whether another page exists without a second count.
    candidates = list(session.execute(page.limit(limit + 1)).all())
    has_more = len(candidates) > limit
    candidates = candidates[:limit]

    # A linked Matter that is no longer operational hides its IP rows the same
    # way the docket listing does; this is a visibility rule, not a filter.
    visible: list[tuple] = []
    for application, asset, docket in candidates:
        if docket.matter_id:
            matter = session.get(Matter, docket.matter_id)
            if matter is None:
                continue
            try:
                assert_operational_matter(session, matter=matter)
            except MatterNotOperationalError:
                continue
        visible.append((application, asset, docket))

    docket_ids = [docket.id for _a, _s, docket in visible]
    deadlines = _deadline_counts(
        session, company_id=context.company.id, docket_ids=docket_ids
    )

    rows: list[IpPortfolioRow] = []
    for application, asset, docket in visible:
        open_count, unconfirmed, overdue = deadlines.get(docket.id, (0, 0, 0))
        reasons = _incomplete_reasons(application, asset, docket)
        rows.append(
            IpPortfolioRow(
                application_id=application.id,
                docket_id=docket.id,
                matter_id=docket.matter_id,
                asset_id=application.asset_id,
                asset_kind=asset.asset_kind if asset else None,
                asset_title=asset.title if asset else None,
                asset_jurisdiction=asset.jurisdiction if asset else None,
                docket_title=docket.title,
                docket_status=docket.status,
                primary_identifier=docket.primary_identifier,
                office=application.office,
                jurisdiction=application.jurisdiction,
                filing_phase=application.filing_phase,
                is_active=application.is_active,
                lifecycle_version=application.lifecycle_version,
                pending_identifier_allocation=(
                    application.source_pending_identifier_allocation
                ),
                record_complete=not reasons,
                incomplete_reasons=reasons,
                open_deadline_count=open_count,
                unconfirmed_deadline_count=unconfirmed,
                overdue_deadline_count=overdue,
                updated_at=application.updated_at,
            )
        )

    counts = IpPortfolioCounts(
        total=len(rows),
        complete_records=sum(1 for row in rows if row.record_complete),
        incomplete_records=sum(1 for row in rows if not row.record_complete),
        unconfirmed_deadline_records=sum(
            1 for row in rows if row.unconfirmed_deadline_count
        ),
        overdue_records=sum(1 for row in rows if row.overdue_deadline_count),
    )
    next_cursor = (
        _encode_cursor(rows[-1].updated_at, rows[-1].application_id)
        if has_more and rows
        else None
    )
    return IpPortfolioListResponse(
        rows=rows,
        counts=counts,
        filters=filters,
        limit=limit,
        next_cursor=next_cursor,
    )


__all__ = ["list_ip_portfolio"]
