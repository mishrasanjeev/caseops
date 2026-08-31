from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import uuid4

from caseops_api.db.session import get_session_factory
from caseops_api.services.embeddings import build_provider
from caseops_api.services.private_retrieval_jobs import (
    DEFAULT_PRIVATE_EVENT_LAG_SLO_SECONDS,
    MAX_PRIVATE_MAINTENANCE_COMPANIES,
    inspect_private_index_integrity,
    list_private_maintenance_companies,
    process_pending_private_projection_events,
    rebuild_private_index,
)


def _integrity_payload(report) -> dict[str, object]:
    return {
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


def _maintain(
    *,
    max_companies: int,
    max_rebuilds: int,
    event_lag_slo_seconds: int,
) -> dict[str, object]:
    session_factory = get_session_factory()
    with session_factory() as session:
        candidates = list_private_maintenance_companies(
            session,
            limit=max_companies,
        )

    companies: list[dict[str, object]] = []
    blocked = candidates.truncated
    rebuild_count = 0
    repairable_blockers = {
        "missing_active_generation",
        "active_generation_manifest_mismatch",
        "orphan_or_stale_scopes",
        "stale_or_ineligible_sources",
    }
    for company_id in candidates.company_ids:
        try:
            with session_factory() as session:
                before = inspect_private_index_integrity(
                    session,
                    company_id=company_id,
                    event_lag_slo_seconds=event_lag_slo_seconds,
                )
                breached_before_recovery = (
                    before.oldest_pending_lag_seconds is not None
                    and before.oldest_pending_lag_seconds > event_lag_slo_seconds
                )
                applied = process_pending_private_projection_events(
                    session,
                    company_id=company_id,
                    commit_after_each_event=True,
                )
                session.commit()
                after = inspect_private_index_integrity(
                    session,
                    company_id=company_id,
                    event_lag_slo_seconds=event_lag_slo_seconds,
                )
                rebuilt = False
                if (
                    after.blockers
                    and set(after.blockers) <= repairable_blockers
                    and rebuild_count < max_rebuilds
                ):
                    rebuild_private_index(
                        session,
                        company_id=company_id,
                        activate=True,
                    )
                    session.commit()
                    rebuild_count += 1
                    rebuilt = True
                    after = inspect_private_index_integrity(
                        session,
                        company_id=company_id,
                        event_lag_slo_seconds=event_lag_slo_seconds,
                    )
                tenant_blocked = breached_before_recovery or after.release_blocked
                blocked = blocked or tenant_blocked
                companies.append(
                    {
                        "company_id": company_id,
                        "applied_event_count": len(applied),
                        "rebuilt": rebuilt,
                        "lag_slo_breached_before_recovery": breached_before_recovery,
                        "oldest_pending_lag_seconds_before": (
                            before.oldest_pending_lag_seconds
                        ),
                        "pending_event_count_after": after.pending_event_count,
                        "failed_event_count_after": after.failed_event_count,
                        "blockers_after": list(after.blockers),
                    }
                )
        except Exception as exc:
            # One corrupt or oversized tenant must not prevent unrelated
            # tenants from draining events. The job remains failed/alertable,
            # but deterministic Cloud Run task retries are disabled by the
            # scheduler inventory so this cannot become a lock-amplifying
            # retry storm.
            blocked = True
            companies.append(
                {
                    "company_id": company_id,
                    "applied_event_count": 0,
                    "rebuilt": False,
                    "error_code": type(exc).__name__[:80],
                    "blockers_after": ["tenant_maintenance_error"],
                }
            )
    return {
        "status": "blocked" if blocked else "ok",
        "release_blocked": blocked,
        "event_lag_slo_seconds": event_lag_slo_seconds,
        "candidate_company_count": len(candidates.company_ids),
        "candidate_scan_truncated": candidates.truncated,
        "rebuild_count": rebuild_count,
        "companies": companies,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded tenant-private projection operations."
    )
    parser.add_argument("--company-id")
    parser.add_argument(
        "--mode",
        choices=("integrity", "events", "rebuild", "maintain"),
        default="integrity",
    )
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--embed", action="store_true")
    parser.add_argument(
        "--max-companies",
        type=int,
        default=MAX_PRIVATE_MAINTENANCE_COMPANIES,
    )
    parser.add_argument(
        "--event-lag-slo-seconds",
        type=int,
        default=DEFAULT_PRIVATE_EVENT_LAG_SLO_SECONDS,
    )
    parser.add_argument("--max-rebuilds", type=int, default=5)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.mode != "maintain" and not args.company_id:
        parser.error("--company-id is required unless --mode=maintain")
    if not 1 <= args.max_companies <= MAX_PRIVATE_MAINTENANCE_COMPANIES:
        parser.error(f"--max-companies must be between 1 and {MAX_PRIVATE_MAINTENANCE_COMPANIES}")
    if not 1 <= args.event_lag_slo_seconds <= 86_400:
        parser.error("--event-lag-slo-seconds must be between 1 and 86400")
    if not 0 <= args.max_rebuilds <= 10:
        parser.error("--max-rebuilds must be between 0 and 10")

    correlation_id = str(uuid4())
    started_at = datetime.now(UTC)
    try:
        if args.mode == "maintain":
            payload = _maintain(
                max_companies=args.max_companies,
                max_rebuilds=args.max_rebuilds,
                event_lag_slo_seconds=args.event_lag_slo_seconds,
            )
        else:
            with get_session_factory()() as session:
                if args.mode == "events":
                    applied = process_pending_private_projection_events(
                        session,
                        company_id=args.company_id,
                        commit_after_each_event=True,
                    )
                    session.commit()
                    payload = {
                        "status": "ok",
                        "release_blocked": False,
                        "company_id": args.company_id,
                        "applied_event_count": len(applied),
                    }
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
                        "release_blocked": False,
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
                        event_lag_slo_seconds=args.event_lag_slo_seconds,
                    )
                    payload = {
                        "company_id": args.company_id,
                        **_integrity_payload(report),
                    }
    except Exception as exc:
        payload = {
            "status": "error",
            "release_blocked": True,
            "error_code": type(exc).__name__[:80],
        }

    payload.update(
        {
            "correlation_id": correlation_id,
            "mode": args.mode,
            "severity": "ERROR" if payload.get("release_blocked") else "INFO",
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
        }
    )
    print("CASEOPS_PRIVATE_PROJECTION " + json.dumps(payload, sort_keys=True))
    return 2 if payload.get("release_blocked") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
