from __future__ import annotations

from types import SimpleNamespace

from caseops_api.scripts import private_projection_integrity
from caseops_api.services.private_retrieval import STALE_PRIVATE_PROJECTION_WRITER_DETAIL


class _WorkerSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    def __enter__(self) -> _WorkerSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1


def test_maintenance_releases_projection_locks_after_each_event(monkeypatch) -> None:
    sessions: list[_WorkerSession] = []
    process_calls: list[dict[str, object]] = []

    def session_factory() -> _WorkerSession:
        session = _WorkerSession()
        sessions.append(session)
        return session

    report = SimpleNamespace(
        active_generation_id="generation-1",
        oldest_pending_lag_seconds=None,
        oldest_repair_lag_seconds=None,
        blockers=(),
        release_blocked=False,
        pending_event_count=0,
        failed_event_count=0,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "list_private_maintenance_companies",
        lambda _session, *, limit: SimpleNamespace(
            company_ids=("company-1",),
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "inspect_private_index_integrity",
        lambda _session, **_kwargs: report,
    )

    def process(_session, **kwargs):
        process_calls.append(kwargs)
        return ("event-1", "event-2")

    monkeypatch.setattr(
        private_projection_integrity,
        "process_pending_private_projection_events",
        process,
    )

    result = private_projection_integrity._maintain(
        max_companies=1,
        max_rebuilds=0,
        event_lag_slo_seconds=60,
    )

    assert result["status"] == "ok"
    assert process_calls == [
        {
            "company_id": "company-1",
            "commit_after_each_event": True,
        }
    ]
    assert sessions[-1].commit_count == 1


def test_maintenance_isolates_one_tenant_failure_and_continues(monkeypatch) -> None:
    sessions: list[_WorkerSession] = []
    processed_companies: list[str] = []

    def session_factory() -> _WorkerSession:
        session = _WorkerSession()
        sessions.append(session)
        return session

    report = SimpleNamespace(
        oldest_pending_lag_seconds=None,
        blockers=(),
        release_blocked=False,
        pending_event_count=0,
        failed_event_count=0,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "get_session_factory",
        lambda: session_factory,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "list_private_maintenance_companies",
        lambda _session, *, limit: SimpleNamespace(
            company_ids=("broken-company", "healthy-company"),
            truncated=False,
        ),
    )

    def inspect(_session, *, company_id, **_kwargs):
        if company_id == "broken-company":
            raise RuntimeError("deterministic tenant failure")
        return report

    monkeypatch.setattr(
        private_projection_integrity,
        "inspect_private_index_integrity",
        inspect,
    )

    def process(_session, *, company_id, **_kwargs):
        processed_companies.append(company_id)
        return ()

    monkeypatch.setattr(
        private_projection_integrity,
        "process_pending_private_projection_events",
        process,
    )

    result = private_projection_integrity._maintain(
        max_companies=2,
        max_rebuilds=0,
        event_lag_slo_seconds=60,
    )

    assert result["status"] == "blocked"
    assert result["release_blocked"] is True
    assert processed_companies == ["healthy-company"]
    assert result["companies"] == [
        {
            "company_id": "broken-company",
            "applied_event_count": 0,
            "rebuilt": False,
            "error_code": "RuntimeError",
            "error_detail": (
                "Unexpected private projection maintenance failure; "
                "inspect correlated service logs."
            ),
            "blockers_after": ["tenant_maintenance_error"],
        },
        {
            "company_id": "healthy-company",
            "applied_event_count": 0,
            "rebuilt": False,
            "lag_slo_breached_before_recovery": False,
            "oldest_pending_lag_seconds_before": None,
            "pending_event_count_after": 0,
            "failed_event_count_after": 0,
            "repair_deferred": False,
            "repair_deferred_reason": None,
            "oldest_repair_lag_seconds_after": None,
            "repair_lag_slo_breached": False,
            "blockers_after": [],
        },
    ]


def test_maintenance_error_detail_redacts_unknown_exception_text() -> None:
    secret = "matter-secret-identifier"

    detail = private_projection_integrity._safe_error_detail(RuntimeError(secret))

    assert secret not in detail


def test_maintenance_error_detail_preserves_known_safe_capacity_message() -> None:
    safe_detail = private_projection_integrity.PRIVATE_REBUILD_LIMIT_DETAIL

    detail = private_projection_integrity._safe_error_detail(
        private_projection_integrity.PrivateRetrievalInvariantError(safe_detail)
    )

    assert detail == safe_detail


def test_maintenance_error_detail_preserves_typed_concurrency_message() -> None:
    detail = private_projection_integrity._safe_error_detail(
        private_projection_integrity.PrivateRetrievalConcurrencyError(
            STALE_PRIVATE_PROJECTION_WRITER_DETAIL
        )
    )

    assert detail == STALE_PRIVATE_PROJECTION_WRITER_DETAIL


def test_maintenance_retries_one_stale_rebuild_and_converges(monkeypatch) -> None:
    repairable = SimpleNamespace(
        active_generation_id="generation-1",
        oldest_pending_lag_seconds=None,
        oldest_repair_lag_seconds=0,
        blockers=("active_generation_manifest_mismatch",),
        release_blocked=True,
        pending_event_count=0,
        failed_event_count=0,
    )
    ready = SimpleNamespace(
        active_generation_id="generation-2",
        oldest_pending_lag_seconds=None,
        oldest_repair_lag_seconds=None,
        blockers=(),
        release_blocked=False,
        pending_event_count=0,
        failed_event_count=0,
    )
    reports = iter((repairable, repairable, repairable, ready))
    rebuild_calls = 0
    process_calls = 0

    monkeypatch.setattr(
        private_projection_integrity,
        "get_session_factory",
        lambda: _WorkerSession,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "list_private_maintenance_companies",
        lambda _session, *, limit: SimpleNamespace(
            company_ids=("company-1",),
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "inspect_private_index_integrity",
        lambda _session, **_kwargs: next(reports),
    )

    def process(_session, **_kwargs):
        nonlocal process_calls
        process_calls += 1
        return (f"event-{process_calls}",)

    def rebuild(_session, **_kwargs):
        nonlocal rebuild_calls
        rebuild_calls += 1
        if rebuild_calls == 1:
            raise private_projection_integrity.PrivateRetrievalConcurrencyError(
                STALE_PRIVATE_PROJECTION_WRITER_DETAIL
            )

    monkeypatch.setattr(
        private_projection_integrity,
        "process_pending_private_projection_events",
        process,
    )
    monkeypatch.setattr(private_projection_integrity, "rebuild_private_index", rebuild)

    result = private_projection_integrity._maintain(
        max_companies=1,
        max_rebuilds=1,
        event_lag_slo_seconds=60,
    )

    assert result["status"] == "ok"
    assert result["rebuild_count"] == 1
    assert result["companies"][0]["applied_event_count"] == 2
    assert result["companies"][0]["rebuilt"] is True
    assert rebuild_calls == 2
    assert process_calls == 2


def test_maintenance_defers_a_second_stale_rebuild_within_slo(monkeypatch) -> None:
    repairable = SimpleNamespace(
        active_generation_id="generation-1",
        oldest_pending_lag_seconds=None,
        oldest_repair_lag_seconds=59,
        blockers=("active_generation_manifest_mismatch",),
        release_blocked=True,
        pending_event_count=0,
        failed_event_count=0,
    )
    rebuild_calls = 0

    monkeypatch.setattr(
        private_projection_integrity,
        "get_session_factory",
        lambda: _WorkerSession,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "list_private_maintenance_companies",
        lambda _session, *, limit: SimpleNamespace(
            company_ids=("company-1",),
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "inspect_private_index_integrity",
        lambda _session, **_kwargs: repairable,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "process_pending_private_projection_events",
        lambda _session, **_kwargs: (),
    )

    def rebuild(_session, **_kwargs):
        nonlocal rebuild_calls
        rebuild_calls += 1
        raise private_projection_integrity.PrivateRetrievalConcurrencyError(
            STALE_PRIVATE_PROJECTION_WRITER_DETAIL
        )

    monkeypatch.setattr(private_projection_integrity, "rebuild_private_index", rebuild)

    result = private_projection_integrity._maintain(
        max_companies=1,
        max_rebuilds=1,
        event_lag_slo_seconds=60,
    )

    assert result["status"] == "ok"
    assert result["release_blocked"] is False
    assert result["companies"][0]["repair_deferred"] is True
    assert result["companies"][0]["repair_deferred_reason"] == (
        "concurrent_access_or_tombstone_change"
    )
    assert result["companies"][0]["blockers_after"] == ["active_generation_manifest_mismatch"]
    assert rebuild_calls == 2


def test_maintenance_blocks_a_deferred_repair_after_slo(monkeypatch) -> None:
    repairable = SimpleNamespace(
        active_generation_id="generation-1",
        oldest_pending_lag_seconds=None,
        oldest_repair_lag_seconds=301,
        blockers=("active_generation_manifest_mismatch",),
        release_blocked=True,
        pending_event_count=0,
        failed_event_count=0,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "get_session_factory",
        lambda: _WorkerSession,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "list_private_maintenance_companies",
        lambda _session, *, limit: SimpleNamespace(
            company_ids=("company-1",),
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "inspect_private_index_integrity",
        lambda _session, **_kwargs: repairable,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "process_pending_private_projection_events",
        lambda _session, **_kwargs: (),
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "rebuild_private_index",
        lambda _session, **_kwargs: (_ for _ in ()).throw(
            private_projection_integrity.PrivateRetrievalConcurrencyError(
                STALE_PRIVATE_PROJECTION_WRITER_DETAIL
            )
        ),
    )

    result = private_projection_integrity._maintain(
        max_companies=1,
        max_rebuilds=1,
        event_lag_slo_seconds=300,
    )

    assert result["status"] == "blocked"
    assert result["release_blocked"] is True
    assert result["companies"][0]["repair_deferred"] is True
    assert result["companies"][0]["repair_lag_slo_breached"] is True


def test_maintenance_does_not_retry_an_unknown_rebuild_failure(monkeypatch) -> None:
    repairable = SimpleNamespace(
        active_generation_id="generation-1",
        oldest_pending_lag_seconds=None,
        oldest_repair_lag_seconds=0,
        blockers=("active_generation_manifest_mismatch",),
        release_blocked=True,
        pending_event_count=0,
        failed_event_count=0,
    )
    rebuild_calls = 0

    monkeypatch.setattr(
        private_projection_integrity,
        "get_session_factory",
        lambda: _WorkerSession,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "list_private_maintenance_companies",
        lambda _session, *, limit: SimpleNamespace(
            company_ids=("company-1",),
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "inspect_private_index_integrity",
        lambda _session, **_kwargs: repairable,
    )
    monkeypatch.setattr(
        private_projection_integrity,
        "process_pending_private_projection_events",
        lambda _session, **_kwargs: (),
    )

    def rebuild(_session, **_kwargs):
        nonlocal rebuild_calls
        rebuild_calls += 1
        raise RuntimeError("unknown rebuild failure")

    monkeypatch.setattr(private_projection_integrity, "rebuild_private_index", rebuild)

    result = private_projection_integrity._maintain(
        max_companies=1,
        max_rebuilds=1,
        event_lag_slo_seconds=60,
    )

    assert result["status"] == "blocked"
    assert result["release_blocked"] is True
    assert result["companies"][0]["error_code"] == "RuntimeError"
    assert rebuild_calls == 1
