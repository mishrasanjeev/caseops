"""Current record-level stop conditions, shared by reads and dispatch."""

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import aliased

from caseops_api.db.models import (
    IpDeadline,
    IpDocketRecord,
    IpRenewalTerm,
    IpTrademarkParticularVersion,
    TrademarkApplication,
)


def source_stop_reason_expression(due):
    applications = (
        select(TrademarkApplication.id)
        .where(
            TrademarkApplication.company_id == IpDocketRecord.company_id,
            TrademarkApplication.docket_id == IpDocketRecord.id,
        )
        .correlate(IpDocketRecord)
    )
    active_application = applications.where(TrademarkApplication.is_active.is_(True)).exists()
    any_application = applications.exists()
    term, deadline = aliased(IpRenewalTerm), aliased(IpDeadline)
    latest_sequence = (
        select(func.max(term.term_sequence))
        .join(deadline, deadline.id == term.renewal_deadline_id)
        .where(
            term.company_id == IpDocketRecord.company_id,
            term.docket_id == IpDocketRecord.id,
            deadline.company_id == IpDocketRecord.company_id,
            cast(deadline.result_on, String) == due,
        )
        .correlate(IpDocketRecord, IpTrademarkParticularVersion)
        .scalar_subquery()
    )
    current_terms = (
        select(IpRenewalTerm.id)
        .join(IpDeadline, IpDeadline.id == IpRenewalTerm.renewal_deadline_id)
        .where(
            IpRenewalTerm.company_id == IpDocketRecord.company_id,
            IpRenewalTerm.docket_id == IpDocketRecord.id,
            IpDeadline.company_id == IpDocketRecord.company_id,
            cast(IpDeadline.result_on, String) == due,
            IpRenewalTerm.term_sequence == latest_sequence,
        )
        .correlate(IpDocketRecord, IpTrademarkParticularVersion)
    )
    stopped = or_(
        IpRenewalTerm.state.in_(("completed", "cancelled")),
        IpDeadline.state.in_(("completed", "cancelled")),
    )
    closed_current = current_terms.where(stopped).exists()
    active_current = current_terms.where(~stopped).exists()
    return case(
        (and_(any_application, ~active_application), "source_applications_terminal"),
        (and_(closed_current, active_current), "ambiguous_source_renewal_terms"),
        (closed_current, "source_renewal_completed_or_cancelled"),
        else_=None,
    )
