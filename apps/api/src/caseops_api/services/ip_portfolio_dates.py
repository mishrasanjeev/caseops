"""One current-particular date reader and its equivalent bounded SQL predicates."""

from datetime import date

from sqlalchemy import Integer, and_, case, cast, func, literal, select

from caseops_api.db.models import (
    AuditEvent,
    IpDocketRecord,
    IpImportRow,
    IpTrademarkParticularVersion,
)
from caseops_api.services.ip_coverage_read import _TERMINAL_DOCKET_STATUSES
from caseops_api.services.ip_portfolio_source import _imported_source_row


def docket_date_edit_operational(docket):
    return bool(
        docket.is_active
        and not docket.archived_by_matter_disposal
        and docket.status not in _TERMINAL_DOCKET_STATUSES
    )


def _date(value):
    try:
        return (
            date.fromisoformat(value)
            if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-"
            else None
        )
    except ValueError:
        return None


def current_dates(session, *, version, docket_id, imported_proven=None):
    representation = version.representation_json or {}
    imported = representation.get("portfolio_import")
    imported = imported if isinstance(imported, dict) else {}
    manual = representation.get("portfolio_dates")
    manual = manual if isinstance(manual, dict) else {}
    if imported_proven is None:
        imported_proven = bool(
            _imported_source_row(
                session, company_id=version.company_id, docket_id=docket_id, source=imported
            )
        )
    result = {"docket_id": docket_id, "current_version": version.version}
    for field, target, state in (
        ("application_date", "source_application_on", "source_application_state"),
        ("renewal_due_date", "source_renewal_due_on", "source_renewal_state"),
    ):
        correction = manual.get(field)
        if isinstance(correction, dict) and correction.get("origin") == "manual":
            value, origin = _date(correction.get("value")), "manual"
        else:
            value, origin = (
                _date(imported.get(field)) if imported_proven else None,
                "imported_unverified",
            )
            if field == "renewal_due_date" and isinstance(imported.get("date_correction"), dict):
                origin = "manual"
        result[target], result[state] = value, origin if value is not None else "missing"
    return result


def imported_proof_expression():
    source_id = IpTrademarkParticularVersion.representation_json["portfolio_import"][
        "source_row_id"
    ].as_string()
    return (
        select(IpImportRow.id)
        .where(
            func.length(source_id) == 36,
            IpImportRow.id == source_id,
            IpImportRow.company_id == IpDocketRecord.company_id,
            select(AuditEvent.id)
            .where(
                AuditEvent.company_id == IpDocketRecord.company_id,
                AuditEvent.action == "ip_docket.source_materialized",
                AuditEvent.target_type == "ip_import_row",
                AuditEvent.target_id == IpImportRow.id,
                AuditEvent.ip_docket_id == IpDocketRecord.id,
            )
            .correlate(IpDocketRecord, IpImportRow)
            .exists(),
        )
        .correlate(IpDocketRecord, IpTrademarkParticularVersion)
        .exists()
    )


def valid_iso_date_expression(raw):
    # Nested CASE prevents PostgreSQL casts from seeing malformed legacy JSON.
    digits = tuple("0123456789")
    shape = and_(
        func.length(raw) == 10,
        func.substr(raw, 5, 1) == "-",
        func.substr(raw, 8, 1) == "-",
        *(func.substr(raw, position, 1).in_(digits) for position in (1, 2, 3, 4, 6, 7, 9, 10)),
    )
    year, month, day = (
        cast(func.substr(raw, start, count), Integer) for start, count in ((1, 4), (6, 2), (9, 2))
    )
    leap = and_(year % 4 == 0, (year % 100 != 0) | (year % 400 == 0))
    last = case((month == 2, case((leap, 29), else_=28)), (month.in_((4, 6, 9, 11)), 30), else_=31)
    return case(
        (
            shape,
            case((and_(year.between(1, 9999), month.between(1, 12), day.between(1, last)), raw)),
        ),
        else_=None,
    )


def date_expression(field):
    data = IpTrademarkParticularVersion.representation_json
    manual = data["portfolio_dates"][field]
    raw = case(
        (manual["origin"].as_string() == "manual", manual["value"].as_string()),
        (imported_proof_expression(), data["portfolio_import"][field].as_string()),
        else_=literal(None),
    )
    return valid_iso_date_expression(raw)


def page_date_details(session, *, company_id, docket_ids):
    if not docket_ids:
        return {}
    rows = session.execute(
        select(IpTrademarkParticularVersion, imported_proof_expression())
        .join(
            IpDocketRecord,
            and_(
                IpDocketRecord.id == IpTrademarkParticularVersion.docket_id,
                IpDocketRecord.company_id == IpTrademarkParticularVersion.company_id,
                IpDocketRecord.current_version == IpTrademarkParticularVersion.version,
            ),
        )
        .where(IpDocketRecord.company_id == company_id, IpDocketRecord.id.in_(docket_ids))
    )
    return {
        version.docket_id: current_dates(
            session, version=version, docket_id=version.docket_id, imported_proven=proven
        )
        for version, proven in rows
    }
