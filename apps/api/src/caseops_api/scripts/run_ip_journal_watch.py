from __future__ import annotations

import logging

from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_watch import run_journal_watch_scheduler

logger = logging.getLogger(__name__)


def main() -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        result = run_journal_watch_scheduler(session)
    logger.info(
        "journal watch due=%s checked=%s cost_paused=%s provider_paused=%s external_calls=%s",
        result.due_profiles,
        result.checked_profiles,
        result.cost_paused_profiles,
        result.provider_paused_profiles,
        result.external_calls,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
