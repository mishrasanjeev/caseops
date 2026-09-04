from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from caseops_api.db.session import get_session_factory
from caseops_api.services.embeddings import build_provider
from caseops_api.services.private_retrieval import (
    PrivateRetrievalConcurrencyError,
    PrivateRetrievalInvariantError,
)
from caseops_api.services.private_retrieval_jobs import (
    DEFAULT_PRIVATE_EVENT_LAG_SLO_SECONDS,
    MAX_PRIVATE_MAINTENANCE_COMPANIES,
    PRIVATE_REBUILD_LIMIT_DETAIL,
    inspect_private_index_integrity,
    list_private_maintenance_companies,
    process_pending_private_projection_events,
    rebuild_private_index,
)

_REDACTED_ERROR_DETAIL = (
    "Unexpected private projection maintenance failure; inspect correlated service logs."
)
_TRANSIENT_DATABASE_CONCURRENCY_DETAIL = (
    "A bounded database concurrency conflict deferred private projection maintenance."
)
_TRANSIENT_DATABASE_SQLSTATES = {
    "40P01": "database_deadlock_detected",
    "55P03": "database_lock_timeout",
}


def _safe_error_detail(exc: BaseException) -> str:
    detail = str(exc).strip()
    if isinstance(exc, PrivateRetrievalConcurrencyError):
        return detail
    if isinstance(exc, PrivateRetrievalInvariantError) and detail == PRIVATE_REBUILD_LIMIT_DETAIL:
        return detail
    return _REDACTED_ERROR_DETAIL


def _is_retryable_rebuild_conflict(exc: BaseException) -> bool:
    return isinstance(
        exc,
        PrivateRetrievalConcurrencyError,
    ) or _transient_database_concurrency_code(exc) is not None


def _transient_database_concurrency_code(exc: BaseException) -> str | None:
    """Classify only PostgreSQL's deadlock and lock-unavailable SQLSTATEs."""

    if not isinstance(exc, OperationalError):
        return None
    sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    return _TRANSIENT_DATABASE_SQLSTATES.get(str(sqlstate or ""))


