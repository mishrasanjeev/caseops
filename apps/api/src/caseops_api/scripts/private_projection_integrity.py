from __future__ import annotations

import argparse
import json
from collections.abc import Iterable

from caseops_api.db.session import get_session_factory
from caseops_api.services.embeddings import build_provider
from caseops_api.services.private_retrieval_jobs import (
    inspect_private_index_integrity,
    process_pending_private_projection_events,
    rebuild_private_index,
)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded tenant-private projection operation."
    )
    parser.add_argument("--company-id", required=True)
    parser.add_argument(
        "--mode",
        choices=("integrity", "events", "rebuild"),
        default="integrity",
    )
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--embed", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    with get_session_factory()() as session:
        if args.mode == "events":
            applied = process_pending_private_projection_events(
                session,
                company_id=args.company_id,
            )
            session.commit()
            payload = {"status": "ok", "applied_event_count": len(applied)}
        elif args.mode == "rebuild":
            summary = rebuild_private_index(
                session,
                company_id=args.company_id,
                provider=build_provider() if args.embed else None,
                activate=args.activate,
            )
            session.commit()
            payload = {
                "status": "ok",
                "company_id": summary.company_id,
                "generation_id": summary.generation_id,
                "projection_count": summary.projection_count,
                "provider_batch_count": summary.provider_batch_count,
                "activated": summary.activated,
            }
        else:
            report = inspect_private_index_integrity(
                session,
                company_id=args.company_id,
            )
            payload = {
                "status": report.state,
                "active_generation_id": report.active_generation_id,
                "live_projection_count": report.live_projection_count,
                "tombstoned_projection_count": report.tombstoned_projection_count,
                "pending_event_count": report.pending_event_count,
                "failed_event_count": report.failed_event_count,
                "oldest_pending_lag_seconds": report.oldest_pending_lag_seconds,
                "orphan_scope_count": report.orphan_scope_count,
                "stale_source_count": report.stale_source_count,
                "unsafe_tombstone_count": report.unsafe_tombstone_count,
                "generation_manifest_matches": report.generation_manifest_matches,
                "release_blocked": report.release_blocked,
                "blockers": list(report.blockers),
            }
    print("CASEOPS_PRIVATE_PROJECTION " + json.dumps(payload, sort_keys=True))
    return 2 if payload.get("release_blocked") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
