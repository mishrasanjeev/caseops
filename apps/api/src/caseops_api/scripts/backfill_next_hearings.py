"""Materialize legacy Matter dates without contacting a court-data provider."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import Company
from caseops_api.db.session import get_session_factory
from caseops_api.services.next_hearing import (
    backfill_legacy_next_hearings,
    count_legacy_next_hearings,
)

PAGE_SIZE = 50
MAX_ROWS_PER_TENANT = 2500
MAX_ROWS_PER_RELEASE = 10000
MAX_PAGES_PER_TENANT = MAX_ROWS_PER_TENANT // PAGE_SIZE


def _active_company_ids(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(Company.id).where(Company.is_active.is_(True)).order_by(Company.id)
        )
    )


def main() -> int:
    with get_session_factory()() as session:
        company_ids = _active_company_ids(session)
        backlog = {
            company_id: count_legacy_next_hearings(session, company_id=company_id)
            for company_id in company_ids
        }
        session.rollback()
        if any(count > MAX_ROWS_PER_TENANT for count in backlog.values()) or sum(
            backlog.values()
        ) > MAX_ROWS_PER_RELEASE:
            raise RuntimeError(
                "Legacy hearing backfill exceeds release bounds before any writes: "
                + json.dumps(backlog, sort_keys=True)
            )
        print(
            "CASEOPS_HEARING_BACKFILL_PREFLIGHT " + json.dumps(backlog, sort_keys=True),
            flush=True,
        )
        totals: dict[str, int] = {}
        processed = 0
        for company_id in company_ids:
            total = 0
            for _ in range(MAX_PAGES_PER_TENANT):
                count = backfill_legacy_next_hearings(
                    session, company_id=company_id, limit=PAGE_SIZE
                )
                if processed + count > MAX_ROWS_PER_RELEASE:
                    session.rollback()
                    raise RuntimeError(
                        "Legacy hearing backfill exceeded its release-wide write bound."
                    )
                session.commit()
                total += count
                processed += count
                if count < PAGE_SIZE:
                    break
            remaining = count_legacy_next_hearings(session, company_id=company_id)
            session.rollback()
            if remaining:
                raise RuntimeError(
                    "Legacy hearing backfill left eligible rows after bounded pages; "
                    "concurrent writers or locks may be active."
                )
            totals[company_id] = total
        final_remaining = {
            company_id: count_legacy_next_hearings(session, company_id=company_id)
            for company_id in company_ids
        }
        session.rollback()
        if any(final_remaining.values()):
            raise RuntimeError(
                "Legacy hearing backfill has new eligible rows after tenant passes: "
                + json.dumps(final_remaining, sort_keys=True)
            )
        print(
            "CASEOPS_HEARING_BACKFILL "
            + json.dumps(
                {"tenant_count": len(company_ids), "materialized": totals}, sort_keys=True
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
