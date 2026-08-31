from __future__ import annotations

from types import SimpleNamespace

from caseops_api.scripts import private_projection_integrity


class _WorkerSession:
    def __init__(self) -> None:
        self.commit_count = 0

    def __enter__(self) -> _WorkerSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commit_count += 1


def test_maintenance_releases_projection_locks_after_each_event(monkeypatch) -> None:
    sessions: list[_WorkerSession] = []
    process_calls: list[dict[str, object]] = []

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
            "blockers_after": [],
        },
    ]
