"""Materialize legacy Matter dates without contacting a court-data provider."""

from __future__ import annotations

import json

from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import _system_contexts
from caseops_api.services.next_hearing import (
    backfill_legacy_next_hearings,
    count_legacy_next_hearings,
)

PAGE_SIZE = 50
MAX_ROWS_PER_TENANT = 2500
MAX_ROWS_PER_RELEASE = 10000
MAX_PAGES_PER_TENANT = MAX_ROWS_PER_TENANT // PAGE_SIZE


def main() -> int:
    with get_session_factory()() as session:
        contexts = _system_contexts(session)
        backlog = {
            context.company.id: count_legacy_next_hearings(session, context=context)
            for context in contexts
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
        for context in contexts:
            total = 0
            for _ in range(MAX_PAGES_PER_TENANT):
                count = backfill_legacy_next_hearings(
                    session, context=context, limit=PAGE_SIZE
                )
                session.commit()
                total += count
                if count < PAGE_SIZE:
                    break
            remaining = count_legacy_next_hearings(session, context=context)
            session.rollback()
            if remaining:
                raise RuntimeError(
                    "Legacy hearing backfill left eligible rows after bounded pages; "
                    "concurrent writers or locks may be active."
                )
            totals[context.company.id] = total
        print(
            "CASEOPS_HEARING_BACKFILL "
            + json.dumps(
                {"tenant_count": len(contexts), "materialized": totals}, sort_keys=True
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