def _integrity_payload(report) -> dict[str, object]:
    return {
        "status": report.state,
        "active_generation_id": report.active_generation_id,
        "live_projection_count": report.live_projection_count,
        "tombstoned_projection_count": report.tombstoned_projection_count,
        "pending_event_count": report.pending_event_count,
        "failed_event_count": report.failed_event_count,
        "oldest_pending_lag_seconds": report.oldest_pending_lag_seconds,
        "oldest_repair_lag_seconds": report.oldest_repair_lag_seconds,
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
        applied: tuple[str, ...] = ()
        rebuilt = False
        breached_before_recovery = False
        oldest_pending_lag_seconds_before: int | None = None
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
                oldest_pending_lag_seconds_before = before.oldest_pending_lag_seconds
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
                repair_deferred = False
                repair_deferred_reason: str | None = None
                if (
                    after.blockers
                    and set(after.blockers) <= repairable_blockers
                    and rebuild_count < max_rebuilds
                ):
                    for rebuild_attempt in range(2):
                        try:
                            rebuild_private_index(
                                session,
                                company_id=company_id,
                                activate=True,
                            )
                        except Exception as exc:
                            if not _is_retryable_rebuild_conflict(exc):
                                raise
                            # A concurrent rebuild or canonical mutation can win
                            # while this worker is between bounded transactions.
                            # Replan exactly once; a second conflict remains
                            # alertable instead of becoming an unbounded retry.
                            session.rollback()
                            retry_applied = process_pending_private_projection_events(
                                session,
                                company_id=company_id,
                                commit_after_each_event=True,
                            )
                            applied = tuple(dict.fromkeys((*applied, *retry_applied)))
                            session.commit()
                            after = inspect_private_index_integrity(
                                session,
                                company_id=company_id,
                                event_lag_slo_seconds=event_lag_slo_seconds,
                            )
                            if not after.blockers:
                                break
                            if not set(after.blockers) <= repairable_blockers:
                                raise
                            if rebuild_attempt:
                                # The active generation remains fail-closed and
                                # the failed shadow has already been removed.
                                # Do not turn expected interactive writer
                                # progress into a release failure while this
                                # repair remains inside its bounded SLO. The
                                # next cadence replans from canonical state.
                                repair_deferred = True
                                repair_deferred_reason = (
                                    "concurrent_database_lock"
                                    if _transient_database_concurrency_code(exc) is not None
                                    else "concurrent_access_or_tombstone_change"
                                )
                                break
                            continue
                        session.commit()
                        rebuild_count += 1
                        rebuilt = True
                        break
                    after = inspect_private_index_integrity(
                        session,
                        company_id=company_id,
                        event_lag_slo_seconds=event_lag_slo_seconds,
                    )
                oldest_repair_lag_seconds = getattr(
                    after,
                    "oldest_repair_lag_seconds",
                    None,
                )
                repair_lag_slo_breached = (
                    oldest_repair_lag_seconds is not None
                    and oldest_repair_lag_seconds > event_lag_slo_seconds
                )
                deferred_within_slo = (
                    repair_deferred
                    and getattr(after, "active_generation_id", None) is not None
                    and bool(after.blockers)
                    and set(after.blockers) <= repairable_blockers
                    and not repair_lag_slo_breached
                )
                tenant_blocked = breached_before_recovery or (
                    after.release_blocked and not deferred_within_slo
                )
                blocked = blocked or tenant_blocked
                companies.append(
                    {
                        "company_id": company_id,
                        "applied_event_count": len(applied),
                        "rebuilt": rebuilt,
                        "lag_slo_breached_before_recovery": breached_before_recovery,
                        "oldest_pending_lag_seconds_before": oldest_pending_lag_seconds_before,
                        "pending_event_count_after": after.pending_event_count,
                        "failed_event_count_after": after.failed_event_count,
                        "repair_deferred": repair_deferred,
                        "repair_deferred_reason": repair_deferred_reason,
                        "oldest_repair_lag_seconds_after": oldest_repair_lag_seconds,
                        "repair_lag_slo_breached": repair_lag_slo_breached,
                        "blockers_after": list(after.blockers),
                    }
                )
        except Exception as exc:
            transient_code = _transient_database_concurrency_code(exc)
            if transient_code is not None:
                # The failed transaction is unusable. Re-inspect from a fresh
                # session and defer only while the active generation remains
                # intact, every blocker is machine-repairable, and neither
                # event nor repair age has crossed the bounded SLO.
                try:
                    with session_factory() as recovery_session:
                        after = inspect_private_index_integrity(
                            recovery_session,
                            company_id=company_id,
                            event_lag_slo_seconds=event_lag_slo_seconds,
                        )
                except Exception:
                    after = None
                if after is not None:
                    oldest_repair_lag_seconds = getattr(
                        after,
                        "oldest_repair_lag_seconds",
                        None,
                    )
                    pending_lag_slo_breached = (
                        after.oldest_pending_lag_seconds is not None
                        and after.oldest_pending_lag_seconds > event_lag_slo_seconds
                    )
                    repair_lag_slo_breached = (
                        oldest_repair_lag_seconds is not None
                        and oldest_repair_lag_seconds > event_lag_slo_seconds
                    )
                    safe_to_defer = (
                        not breached_before_recovery
                        and getattr(after, "active_generation_id", None) is not None
                        and after.pending_event_count == 0
                        and after.failed_event_count == 0
                        and set(after.blockers) <= repairable_blockers
                        and not pending_lag_slo_breached
                        and not repair_lag_slo_breached
                    )
                    if safe_to_defer:
                        companies.append(
                            {
                                "company_id": company_id,
                                "applied_event_count": len(applied),
                                "rebuilt": rebuilt,
                                "error_code": transient_code,
                                "error_detail": _TRANSIENT_DATABASE_CONCURRENCY_DETAIL,
                                "lag_slo_breached_before_recovery": False,
                                "oldest_pending_lag_seconds_before": (
                                    oldest_pending_lag_seconds_before
                                ),
                                "pending_event_count_after": after.pending_event_count,
                                "failed_event_count_after": after.failed_event_count,
                                "repair_deferred": True,
                                "repair_deferred_reason": "concurrent_database_lock",
                                "oldest_repair_lag_seconds_after": (
                                    oldest_repair_lag_seconds
                                ),
                                "repair_lag_slo_breached": False,
                                "blockers_after": list(after.blockers),
                            }
                        )
                        continue
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
                    "error_detail": _safe_error_detail(exc),
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
            "error_detail": _safe_error_detail(exc),
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
