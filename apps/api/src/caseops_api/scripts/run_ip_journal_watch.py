from __future__ import annotations

import logging

from caseops_api.db.session import get_session_factory
from caseops_api.services.ip_journal_feed import run_ip_india_journal_feed
from caseops_api.services.ip_watch import run_journal_watch_scheduler

logger = logging.getLogger(__name__)


def main() -> int:
    session_factory = get_session_factory()
    with session_factory() as session:
        result = run_journal_watch_scheduler(session)
    logger.info(
        "journal watch due=%s checked=%s cost_paused=%s provider_paused=%s "
        "manual_only=%s external_calls=%s",
        result.due_profiles,
        result.checked_profiles,
        result.cost_paused_profiles,
        result.provider_paused_profiles,
        result.manual_profiles,
        result.external_calls,
    )
    # The public Trade Marks Journal feed: off unless the platform kill switch
    # and at least one workspace setting are on.
    with session_factory() as session:
        feed = run_ip_india_journal_feed(session)
    logger.info(
        "journal feed status=%s listing_checked=%s check=%s/%s discovered=%s fetched=%s "
        "failed=%s entries=%s review=%s requests=%s workspaces=%s hits=%s",
        feed.status,
        feed.listing_checked,
        feed.check_status,
        feed.check_reason,
        feed.documents_discovered,
        feed.documents_fetched,
        feed.documents_failed,
        feed.entries_stored,
        feed.review_entries,
        feed.external_requests,
        feed.workspace_runs,
        feed.hits_created,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
