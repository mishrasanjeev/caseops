"""Read-only source provenance for imported portfolio renewal reminders."""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    IpDocketRecord,
    IpImportRow,
    IpTrademarkParticularVersion,
    NotificationDeliveryIntent,
)


def _portfolio_source(representation: dict) -> dict:
    value = representation.get("portfolio_import")
    return value if isinstance(value, dict) else {}


def imported_renewal_reminder_is_current(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
) -> bool:
    """Source predicate for the shared delivery owner's pre-dispatch fence.

    This is not lifecycle or recipient authorization; those remain the shared
    owner's responsibility. A correction/removal of the source date denies
    this retained intent rather than interpreting it as a legal renewal.
    """
    if (
        intent.source_type != "ip_trademark_particular_version"
        or intent.event_type != "renewal_source_date_1month"
    ):
        return False
    pair = session.execute(
        select(IpTrademarkParticularVersion)
        .select_from(IpTrademarkParticularVersion)
        .join(
            IpDocketRecord,
            and_(
                IpDocketRecord.company_id == IpTrademarkParticularVersion.company_id,
                IpDocketRecord.id == intent.ip_docket_id,
                IpTrademarkParticularVersion.docket_id == IpDocketRecord.id,
                IpTrademarkParticularVersion.version == IpDocketRecord.current_version,
            ),
        )
        .where(
            IpTrademarkParticularVersion.id == intent.source_id,
            IpTrademarkParticularVersion.company_id == intent.company_id,
        )
    ).scalar_one_or_none()
    if pair is None:
        return False
    source = _portfolio_source(pair.representation_json)
    return bool(
        _imported_source_row(
            session, company_id=intent.company_id, docket_id=intent.ip_docket_id, source=source
        )
        and source.get("renewal_due_date") == (intent.metadata_json or {}).get("source_due_on")
        and source.get("renewal_due_date")
        and intent.schedule_source_type == "ip_portfolio_renewal"
        and intent.schedule_source_id == intent.ip_docket_id
    )


def _imported_source_row(session: Session, *, company_id: str, docket_id: str, source: dict):
    row_id = source.get("source_row_id")
    if not isinstance(row_id, str) or len(row_id) != 36:
        return None
    return session.scalar(
        select(IpImportRow).where(
            IpImportRow.company_id == company_id,
            IpImportRow.id == row_id,
            select(AuditEvent.id)
            .where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "ip_docket.source_materialized",
                AuditEvent.target_type == "ip_import_row",
                AuditEvent.target_id == IpImportRow.id,
                AuditEvent.ip_docket_id == docket_id,
            )
            .exists(),
        )
    )


__all__ = ["imported_renewal_reminder_is_current"]
