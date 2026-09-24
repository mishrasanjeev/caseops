"""Materialize legacy Matter dates without contacting a court-data provider."""

from __future__ import annotations

import json

from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import _system_contexts
from caseops_api.services.next_hearing import backfill_legacy_next_hearings

PAGE_SIZE = 50
MAX_PAGES_PER_TENANT = 10


def main() -> int:
    with get_session_factory()() as session:
        contexts = _system_contexts(session)
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
            else:
                remaining = backfill_legacy_next_hearings(
                    session, context=context, limit=1
                )
                session.rollback()
                if remaining:
                    raise RuntimeError(
                        "Legacy hearing backfill exceeded its per-tenant release bound."
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
