"""Court-only execution and pre-SQL admission contract."""

import ast
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from caseops_api.services import court_sync_jobs
from caseops_api.workers import court_sync


def _settings(**overrides):
    return SimpleNamespace(
        **(
            {
                "court_sync_worker_admission_protocol_version": 1,
                "court_sync_worker_admission_enabled": True,
                "court_sync_worker_batch_size": 3,
                "court_sync_stale_after_minutes": 15,
                "auto_migrate": True,
            }
            | overrides
        )
    )


@pytest.fixture
def no_sql(monkeypatch):
    monkeypatch.setattr(
        court_sync_jobs, "get_session_factory", lambda: pytest.fail("SQL before court admission")
    )
    from caseops_api.db import migrations

    monkeypatch.setattr(
        migrations, "run_migrations", lambda: pytest.fail("court executor must never migrate")
    )


@pytest.mark.parametrize(
    "protocol, admission",
    [
        (0, False),
        (None, False),
        (2, True),
        (True, True),
        ("1", False),
        (1, None),
        (1, "false"),
        (1, 0),
        (1, 1),
    ],
)
def test_court_admission_invalid_configuration_fails_before_sql(
    protocol,
    admission,
    no_sql,
    monkeypatch,
):
    monkeypatch.setattr(
        court_sync,
        "get_settings",
        lambda: _settings(
            court_sync_worker_admission_protocol_version=protocol,
            court_sync_worker_admission_enabled=admission,
        ),
    )
    with pytest.raises(SystemExit) as error:
        court_sync.main(["--once", "--skip-migrations"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "args, enabled",
    [
        (["--once"], False),
        (["--once", "--skip-migrations"], False),
        (["--once", "--admission-disabled"], True),
    ],
)
def test_court_admission_disabled_has_zero_sql_and_explicit_zero_receipt(
    args,
    enabled,
    no_sql,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        court_sync,
        "get_settings",
        lambda: _settings(
            court_sync_worker_admission_enabled=enabled,
        ),
    )
    assert court_sync.main(args) == 0
    assert capsys.readouterr().out == (
        "CaseOps court sync worker: admission_protocol=1 admission=disabled "
        "recovered=0 attempted=0 completed=0 failed=0 unfinalized=0\n"
    )


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--batch-size=3"],
        ["--once", "--batch-size=0"],
        ["--once", "--batch-size=26"],
        ["--once", "--batch-size=x"],
    ],
)
def test_court_cli_rejects_continuous_or_unbounded_work(args, no_sql, monkeypatch):
    monkeypatch.setattr(court_sync, "get_settings", _settings)
    with pytest.raises(SystemExit) as error:
        court_sync.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("age", [0, 1441, True, "15"])
def test_court_enabled_invalid_recovery_age_fails_before_sql(age, no_sql, monkeypatch):
    monkeypatch.setattr(
        court_sync,
        "get_settings",
        lambda: _settings(
            court_sync_stale_after_minutes=age,
        ),
    )
    with pytest.raises(SystemExit) as error:
        court_sync.main(["--once"])
    assert error.value.code == 2


@pytest.mark.parametrize("batch", [1, 3, 25])
def test_court_cli_drains_only_bounded_court_work(batch, no_sql, monkeypatch, capsys):
    from caseops_api.services import case_tracking_summary, document_jobs

    monkeypatch.setattr(court_sync, "get_settings", _settings)
    calls = []

    def recover(**kwargs):
        calls.append(("recover", kwargs))
        return 1

    def drain(*, limit, outcomes):
        calls.append(("drain", {"limit": limit}))
        outcomes.update(completed=1, failed=0, unfinalized=0)
        return 1

    monkeypatch.setattr(court_sync_jobs, "recover_stale_matter_court_sync_jobs", recover)
    monkeypatch.setattr(court_sync_jobs, "drain_matter_court_sync_jobs", drain)
    for module, name in (
        (document_jobs, "drain_document_processing_jobs"),
        (document_jobs, "enqueue_scheduled_document_reprocessing"),
        (case_tracking_summary, "drain_update_summaries"),
    ):
        monkeypatch.setattr(module, name, lambda **_: pytest.fail("non-court work"))
    assert court_sync.main(["--once", f"--batch-size={batch}"]) == 0
    assert calls == [
        ("recover", {"stale_after_minutes": 15, "limit": batch}),
        ("drain", {"limit": batch}),
    ]
    assert "attempted=1 completed=1 failed=0 unfinalized=0" in capsys.readouterr().out


def test_court_worker_console_entry_and_dependency_owner():
    api = Path(__file__).resolve().parents[1]
    config = tomllib.loads((api / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["scripts"]["caseops-court-sync-worker"] == (
        "caseops_api.workers.court_sync:main"
    )
    tree = ast.parse(Path(court_sync.__file__).read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert set(imports) == {
        "__future__",
        "caseops_api.core.settings",
        "caseops_api.services.court_sync_jobs",
    }
