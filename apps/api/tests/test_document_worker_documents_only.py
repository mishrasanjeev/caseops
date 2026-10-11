from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

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
