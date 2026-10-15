"""Shared current docket, mark and identifier search without version-history scans."""

from sqlalchemy import and_, func, or_, select

from caseops_api.db.models import IpAsset, IpDocketRecord, IpIdentifier, TrademarkApplication
from caseops_api.services.ip_identifier_rules import normalize_ip_identifier


def portfolio_target_search_predicate(*, company_id, query):
    like = f"%{query.strip().lower()}%"
    mark_match = (
        select(TrademarkApplication.id)
        .join(
            IpAsset,
            and_(IpAsset.id == TrademarkApplication.asset_id, IpAsset.company_id == company_id),
        )
        .where(
            TrademarkApplication.company_id == company_id,
            TrademarkApplication.docket_id == IpDocketRecord.id,
            func.lower(IpAsset.title).like(like),
        )
        .correlate(IpDocketRecord)
        .exists()
    )
    identifier_match = (
        select(IpIdentifier.id)
        .where(
            IpIdentifier.company_id == company_id,
            IpIdentifier.docket_id == IpDocketRecord.id,
            IpIdentifier.effective_until.is_(None),
            IpIdentifier.superseded_by_identifier_id.is_(None),
            IpIdentifier.normalized_value == normalize_ip_identifier(query),
        )
        .correlate(IpDocketRecord)
        .exists()
    )
    return or_(func.lower(IpDocketRecord.title).like(like), mark_match, identifier_match)
