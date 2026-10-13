from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.services import document_jobs
from caseops_api.workers import document_processor as worker


@pytest.fixture
def document_worker_settings(monkeypatch):
    settings = SimpleNamespace(
        env="local", auto_migrate=True, document_worker_batch_size=5,
        document_worker_poll_interval_seconds=10, document_processing_stale_after_minutes=15,
        document_retry_after_hours=24, document_reindex_after_hours=24,
        document_reprocessing_batch_size=5, court_sync_worker_batch_size=5,
        court_sync_stale_after_minutes=15,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    return settings


@pytest.fixture
def forbid_worker_database_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Disabled or invalid admission performed database or sibling work")

    for name in (
        "run_migrations", "run_worker_iteration", "drain_matter_court_sync_jobs",
        "recover_stale_matter_court_sync_jobs", "enqueue_scheduled_document_reprocessing",
        "drain_update_summaries", "recover_stale_document_processing_jobs",
        "drain_document_processing_jobs",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    event.listen(Engine, "before_cursor_execute", forbidden)
    try:
        yield
    finally:
        event.remove(Engine, "before_cursor_execute", forbidden)


@pytest.mark.parametrize("skip_migrations", [False, True])
@pytest.mark.parametrize("env", ["local", "production"])
def test_documents_only_recovers_and_drains_only_documents(
    monkeypatch, capsys, skip_migrations, env, document_worker_settings,
):
    calls = []
    document_worker_settings.env = env
    if env == "production":
        document_worker_settings.document_worker_admission_protocol_version = 1
        document_worker_settings.document_worker_admission_enabled = True
    for name in ("run_migrations", "run_worker_iteration", "drain_matter_court_sync_jobs",
                 "recover_stale_matter_court_sync_jobs", "enqueue_scheduled_document_reprocessing",
                 "drain_update_summaries"):
        monkeypatch.setattr(worker, name, lambda **_: pytest.fail("Sibling work was invoked"))
    monkeypatch.setattr(worker, "recover_stale_document_processing_jobs",
                        lambda **kw: calls.append(("recover", kw)) or 1)
    def drain(**kwargs):
        calls.append(("drain", kwargs))
        kwargs["outcomes"].update({"completed": 1, "failed": 1})
        return 2

    monkeypatch.setattr(worker, "drain_document_processing_jobs", drain)
    args = ["--documents-only", "--once", "--batch-size", "5"]
    if skip_migrations:
        args.append("--skip-migrations")
    assert worker.main(args) == 0
    assert calls == [("recover", {"stale_after_minutes": 15, "limit": 5}),
                     ("drain", {"limit": 5, "outcomes": {"completed": 1, "failed": 1}})]
    output = capsys.readouterr().out
    assert "admission_protocol=1 admission=enabled" in output
    assert "recovered=1 queued=0 attempted=2 completed=1 failed=1 unfinalized=0" in output
    assert "court_sync_processed=0 case_summaries_processed=0" in output


@pytest.mark.parametrize("env", ["local", "production", "cloud", "unknown-profile"])
@pytest.mark.parametrize("disabled_by", ["setting", "cli"])
def test_disabled_admission_exits_before_any_database_work(
    capsys, document_worker_settings, forbid_worker_database_work, env, disabled_by,
):
    document_worker_settings.env = env
    document_worker_settings.document_worker_admission_protocol_version = 1
    document_worker_settings.document_worker_admission_enabled = disabled_by != "setting"
    args = ["--documents-only", "--once"]
    if disabled_by == "cli":
        args.append("--admission-disabled")
    assert worker.main(args) == 0
    assert capsys.readouterr().out.strip() == (
        "CaseOps document worker: admission_protocol=1 admission=disabled "
        "recovered=0 queued=0 attempted=0 completed=0 failed=0 unfinalized=0 "
        "court_sync_recovered=0 court_sync_processed=0 case_summaries_processed=0"
    )


@pytest.mark.parametrize("env", ["production", "cloud", "unknown-profile"])
@pytest.mark.parametrize("configuration", ["missing", "protocol-only", "admission-only"])
def test_non_local_missing_admission_configuration_fails_closed(
    capsys, document_worker_settings, forbid_worker_database_work, env, configuration,
):
    document_worker_settings.env = env
    if configuration == "protocol-only":
        document_worker_settings.document_worker_admission_protocol_version = 1
    elif configuration == "admission-only":
        document_worker_settings.document_worker_admission_enabled = False
    with pytest.raises(SystemExit) as failure:
        worker.main(["--documents-only", "--once"])
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "requires explicit admission and protocol 1" in output.err


@pytest.mark.parametrize("env", ["local", "production"])
@pytest.mark.parametrize("protocol", [0, 2])
def test_admission_protocol_validation_precedes_disabled_gate(
    capsys, document_worker_settings, forbid_worker_database_work, env, protocol,
):
    document_worker_settings.env = env
    document_worker_settings.document_worker_admission_protocol_version = protocol
    document_worker_settings.document_worker_admission_enabled = False
    if env == "local" and protocol == 0:
        assert worker.main(["--documents-only", "--once"]) == 0
        assert "admission=disabled" in capsys.readouterr().out
    else:
        with pytest.raises(SystemExit) as failure:
            worker.main(["--documents-only", "--once", "--admission-disabled"])
        assert failure.value.code == 2
        assert capsys.readouterr().out == ""


def test_regular_local_mode_is_unchanged_by_document_only_admission(
    monkeypatch, document_worker_settings,
):
    document_worker_settings.auto_migrate = False
    document_worker_settings.document_worker_admission_enabled = False
    document_worker_settings.document_worker_admission_protocol_version = 0
    calls = []
    monkeypatch.setattr(worker, "run_worker_iteration", lambda **kw: (
        calls.append(kw) or worker.WorkerRunSummary(0, 0, 0, 0, 0)
    ))
    assert worker.main(["--once"]) == 0
    assert len(calls) == 1


def test_local_cli_disabled_supports_missing_optional_admission_settings(
    capsys, document_worker_settings, forbid_worker_database_work,
):
    assert worker.main(["--documents-only", "--once", "--admission-disabled"]) == 0
    assert "admission_protocol=1 admission=disabled" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--documents-only"],
    ["--admission-disabled", "--once"],
    ["--documents-only", "--once", "--batch-size", "0"],
    ["--documents-only", "--once", "--batch-size", "101"]])
