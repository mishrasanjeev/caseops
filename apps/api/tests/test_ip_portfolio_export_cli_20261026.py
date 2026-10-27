from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from caseops_api.workers import portfolio_exports as worker


@pytest.mark.parametrize("limit", [0, -1, 6])
def test_recovery_rejects_unbounded_work_before_reading_jobs(monkeypatch, limit):
    read = Mock(side_effect=AssertionError("Invalid recovery read jobs"))
    monkeypatch.setattr(worker, "list_recoverable_portfolio_exports", read)
    with pytest.raises(ValueError, match="one to five"):
        worker.run_once(limit=limit)
    read.assert_not_called()


@pytest.mark.parametrize("jobs", [["same", "same"], ["a", "b", "c"]])
def test_recovery_refuses_duplicate_or_excess_inventory_without_execution(monkeypatch, jobs):
    monkeypatch.setattr(worker, "list_recoverable_portfolio_exports", lambda **kwargs: jobs)
    run = Mock()
    monkeypatch.setattr(worker, "run_portfolio_export_job", run)
    with pytest.raises(RuntimeError, match="inventory"):
        worker.run_once(limit=2)
    run.assert_not_called()


def test_recovery_is_bounded_serial_and_reports_legacy_without_claiming_it(monkeypatch, capsys):
    read = Mock(return_value=["one", "two", "three", "four"])
    run = Mock(side_effect=["completed", "busy", "terminal", "missing"])
    monkeypatch.setattr(worker, "list_recoverable_portfolio_exports", read)
    monkeypatch.setattr(worker, "run_portfolio_export_job", run)
    monkeypatch.setattr(worker, "legacy_unresolved_exports", lambda: (2, False))
    assert worker.main(["--once", "--batch-size=4"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["selected"] == 4 and result["outcomes"] == {
        "completed": 1,
        "busy": 1,
        "terminal": 1,
        "missing": 1,
    }
    assert result["legacy_unresolved_capped_count"] == 2 and result["legacy_rows_claimed"] == 0
    assert [call.args[0] for call in run.call_args_list] == ["one", "two", "three", "four"]
    read.assert_called_once_with(limit=4)


@pytest.mark.parametrize("arguments", [[], ["--batch-size=5"], ["--once", "--batch-size=6"]])
def test_cli_requires_explicit_once_and_finite_batch(monkeypatch, arguments):
    run = Mock()
    monkeypatch.setattr(worker, "run_once", run)
    with pytest.raises(SystemExit) as error:
        worker.main(arguments)
    assert error.value.code == 2
    run.assert_not_called()


def test_unknown_worker_outcome_is_not_a_successful_recovery(monkeypatch):
    monkeypatch.setattr(worker, "list_recoverable_portfolio_exports", lambda **kwargs: ["job"])
    monkeypatch.setattr(worker, "run_portfolio_export_job", lambda _job: "unknown")
    with pytest.raises(RuntimeError, match="unknown outcome"):
        worker.run_once(limit=1)
