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
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpAsset,
    IpDeadline,
    IpDocketRecord,
    Matter,
    MatterStatus,
    TrademarkApplication,
)
from caseops_api.schemas.ip_portfolio import (
    IpPortfolioCounts,
    IpPortfolioFamily,
    IpPortfolioFamilyMember,
    IpPortfolioFamilyResponse,
    IpPortfolioFilters,
    IpPortfolioListResponse,
    IpPortfolioRow,
)
from caseops_api.services.matter_access import visible_ip_dockets_filter
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
        .outerjoin(
            Matter,
            and_(
                Matter.id == IpDocketRecord.matter_id,
                Matter.company_id == context.company.id,
            ),
        )
        .where(
            TrademarkApplication.company_id == context.company.id,
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            visible_ip_dockets_filter(session, context=context),
            # Operational visibility is part of the SQL scope, not a
            # post-pagination filter.  Applying it after LIMIT can return an
            # empty page and discard the cursor even when later live records
            # exist.  Missing linked Matters fail closed; unlinked IP dockets
            # remain valid portfolio records.
            or_(
                IpDocketRecord.matter_id.is_(None),
                and_(
                    Matter.id.is_not(None),
                    Matter.is_active.is_(True),
                    Matter.status.in_(
                        [
                            MatterStatus.INTAKE.value,
                            MatterStatus.ACTIVE.value,
                            MatterStatus.ON_HOLD.value,
                        ]
                    ),
                ),
            ),
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
        statement = statement.where(IpDocketRecord.status.in_(_normalize(filters.docket_status)))
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

    visible = candidates

    docket_ids = [docket.id for _a, _s, docket in visible]
    deadlines = _deadline_counts(session, company_id=context.company.id, docket_ids=docket_ids)

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
                pending_identifier_allocation=(application.source_pending_identifier_allocation),
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
        unconfirmed_deadline_records=sum(1 for row in rows if row.unconfirmed_deadline_count),
        overdue_records=sum(1 for row in rows if row.overdue_deadline_count),
    )
    next_cursor = (
        _encode_cursor(rows[-1].updated_at, rows[-1].application_id) if has_more and rows else None
    )
    return IpPortfolioListResponse(
        rows=rows,
        counts=counts,
        filters=filters,
        limit=limit,
        next_cursor=next_cursor,
    )


def list_ip_portfolio_families(
    session: Session,
    *,
    context: SessionContext,
    grouping: str,
    filters: IpPortfolioFilters,
) -> IpPortfolioFamilyResponse:
    """IP-PROS-11 — group related applications without merging their identity.

    Grouping is presentational. Each member keeps its own application id,
    identifier, office, jurisdiction, filing phase and lifecycle version, and a
    family deliberately exposes no shared phase, deadline or identifier.
    """

    if grouping not in {"mark", "client"}:
        raise HTTPException(status_code=400, detail="grouping must be 'mark' or 'client'.")

    statement = _scoped_query(session, context=context, filters=filters)
    rows = list(session.execute(statement).all())

    visible = rows

    deadlines = _deadline_counts(
        session,
        company_id=context.company.id,
        docket_ids=[docket.id for _a, _s, docket in visible],
    )

    grouped: dict[str, dict] = {}
    ungrouped = 0
    for application, asset, docket in visible:
        if grouping == "mark":
            key = application.asset_id
            label = (asset.title if asset else None) or ""
        else:
            key = docket.matter_id
            # Label a client family from the Matter, not from whichever member
            # happens to be first; a docket title names one filing, not a client.
            matter = session.get(Matter, key) if key else None
            label = (getattr(matter, "title", None) or "") if matter else ""
        if not key:
            # A record with no mark or no client cannot be grouped; it is
            # counted rather than forced into a synthetic family.
            ungrouped += 1
            continue
        open_count, _unconfirmed, overdue = deadlines.get(docket.id, (0, 0, 0))
        bucket = grouped.setdefault(key, {"label": label, "members": []})
        if not bucket["label"]:
            bucket["label"] = label
        bucket["members"].append(
            IpPortfolioFamilyMember(
                application_id=application.id,
                docket_id=docket.id,
                asset_id=application.asset_id,
                office=application.office,
                jurisdiction=application.jurisdiction,
                filing_phase=application.filing_phase,
                lifecycle_version=application.lifecycle_version,
                primary_identifier=docket.primary_identifier,
                open_deadline_count=open_count,
                overdue_deadline_count=overdue,
            )
        )

    families = [
        IpPortfolioFamily(
            grouping=grouping,
            family_key=key,
            label=bucket["label"],
            member_count=len(bucket["members"]),
            distinct_jurisdictions=sorted(
                {m.jurisdiction for m in bucket["members"] if m.jurisdiction}
            ),
            distinct_filing_phases=sorted({m.filing_phase for m in bucket["members"]}),
            members=sorted(
                bucket["members"], key=lambda m: (m.jurisdiction or "", m.application_id)
            ),
        )
        for key, bucket in grouped.items()
    ]
    families.sort(key=lambda f: (-f.member_count, f.label, f.family_key))
    return IpPortfolioFamilyResponse(
        grouping=grouping, families=families, ungrouped_member_count=ungrouped
    )


__all__ = ["list_ip_portfolio", "list_ip_portfolio_families"]