def test_documents_only_requires_once_and_bounded_work(args):
    with pytest.raises(SystemExit) as failure:
        worker.main(args)
    assert failure.value.code == 2


@pytest.fixture
def no_paid_worker_context():
    marker = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
    try:
        yield
    finally:
        reset_automated_test_request(marker)


@pytest.mark.parametrize("env", ["local", "production"])
@pytest.mark.parametrize("batch_size", [1, 5, 6, 100])
def test_documents_only_caps_real_recovery_without_reducing_drain(
    monkeypatch, capsys, document_worker_settings, no_paid_worker_context, env, batch_size,
):
    document_worker_settings.env = env
    document_worker_settings.document_worker_admission_protocol_version = 1
    document_worker_settings.document_worker_admission_enabled = True
    assert worker.recover_stale_document_processing_jobs is (
        document_jobs.recover_stale_document_processing_jobs
    )
    assert document_jobs.MAX_DOCUMENT_JOB_RECOVERY_BATCH == 5
    session = Mock(spec=Session)
    session.scalars.return_value = []
    session_factory = Mock(return_value=session)
    monkeypatch.setattr(document_jobs, "get_session_factory", lambda: session_factory)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Documents-only invoked migrations, sibling work or a database transport")

    for name in (
        "run_migrations", "run_worker_iteration", "drain_matter_court_sync_jobs",
        "recover_stale_matter_court_sync_jobs", "enqueue_scheduled_document_reprocessing",
        "drain_update_summaries",
    ):
        monkeypatch.setattr(worker, name, forbidden)
    drain_calls = []

    def drain(*, limit, outcomes):
        assert paid_providers_blocked_for_request()
        drain_calls.append((limit, dict(outcomes)))
        return 0

    monkeypatch.setattr(worker, "drain_document_processing_jobs", drain)
    event.listen(Engine, "before_cursor_execute", forbidden)
    try:
        assert worker.main([
            "--documents-only", "--once", "--batch-size", str(batch_size),
        ]) == 0
    finally:
        event.remove(Engine, "before_cursor_execute", forbidden)

    session_factory.assert_called_once_with()
    session.scalars.assert_called_once()
    session.close.assert_called_once_with()
    session.commit.assert_not_called()
    statement = session.scalars.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert compiled.params["param_1"] == min(batch_size, 5)
    assert "FOR UPDATE OF document_processing_jobs SKIP LOCKED" in str(compiled)
    assert drain_calls == [(batch_size, {})]
    assert paid_providers_blocked_for_request()
    assert capsys.readouterr().out.strip() == (
        "CaseOps document worker: admission_protocol=1 admission=enabled "
        "recovered=0 queued=0 attempted=0 completed=0 failed=0 unfinalized=0 "
        "court_sync_recovered=0 court_sync_processed=0 case_summaries_processed=0"
    )


