"""Seed the machine-verified Indian Kanoon price schedule.

This is release configuration, not an operator approval workflow. The canonical
deployment runs it before traffic so licensed-source readiness cannot depend on
someone re-entering the public price list in the platform-admin UI.

CLI: ``python -m caseops_api.scripts.seed_indian_kanoon_costs``
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import ProviderCostCategory, ProviderCostProfile
from caseops_api.db.session import get_session_factory

logger = logging.getLogger("seed_indian_kanoon_costs")

PROVIDER = "indian-kanoon"
PRICING_URL = "https://api.indiankanoon.org/pricing/"
PRICING_CHECKED_AT = datetime(2026, 9, 3, tzinfo=UTC)
EVIDENCE_REF = f"{PRICING_URL} checked {PRICING_CHECKED_AT.date().isoformat()}"
PRICE_SCHEDULE_MINOR = {
    ProviderCostCategory.LEGAL_SOURCE_SEARCH: 50,
    ProviderCostCategory.LEGAL_SOURCE_DOCUMENT: 20,
    ProviderCostCategory.LEGAL_SOURCE_ORIGINAL_DOCUMENT: 50,
    ProviderCostCategory.LEGAL_SOURCE_FRAGMENT: 5,
    ProviderCostCategory.LEGAL_SOURCE_METADATA: 2,
}


def _seed(session: Session) -> tuple[int, int]:
    """Return ``(inserted, updated)`` after an idempotent price refresh."""

    inserted = updated = 0
    now = datetime.now(UTC)
    for category, amount in PRICE_SCHEDULE_MINOR.items():
        row = session.scalar(
            select(ProviderCostProfile).where(
                ProviderCostProfile.category == category,
                ProviderCostProfile.provider == PROVIDER,
                ProviderCostProfile.currency == "INR",
                ProviderCostProfile.evidence_ref == EVIDENCE_REF,
            )
        )
        if row is None:
            row = ProviderCostProfile(
                category=category,
                provider=PROVIDER,
                currency="INR",
                effective_from=PRICING_CHECKED_AT,
                created_at=now,
            )
            session.add(row)
            inserted += 1
        else:
            updated += 1

        row.unit_amount_minor = amount
        row.unit_amount_bps = None
        row.unit_label = "API request"
        row.effective_from = PRICING_CHECKED_AT
        row.effective_until = None
        row.status = "active"
        row.source = PRICING_URL
        row.tax_fee_notes = "Published INR price per successful API request."
        row.cost_basis = "actual"
        row.confidence_level = "high"
        row.evidence_ref = EVIDENCE_REF
        # Readiness uses the official source, dated evidence and confidence;
        # the legacy founder field is deliberately not a manual activation gate.
        row.founder_approval_status = "pending"
        row.approved_at = None
        row.approved_by_platform_admin_id = None
        row.notes = (
            "Release-owned Indian Kanoon price schedule; machine-verifiable "
            "and safe to refresh without an approval workflow."
        )
        row.updated_at = now

    session.commit()
    return inserted, updated


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with get_session_factory()() as session:
        inserted, updated = _seed(session)
    logger.info(
        "seed_indian_kanoon_costs: inserted=%d updated=%d",
        inserted,
        updated,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
