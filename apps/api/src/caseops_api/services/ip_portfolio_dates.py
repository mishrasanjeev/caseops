"""One current-particular date reader and its equivalent bounded SQL predicates."""

from datetime import date

from sqlalchemy import Integer, and_, case, cast, func, literal, select, tuple_

from caseops_api.db.models import (
    AuditEvent,
    IpDocketRecord,
    IpImportRow,
    IpTrademarkParticularVersion,
)
from caseops_api.services.ip_coverage_read import _TERMINAL_DOCKET_STATUSES
from caseops_api.services.ip_import_source_status import (
    SOURCE_STATUS_ALIASES,
    source_status_key,
)
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
    audit_key = (
        AuditEvent.company_id,
        AuditEvent.action,
        AuditEvent.target_type,
        AuditEvent.target_id,
        AuditEvent.ip_docket_id,
    )
    # Seek one full-key successor; check exact identity outside the LIMIT fence.
    audit_candidate = (
        select(*audit_key)
        .where(
            tuple_(*audit_key)
            >= tuple_(
                IpDocketRecord.company_id,
                literal("ip_docket.source_materialized"),
                literal("ip_import_row"),
                IpImportRow.id,
                IpDocketRecord.id,
            )
        )
        .order_by(*audit_key)
        .correlate(IpDocketRecord, IpImportRow)
        .limit(1)
        .subquery()
    )
    audit_matches = (
        select(literal(1))
        .select_from(audit_candidate)
        .where(
            audit_candidate.c.company_id == IpDocketRecord.company_id,
            audit_candidate.c.action == "ip_docket.source_materialized",
            audit_candidate.c.target_type == "ip_import_row",
            audit_candidate.c.target_id == IpImportRow.id,
            audit_candidate.c.ip_docket_id == IpDocketRecord.id,
        )
        .correlate(IpDocketRecord, IpImportRow)
        .exists()
    )
    return (
        select(IpImportRow.id)
        .where(
            func.length(source_id) == 36,
            IpImportRow.id == source_id,
            IpImportRow.company_id == IpDocketRecord.company_id,
            audit_matches,
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


def raw_date_expression(field, *, data=None, imported_proven=None):
    if data is None:
        data = IpTrademarkParticularVersion.representation_json
    if imported_proven is None:
        imported_proven = imported_proof_expression()
    manual = data["portfolio_dates"][field]
    return case(
        (manual["origin"].as_string() == "manual", manual["value"].as_string()),
        (imported_proven, data["portfolio_import"][field].as_string()),
        else_=literal(None),
    )


def date_expression(field):
    return valid_iso_date_expression(raw_date_expression(field))


def _source_fact_stage(statement, *, name):
    # Distinct stage identities prevent nested CTE references from shadowing.
    return statement.cte(name=name, nesting=True).prefix_with("MATERIALIZED", dialect="postgresql")


def current_date_facts(candidates, *, company_id):
    """Resolve proof and safe current dates once for the already authorized scope."""
    scoped = _source_fact_stage(
        candidates.with_only_columns(
            IpDocketRecord.id.label("docket_id"), maintain_column_froms=True
        )
        .order_by(None)
        .distinct(),
        name="ip_date_scoped",
    )
    proof = _source_fact_stage(
        select(
            IpDocketRecord.id.label("docket_id"),
            IpTrademarkParticularVersion.id.label("version_id"),
            IpTrademarkParticularVersion.representation_json.label("data"),
            imported_proof_expression().label("import_proven"),
        )
        .select_from(IpDocketRecord)
        .join(scoped, scoped.c.docket_id == IpDocketRecord.id)
        .join(
            IpTrademarkParticularVersion,
            and_(
                IpTrademarkParticularVersion.company_id == IpDocketRecord.company_id,
                IpTrademarkParticularVersion.docket_id == IpDocketRecord.id,
                IpTrademarkParticularVersion.version == IpDocketRecord.current_version,
            ),
        )
        .where(IpDocketRecord.company_id == company_id),
        name="ip_date_proof",
    )
    raw = _source_fact_stage(
        select(
            proof.c.docket_id,
            proof.c.version_id,
            proof.c.import_proven,
            raw_date_expression(
                "application_date", data=proof.c.data, imported_proven=proof.c.import_proven
            ).label("application_raw"),
            raw_date_expression(
                "renewal_due_date", data=proof.c.data, imported_proven=proof.c.import_proven
            ).label("renewal_raw"),
        ),
        name="ip_date_raw",
    )
    return _source_fact_stage(
        select(
            raw.c.docket_id,
            raw.c.version_id,
            raw.c.import_proven,
            valid_iso_date_expression(raw.c.application_raw).label("application_on"),
            valid_iso_date_expression(raw.c.renewal_raw).label("renewal_due_on"),
        ),
        name="ip_date_validated",
    )


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
        version.docket_id: {
            **current_dates(
                session, version=version, docket_id=version.docket_id, imported_proven=proven
            ),
            **_declared_status(version, proven),
        }
        for version, proven in rows
    }


# Longest source Status wording shown back to the lawyer.
SOURCE_STATUS_TEXT_MAX = 120


def _declared_status(version, proven):
    """The import's declared source status (B4-ADJ-11), unverified legal state.

    ``source_status_text`` is the wording the source used; ``source_declared_status``
    is its recognised key, or None when the wording is not recognised. Imports
    made before the mapping kept only the wording, so the key is derived from it.
    """

    imported = (version.representation_json or {}).get("portfolio_import")
    if not proven or not isinstance(imported, dict):
        return {"source_declared_status": None, "source_status_text": None}
    raw = imported.get("source_status")
    text = " ".join(raw.split())[:SOURCE_STATUS_TEXT_MAX] if isinstance(raw, str) else ""
    declared = imported.get("declared_status")
    if declared not in set(SOURCE_STATUS_ALIASES.values()):
        declared = source_status_key(text) if text else None
    return {"source_declared_status": declared, "source_status_text": text or None}
