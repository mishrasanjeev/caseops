from __future__ import annotations

import logging

from caseops_api.core.settings import get_settings
from caseops_api.db.session import get_session_factory
from caseops_api.services.case_tracking import poll_tracked_cases
from caseops_api.services.case_tracking_providers import CaseTrackingProviderUnavailable

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    if not settings.case_tracking_enabled:
        logger.info("case tracking polling disabled")
        return 0
    session_factory = get_session_factory()
    with session_factory() as session:
        try:
            runs = poll_tracked_cases(session)
        except CaseTrackingProviderUnavailable as exc:
            logger.info("case tracking provider unavailable: %s", exc)
            return 0
        for run in runs:
            logger.info(
                "case tracking poll company=%s status=%s checked=%s updates=%s errors=%s",
                run.company_id,
                run.status,
                run.checked_count,
                run.update_count,
                run.error_count,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