@pytest.mark.parametrize("env", ["local", "production"])
@pytest.mark.parametrize("disabled_by", ["setting", "cli"])
@pytest.mark.parametrize("batch_size", [1, 5, 6, 100])
def test_documents_only_batch_boundary_keeps_disabled_admission_inert(
    capsys, document_worker_settings, forbid_worker_database_work,
    env, disabled_by, batch_size,
):
    document_worker_settings.env = env
    document_worker_settings.document_worker_admission_protocol_version = 1
    document_worker_settings.document_worker_admission_enabled = disabled_by != "setting"
    args = ["--documents-only", "--once", "--batch-size", str(batch_size)]
    if disabled_by == "cli":
        args.append("--admission-disabled")
    assert worker.main(args) == 0
    assert capsys.readouterr().out.strip() == (
        "CaseOps document worker: admission_protocol=1 admission=disabled "
        "recovered=0 queued=0 attempted=0 completed=0 failed=0 unfinalized=0 "
        "court_sync_recovered=0 court_sync_processed=0 case_summaries_processed=0"
    )


@pytest.mark.parametrize("env", ["local", "production"])
@pytest.mark.parametrize("admission", ["enabled", "setting", "cli"])
@pytest.mark.parametrize("batch_size", [1, 5, 6, 100])
def test_documents_only_batch_boundary_still_requires_once(
    capsys, document_worker_settings, forbid_worker_database_work,
    env, admission, batch_size,
):
    document_worker_settings.env = env
    document_worker_settings.document_worker_admission_protocol_version = 1
    document_worker_settings.document_worker_admission_enabled = admission != "setting"
    args = ["--documents-only", "--batch-size", str(batch_size)]
    if admission == "cli":
        args.append("--admission-disabled")
    with pytest.raises(SystemExit) as failure:
        worker.main(args)
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "--documents-only requires --once" in output.err


@pytest.mark.parametrize("env", ["local", "production"])
@pytest.mark.parametrize("admission", ["enabled", "setting", "cli"])
@pytest.mark.parametrize("once", [False, True])
def test_documents_only_oversized_batch_rejects_before_admission_or_work(
    capsys, document_worker_settings, forbid_worker_database_work, env, admission, once,
):
    document_worker_settings.env = env
    document_worker_settings.document_worker_admission_protocol_version = 1
    document_worker_settings.document_worker_admission_enabled = admission != "setting"
    args = ["--documents-only", "--batch-size", "101"]
    if once:
        args.append("--once")
    if admission == "cli":
        args.append("--admission-disabled")
    with pytest.raises(SystemExit) as failure:
        worker.main(args)
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "argument --batch-size: invalid choice: '101'" in output.err, output.err


class _StopWorkerLoop(Exception):
    pass


@pytest.mark.parametrize("batch_size", [1, 5, 6, 100])
@pytest.mark.parametrize("once", [False, True])
def test_regular_worker_batch_boundary_preserves_once_and_continuous_modes(
    monkeypatch, capsys, document_worker_settings, no_paid_worker_context, batch_size, once,
):
    document_worker_settings.auto_migrate = False
    document_worker_settings.document_worker_admission_enabled = False
    document_worker_settings.document_worker_admission_protocol_version = 0
    calls = []

    def iteration(**kwargs):
        assert paid_providers_blocked_for_request()
        calls.append(kwargs)
        return worker.WorkerRunSummary(0, 0, 0, 0, 0)

    sleep_calls = []

    def sleep(seconds):
        sleep_calls.append(seconds)
        raise _StopWorkerLoop

    monkeypatch.setattr(worker, "run_worker_iteration", iteration)
    monkeypatch.setattr(worker.time, "sleep", sleep)
    args = ["--batch-size", str(batch_size)]
    if once:
        args.append("--once")
        assert worker.main(args) == 0
        assert sleep_calls == []
    else:
        with pytest.raises(_StopWorkerLoop):
            worker.main(args)
        assert sleep_calls == [document_worker_settings.document_worker_poll_interval_seconds]
    assert len(calls) == 1
    assert calls[0]["batch_size"] == batch_size
    assert calls[0]["stale_after_minutes"] == 15
    assert paid_providers_blocked_for_request()
    output = capsys.readouterr().out
    assert "processed=0" in output
    assert "admission_protocol=" not in output
