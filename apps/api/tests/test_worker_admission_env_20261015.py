"""Real Settings environment loading at the two worker admission boundaries."""

import os
import socket
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Engine

from caseops_api.core import settings as settings_module
from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE,
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.db import migrations
from caseops_api.services import case_tracking_summary, court_sync_jobs, document_jobs
from caseops_api.workers import court_sync, document_processor

WORKERS = ("document", "court_sync")


@pytest.fixture
def real_worker_environment(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith("CASEOPS_") and not name.startswith("CASEOPS_TEST_RESULT_JOURNAL"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CASEOPS_ENV", "cloud")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", uuid4().hex + uuid4().hex)
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    settings_module.get_settings.cache_clear()
    marker = set_automated_test_request(NO_PAID_PROVIDERS_VALUE)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Worker startup crossed a database or network boundary")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for module, names in (
        (migrations, ("run_migrations",)),
        (document_processor, ("run_worker_iteration",)),
        (case_tracking_summary, ("drain_update_summaries",)),
        (document_jobs, (
            "enqueue_scheduled_document_reprocessing", "recover_stale_document_processing_jobs",
            "drain_document_processing_jobs",
        )),
        (court_sync_jobs, (
            "get_session_factory", "recover_stale_matter_court_sync_jobs",
            "drain_matter_court_sync_jobs",
        )),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    try:
        yield
    finally:
        reset_automated_test_request(marker)
        settings_module.get_settings.cache_clear()


def _configure(monkeypatch, worker, protocol, admission="false"):
    monkeypatch.setenv(f"CASEOPS_{worker.upper()}_WORKER_ADMISSION_PROTOCOL_VERSION", protocol)
    monkeypatch.setenv(f"CASEOPS_{worker.upper()}_WORKER_ADMISSION_ENABLED", admission)


def _main(worker):
    module = document_processor if worker == "document" else court_sync
    assert module.get_settings is settings_module.get_settings
    return module.main


def _args(worker):
    return (["--documents-only"] if worker == "document" else []) + [
        "--once", "--skip-migrations",
    ]


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("protocol", ["0", "1"])
def test_settings_loads_canonical_protocol_environment_strings(
    monkeypatch, real_worker_environment, worker, protocol,
):
    _configure(monkeypatch, worker, protocol)
    actual = getattr(settings_module.get_settings(), f"{worker}_worker_admission_protocol_version")
    assert type(actual) is int
    assert actual == int(protocol)


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("disable_by", ["setting", "cli"])
def test_real_env_protocol_one_starts_disabled_cli_without_sql_or_network(
    monkeypatch, real_worker_environment, capsys, worker, disable_by,
):
    _configure(monkeypatch, worker, "1", "false" if disable_by == "setting" else "true")
    args = _args(worker) + (["--admission-disabled"] if disable_by == "cli" else [])
    assert _main(worker)(args) == 0
    output = capsys.readouterr().out
    assert "admission_protocol=1 admission=disabled" in output
    assert "attempted=0 completed=0 failed=0 unfinalized=0" in output
    assert paid_providers_blocked_for_request()


@pytest.mark.parametrize("worker", WORKERS)
def test_real_env_protocol_zero_does_not_bypass_cloud_admission(
    monkeypatch, real_worker_environment, capsys, worker,
):
    _configure(monkeypatch, worker, "0")
    with pytest.raises(SystemExit) as failure:
        _main(worker)(_args(worker) + ["--admission-disabled"])
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "protocol 1" in output.err


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize(
    "protocol", ["2", "-1", "true", "false", "01", "+1", "1.0", " 1", "1 ", "unknown"],
)
def test_invalid_environment_protocol_rejected_before_disabled_cli(
    monkeypatch, real_worker_environment, worker, protocol,
):
    _configure(monkeypatch, worker, protocol)
    with pytest.raises(ValidationError) as failure:
        _main(worker)(_args(worker) + ["--admission-disabled"])
    assert failure.value.errors(include_input=False)[0]["loc"] == (
        f"{worker}_worker_admission_protocol_version",
    )


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("protocol", [0, 1])
def test_settings_preserves_documented_integer_protocols(real_worker_environment, worker, protocol):
    settings = settings_module.Settings(**{f"{worker}_worker_admission_protocol_version": protocol})
    assert getattr(settings, f"{worker}_worker_admission_protocol_version") == protocol


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("protocol", [None, ""])
def test_missing_or_empty_protocol_still_fails_cloud_cli_before_work(
    monkeypatch, real_worker_environment, capsys, worker, protocol,
):
    if protocol is not None:
        monkeypatch.setenv(f"CASEOPS_{worker.upper()}_WORKER_ADMISSION_PROTOCOL_VERSION", protocol)
    monkeypatch.setenv(f"CASEOPS_{worker.upper()}_WORKER_ADMISSION_ENABLED", "false")
    with pytest.raises(SystemExit) as failure:
        _main(worker)(_args(worker) + ["--admission-disabled"])
    assert failure.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "protocol 1" in output.err


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("protocol", [True, False, 1.0, 0.0, None, 2, -1])
def test_non_integer_protocol_configuration_is_not_normalized_to_admission(
    real_worker_environment, worker, protocol,
):
    with pytest.raises(ValidationError) as failure:
        settings_module.Settings(**{f"{worker}_worker_admission_protocol_version": protocol})
    assert failure.value.errors(include_input=False)[0]["loc"] == (
        f"{worker}_worker_admission_protocol_version",
    )


@pytest.mark.parametrize("worker", WORKERS)
def test_real_env_enabled_cli_preserves_bounded_work_admission(
    monkeypatch, real_worker_environment, capsys, worker,
):
    _configure(monkeypatch, worker, "1", "true")
    calls = []

    def recover(**kwargs):
        assert paid_providers_blocked_for_request()
        calls.append(("recover", kwargs))
        return 0

    def drain(*, limit, outcomes):
        assert paid_providers_blocked_for_request()
        calls.append(("drain", limit))
        return 0

    module = document_jobs if worker == "document" else court_sync_jobs
    suffix = "document_processing_jobs" if worker == "document" else "matter_court_sync_jobs"
    monkeypatch.setattr(module, "recover_stale_" + suffix, recover)
    monkeypatch.setattr(module, "drain_" + suffix, drain)
    assert _main(worker)(_args(worker)) == 0
    limit = 5 if worker == "document" else 3
    assert calls == [("recover", {"stale_after_minutes": 15, "limit": limit}), ("drain", limit)]
    assert "admission_protocol=1 admission=enabled" in capsys.readouterr().out
