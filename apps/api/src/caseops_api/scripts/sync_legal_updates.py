from __future__ import annotations

import logging

from caseops_api.core.settings import get_settings
from caseops_api.db.session import get_session_factory
from caseops_api.services.legal_update_sources import (
    sync_configured_legal_update_sources,
)

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    if not settings.legal_update_sync_enabled:
        logger.info("legal update sync disabled")
        return 0
    session_factory = get_session_factory()
    with session_factory() as session:
        runs = sync_configured_legal_update_sources(
            session,
            limit=settings.legal_update_sync_default_limit,
        )
        for run in runs:
            logger.info(
                "legal update sync source=%s status=%s fetched=%s created=%s changed=%s",
                run.source_key,
                run.status,
                run.fetched_count,
                run.created_count,
                run.changed_count,
            )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
