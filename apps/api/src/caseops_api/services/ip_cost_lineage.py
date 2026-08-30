"""Shared query boundary for append-only IP cost lineage."""

from sqlalchemy import exists, select
from sqlalchemy.sql.elements import ColumnElement

from caseops_api.db.models import IpCostItem, IpCostItemCorrection


def active_ip_cost_predicate() -> ColumnElement[bool]:
    """Return the SQL condition that excludes voided or superseded sources.

    Consumers must never re-use a historical source merely because its immutable
    row still exists. Keeping this predicate shared prevents renewals, foreign
    associate spend, Madrid actions, and recordals from drifting away from the
    reconciliation/report definition of an active cost.
    """

    return ~exists(
        select(IpCostItemCorrection.id).where(
            IpCostItemCorrection.source_cost_item_id == IpCostItem.id
        )
    )


__all__ = ["active_ip_cost_predicate"]
