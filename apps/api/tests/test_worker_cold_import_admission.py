"""Admission must precede worker SQL, storage, model and provider imports."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

WORKERS = ("document", "court_sync")
SOURCE = Path(__file__).resolve().parents[1] / "src"
DISABLED_RECEIPTS = {
    "document": (
        "CaseOps document worker: admission_protocol=1 admission=disabled "
        "recovered=0 queued=0 attempted=0 completed=0 failed=0 unfinalized=0 "
        "court_sync_recovered=0 court_sync_processed=0 case_summaries_processed=0\n"
    ),
    "court_sync": (
        "CaseOps court sync worker: admission_protocol=1 admission=disabled "
        "recovered=0 attempted=0 completed=0 failed=0 unfinalized=0\n"
    ),
}

# The guard is installed before importing either worker, not in the warm pytest
# process where conftest has already loaded the application and its SQL services.
COLD_PROCESS = r'''
import contextlib
import importlib
import importlib.abc
import io
import json
import runpy
import sys

source, worker, argv, entrypoint = sys.argv[1:]
sys.path.insert(0, source)
prefixes = (
    "caseops_api.db", "caseops_api.models", "caseops_api.services",
    "sqlalchemy", "google", "azure", "boto3", "botocore", "vertexai",
    "openai", "anthropic", "litellm", "cohere", "mistralai",
)

def forbidden(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)

assert not any(forbidden(name) for name in sys.modules)
blocked_imports = []
network_attempts = []

class ForbiddenWorkerImport(ImportError):
    pass

class ForbiddenNetwork(RuntimeError):
    pass

class ImportGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            blocked_imports.append(fullname)
            raise ForbiddenWorkerImport(fullname)

def no_network(event, args):
    if event.startswith("socket."):
        network_attempts.append(event)
        raise ForbiddenNetwork(event)

sys.meta_path.insert(0, ImportGuard())
sys.addaudithook(no_network)

from pydantic import ValidationError
from caseops_api.core.automated_test_context import (
    NO_PAID_PROVIDERS_VALUE, paid_providers_blocked_for_request,
    set_automated_test_request,
)

set_automated_test_request(NO_PAID_PROVIDERS_VALUE)
module = "caseops_api.workers." + (
    "document_processor" if worker == "document" else "court_sync"
)
stdout, stderr = io.StringIO(), io.StringIO()
result = {"exit_code": 0, "status": "returned", "validation_fields": [], "validation_messages": []}
with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
    try:
        if entrypoint == "iteration":
            importlib.import_module(module).run_worker_iteration(
                batch_size=5, stale_after_minutes=15, retry_after_hours=24,
                reindex_after_hours=24, reprocessing_batch_size=5,
                court_sync_batch_size=3, court_sync_stale_after_minutes=15,
            )
        else:
            sys.argv = [module, *json.loads(argv)]
            runpy.run_module(module, run_name="__main__")
    except SystemExit as exc:
        result["exit_code"] = exc.code
        if exc.code != 0:
            result["status"] = "parser-rejected"
    except ValidationError as exc:
        result.update(
            exit_code=2, status="settings-rejected",
            validation_fields=[list(error["loc"]) for error in exc.errors(include_input=False)],
            validation_messages=[error["msg"] for error in exc.errors(include_input=False)],
        )
    except ForbiddenWorkerImport:
        result.update(exit_code=86, status="forbidden-import")
    except ForbiddenNetwork:
        result.update(exit_code=87, status="forbidden-network")

if result["status"] == "returned":
    from caseops_api.core.settings import get_settings
    settings = get_settings()
    protocol = getattr(settings, worker + "_worker_admission_protocol_version")
    admission = getattr(settings, worker + "_worker_admission_enabled")
    result.update(
        environment=settings.env, protocol=protocol, protocol_type=type(protocol).__name__,
        admission=admission, admission_type=type(admission).__name__,
    )
result.update(
    stdout=stdout.getvalue(), stderr=stderr.getvalue(), blocked_imports=blocked_imports,
    loaded_forbidden=sorted(name for name in sys.modules if forbidden(name)),
    network_attempts=network_attempts, no_paid=paid_providers_blocked_for_request(),
)
print(json.dumps(result))
raise SystemExit(result["exit_code"])
'''


def _args(worker):
    return (["--documents-only"] if worker == "document" else []) + ["--once"]


def _cold_worker(
    tmp_path, worker, args, *, protocol="1", admission="false", entrypoint="cli",
    environment="cloud", auto_migrate=False,
):
    env = {
        name: value for name, value in os.environ.items()
        if not name.startswith(("CASEOPS_", "PYTHON")) and name != "PYTEST_CURRENT_TEST"
    }
    env.update(
        CASEOPS_ENV=environment, CASEOPS_AUTH_SECRET=uuid4().hex + uuid4().hex,
        CASEOPS_AUTO_MIGRATE="true" if auto_migrate else "false",
    )
    prefix = f"CASEOPS_{worker.upper()}_WORKER_ADMISSION_"
    if protocol is not None:
        env[prefix + "PROTOCOL_VERSION"] = protocol
    if admission is not None:
        env[prefix + "ENABLED"] = admission
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", COLD_PROCESS,
         str(SOURCE), worker, json.dumps(args), entrypoint],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
        timeout=120,  # Hang protection, not a cold-start performance oracle.
    )
    (tmp_path / "cold-worker-result.json").write_text(completed.stdout, encoding="utf-8")
    assert completed.stdout.strip(), (completed.returncode, completed.stderr)
    result = json.loads(completed.stdout)
    assert completed.returncode == result["exit_code"], (result, completed.stderr)
    assert completed.stderr == "", completed.stderr
    assert result["loaded_forbidden"] == [], result
    assert result["network_attempts"] == [], result
    assert result["no_paid"] is True, result
    return result


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("disabled_by", ["setting", "cli"])
def test_cold_disabled_worker_emits_exact_zero_work_without_runtime_imports(
    tmp_path, worker, disabled_by,
):
    args = _args(worker)
    if disabled_by == "cli":
        args.append("--admission-disabled")
    result = _cold_worker(
        tmp_path, worker, args, admission="false" if disabled_by == "setting" else "true",
    )
    assert result["exit_code"] == 0, result
    assert result["status"] == "returned", result
    assert result["environment"] == "cloud"
    assert result["protocol"] == 1 and result["protocol_type"] == "int"
    assert result["admission"] is (disabled_by == "cli")
    assert result["admission_type"] == "bool"
    assert result["blocked_imports"] == []
    assert result["validation_fields"] == []
    assert result["stdout"] == DISABLED_RECEIPTS[worker]
    assert result["stderr"] == ""


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize(
    "protocol,admission,status,field",
    [
        pytest.param("0", "false", "parser-rejected", None, id="protocol-zero"),
        pytest.param("2", "false", "settings-rejected", "protocol_version", id="protocol-two"),
        pytest.param("1", None, "parser-rejected", None, id="admission-missing"),
        pytest.param("1", "invalid", "settings-rejected", "enabled", id="admission-invalid"),
    ],
)
def test_cold_invalid_configuration_is_not_disabled_success(
    tmp_path, worker, protocol, admission, status, field,
):
    result = _cold_worker(
        tmp_path, worker, _args(worker) + ["--admission-disabled"],
        protocol=protocol, admission=admission,
    )
    assert result["exit_code"] == 2, result
    assert result["status"] == status, result
    assert result["blocked_imports"] == []
    assert result["stdout"] == ""
    if field is not None:
        assert result["validation_fields"] == [[f"{worker}_worker_admission_{field}"]]
    else:
        assert result["validation_fields"] == []
        assert "protocol 1" in result["stderr"] or "Boolean admission" in result["stderr"]


@pytest.mark.parametrize("worker", WORKERS)
@pytest.mark.parametrize("invalid", ["missing-once", "oversized-batch"])
def test_cold_invalid_cli_is_rejected_before_disabled_work(tmp_path, worker, invalid):
    args = _args(worker) + ["--admission-disabled"]
    if invalid == "missing-once":
        args.remove("--once")
        error = "requires --once"
    else:
        oversized = "101" if worker == "document" else "26"
        args += ["--batch-size", oversized]
        error = f"argument --batch-size: invalid choice: '{oversized}'"
    result = _cold_worker(tmp_path, worker, args)
    assert result["exit_code"] == 2, result
    assert result["status"] == "parser-rejected", result
    assert result["blocked_imports"] == []
    assert result["stdout"] == ""
    assert error in result["stderr"]


@pytest.mark.parametrize("worker", WORKERS)
def test_cold_cloud_auto_migration_cannot_bypass_configuration_guard(tmp_path, worker):
    result = _cold_worker(
        tmp_path, worker, _args(worker) + ["--admission-disabled"], auto_migrate=True,
    )
    assert result["exit_code"] == 2, result
    assert result["status"] == "settings-rejected", result
    assert result["validation_fields"] == [[]]
    assert len(result["validation_messages"]) == 1
    assert "CASEOPS_AUTO_MIGRATE=true is rejected" in result["validation_messages"][0]
    assert result["blocked_imports"] == []
    assert result["stdout"] == ""
    assert result["stderr"] == ""


@pytest.mark.parametrize(
    "worker,args,entrypoint,expected_import",
    [
        pytest.param("document", ["--documents-only", "--once"], "cli",
                     "caseops_api.services", id="documents-only"),
        pytest.param("court_sync", ["--once"], "cli",
                     "caseops_api.services", id="court-sync"),
        pytest.param("document", ["--once", "--skip-migrations"], "cli",
                     "caseops_api.services", id="legacy-iteration"),
        pytest.param("document", ["--once", "--skip-migrations", "--skip-maintenance"], "cli",
                     "caseops_api.services", id="skip-maintenance"),
        pytest.param("document", ["--once"], "cli",
                     "caseops_api.db", id="legacy-auto-migrate"),
        pytest.param("document", [], "iteration",
                     "caseops_api.services", id="public-iteration"),
        pytest.param("document", ["--documents-only", "--once", "--skip-migrations",
                                  "--require-qa-quiescence"], "cli",
                     "caseops_api.services", id="qa-quiescence"),
    ],
)
def test_cold_enabled_worker_reaches_runtime_instead_of_false_zero_work(
    tmp_path, worker, args, entrypoint, expected_import,
):
    result = _cold_worker(
        tmp_path, worker, args, admission="true", entrypoint=entrypoint,
        environment="local" if expected_import == "caseops_api.db" else "cloud",
        auto_migrate=expected_import == "caseops_api.db",
    )
    assert result["exit_code"] == 86, result
    assert result["status"] == "forbidden-import", result
    assert result["blocked_imports"] == [expected_import]
    assert result["validation_fields"] == []
    assert result["stdout"] == ""
    assert result["stderr"] == ""
