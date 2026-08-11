from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import AuditEvent
from caseops_api.schemas.audit import IpDocketAuditListResponse
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.matter_audit import matter_audit_record
from caseops_api.services.session_context import SessionContext


def list_ip_docket_audit_events(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    limit: int = 50,
    offset: int = 0,
) -> IpDocketAuditListResponse:
    """List only audit rows correlated to an already-authorized IP target."""

    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
    )
    safe_limit = min(max(limit, 1), 200)
    safe_offset = max(offset, 0)
    filters = (
        AuditEvent.company_id == context.company.id,
        AuditEvent.ip_docket_id == docket.id,
    )
    total = session.scalar(select(func.count(AuditEvent.id)).where(*filters)) or 0
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        )
    )
    return IpDocketAuditListResponse(
        ip_docket_id=docket.id,
        events=[matter_audit_record(event) for event in events],
        total=int(total),
        limit=safe_limit,
        offset=safe_offset,
    )


__all__ = ["list_ip_docket_audit_events"]
