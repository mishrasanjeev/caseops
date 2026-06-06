from __future__ import annotations

import argparse
import logging

from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import (
    case_tracking_window_state,
    poll_tracked_cases,
    should_enforce_case_tracking_window,
)

logger = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Poll explicitly tracked/bookmarked court cases.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Allow a scheduled/provider polling run outside the configured "
            "daily refresh window. Intended for operator break-glass/local use."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    enforce_window = should_enforce_case_tracking_window(force=args.force)
    window = case_tracking_window_state()
    logger.info(
        "case tracking poll window timezone=%s start=%s end=%s local_now=%s inside=%s "
        "enforce=%s force=%s",
        window.timezone,
        window.window_start,
        window.window_end,
        window.local_now.isoformat(),
        window.inside_window,
        enforce_window,
        args.force,
    )
    session_factory = get_session_factory()
    with session_factory() as session:
        runs = poll_tracked_cases(
            session,
            enforce_window=enforce_window,
            force=args.force,
        )
        for run in runs:
            logger.info(
                "case tracking poll company=%s status=%s checked=%s updates=%s "
                "skipped=%s blocked=%s provider_calls=%s backlog=%s errors=%s",
                run.company_id,
                run.status,
                run.checked_count,
                run.update_count,
                run.skipped_count,
                run.blocked_count,
                run.provider_call_count,
                run.backlog_remaining_count,
                run.error_count,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
