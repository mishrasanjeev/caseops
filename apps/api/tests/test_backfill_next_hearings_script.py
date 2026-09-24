from __future__ import annotations

import json
from types import SimpleNamespace

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
    context = SimpleNamespace(company=SimpleNamespace(id="tenant-a"))
    pages = iter((50, 2))
    calls: list[int] = []

    monkeypatch.setattr(command, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(command, "_system_contexts", lambda _session: [context])

    def backfill(_session: FakeSession, *, context: object, limit: int) -> int:
        assert context is not None
        calls.append(limit)
        return next(pages)

    monkeypatch.setattr(command, "backfill_legacy_next_hearings", backfill)

    assert command.main() == 0
    assert calls == [50, 50]
    assert session.commits == 2
    assert session.rollbacks == 0
    line = capsys.readouterr().out.strip()
    assert json.loads(line.removeprefix("CASEOPS_HEARING_BACKFILL ")) == {
        "tenant_count": 1,
        "materialized": {"tenant-a": 52},
    }


def test_release_hearing_backfill_fails_when_more_than_ten_pages_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    context = SimpleNamespace(company=SimpleNamespace(id="tenant-a"))
    monkeypatch.setattr(command, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(command, "_system_contexts", lambda _session: [context])
    monkeypatch.setattr(
        command,
        "backfill_legacy_next_hearings",
        lambda _session, *, context, limit: 50 if limit == 50 else 1,
    )

    with pytest.raises(RuntimeError, match="exceeded its per-tenant release bound"):
        command.main()
    assert session.commits == 10
    assert session.rollbacks == 1
