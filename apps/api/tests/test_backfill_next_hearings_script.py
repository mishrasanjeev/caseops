from __future__ import annotations

import json

import pytest

from caseops_api.scripts import backfill_next_hearings as command


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_release_hearing_backfill_is_bounded_and_provider_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    session = FakeSession()
    pages = iter((50, 2))
    calls: list[int] = []

    monkeypatch.setattr(command, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(command, "_active_company_ids", lambda _session: ["tenant-a"])
    counts = iter((52, 0, 0))
    monkeypatch.setattr(
        command, "count_legacy_next_hearings", lambda *_args, **_kwargs: next(counts)
    )

    def backfill(_session: FakeSession, *, company_id: str, limit: int) -> int:
        assert company_id == "tenant-a"
        calls.append(limit)
        return next(pages)

    monkeypatch.setattr(command, "backfill_legacy_next_hearings", backfill)

    assert command.main() == 0
    assert calls == [50, 50]
    assert session.commits == 2
    assert session.rollbacks == 3
    preflight, result = capsys.readouterr().out.strip().splitlines()
    assert json.loads(preflight.removeprefix("CASEOPS_HEARING_BACKFILL_PREFLIGHT ")) == {
        "tenant-a": 52
    }
    assert json.loads(result.removeprefix("CASEOPS_HEARING_BACKFILL ")) == {
        "tenant_count": 1,
        "materialized": {"tenant-a": 52},
    }


def test_release_hearing_backfill_rejects_oversized_backlog_before_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    monkeypatch.setattr(command, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(command, "_active_company_ids", lambda _session: ["tenant-a"])
    monkeypatch.setattr(
        command, "count_legacy_next_hearings", lambda *_args, **_kwargs: 2501
    )
    monkeypatch.setattr(
        command,
        "backfill_legacy_next_hearings",
        lambda *_args, **_kwargs: pytest.fail("writer called"),
    )

    with pytest.raises(RuntimeError, match="before any writes"):
        command.main()
    assert session.commits == 0
    assert session.rollbacks == 1


def test_release_hearing_backfill_detects_remaining_rows_after_short_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    calls = iter((50, 1))
    monkeypatch.setattr(command, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(command, "_active_company_ids", lambda _session: ["tenant-a"])
    monkeypatch.setattr(
        command, "count_legacy_next_hearings", lambda *_args, **_kwargs: next(calls)
    )
    monkeypatch.setattr(
        command, "backfill_legacy_next_hearings", lambda *_args, **_kwargs: 49
    )

    with pytest.raises(RuntimeError, match="left eligible rows"):
        command.main()
    assert session.commits == 1
    assert session.rollbacks == 2


def test_release_hearing_backfill_rechecks_all_tenants_after_later_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    calls = iter((1, 0, 0, 0, 0, 1))
    monkeypatch.setattr(command, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(
        command, "_active_company_ids", lambda _session: ["tenant-a", "tenant-b"]
    )
    monkeypatch.setattr(
        command, "count_legacy_next_hearings", lambda *_args, **_kwargs: next(calls)
    )
    monkeypatch.setattr(
        command, "backfill_legacy_next_hearings", lambda *_args, **_kwargs: 0
    )

    with pytest.raises(RuntimeError, match="new eligible rows after tenant passes"):
        command.main()
    assert session.commits == 2
    assert session.rollbacks == 4


def test_release_hearing_backfill_caps_actual_writes_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    monkeypatch.setattr(command, "MAX_ROWS_PER_RELEASE", 50)
    monkeypatch.setattr(command, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(command, "_active_company_ids", lambda _session: ["tenant-a"])
    monkeypatch.setattr(
        command, "count_legacy_next_hearings", lambda *_args, **_kwargs: 50
    )
    pages = iter((50, 1))
    monkeypatch.setattr(
        command, "backfill_legacy_next_hearings", lambda *_args, **_kwargs: next(pages)
    )

    with pytest.raises(RuntimeError, match="release-wide write bound"):
        command.main()
    assert session.commits == 1
    assert session.rollbacks == 2
