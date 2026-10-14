from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest


def _args_value(argv):
    values = [item.removeprefix("--args=") for item in argv if item.startswith("--args=")]
    assert len(values) == 1 and "--args" not in argv
    return values[0]

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40
REQUEST = {
    "schema_version": 1,
    "company_id": "11111111-1111-4111-8111-111111111111",
    "subscription_id": "22222222-2222-4222-8222-222222222222",
    "operation_id": "33333333-3333-4333-8333-333333333333",
    "before_sha256": "b" * 64,
}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("qa_manual_ip_grant_release")
    image = module.IMAGE_PREFIX + "c" * 64
    secrets = {"CASEOPS_DATABASE_URL": "7", "CASEOPS_AUTH_SECRET": "11"}
    source, output = tmp_path / "approved.json", tmp_path / "evidence.json"
    source.write_text(json.dumps(REQUEST), encoding="utf-8")
    state = {
        "calls": [],
        "checks": 0,
        "runs": [],
        "mutate_job": None,
        "mutate_execution": None,
        "mutate_receipt": None,
        "scheduler": [],
        "fail_execute": False,
        "main_race": None,
        "after_count_delta": 0,
        "inspect_fingerprint": "d" * 64,
        "secret_project": "123456789",
        "serving_refs": {"CASEOPS_DATABASE_URL": "latest", "CASEOPS_AUTH_SECRET": "latest"},
        "latest_versions": dict(secrets),
        "real_execution_shape": True,
    }

    def task(args):
        env = [
            {"name": name, "value": value}
            for name, value in {
                "CASEOPS_ENV": "cloud",
                "CASEOPS_AUTO_MIGRATE": "false",
                "CASEOPS_RELEASE_SHA": SHA,
            }.items()
        ]
        env.extend(
            {
                "name": name,
                "valueFrom": {
                    "secretKeyRef": {
                        "name": "caseops-database-url"
                        if name == "CASEOPS_DATABASE_URL"
                        else "caseops-auth-secret",
                        "key": version,
                    }
                },
            }
            for name, version in state.get("deployed_versions", secrets).items()
        )
        return {
            "serviceAccountName": module.SERVICE_ACCOUNT,
            "maxRetries": 0,
            "timeoutSeconds": 180,
            "containers": [
                {
                    "image": image,
                    "command": ["python"],
                    "args": args,
                    "env": env,
                    "resources": {"limits": {"cpu": "1000m", "memory": "512Mi"}},
                }
            ],
        }

    def job():
        value = {
            "metadata": {
                "name": module.JOB,
                "uid": "job-uid",
                "generation": 4,
                "labels": {"caseops-release": SHA, "caseops-control": "test-legal-manual-ip"},
            },
            "status": {
                "observedGeneration": 4,
                "conditions": [{"type": "Ready", "status": "True"}],
                "executionCount": len(state["runs"])
                + len(state.get("history", []))
                + state["after_count_delta"],
                "latestCreatedExecution": {
                    "name": (
                        state["runs"][-1][0]
                        if state["runs"]
                        else state["history"][-1]["metadata"]["name"]
                        if state.get("history")
                        else ""
                    )
                },
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"run.googleapis.com/cloudsql-instances": module.CLOUD_SQL}
                    },
                    "spec": {
                        "taskCount": 1,
                        "parallelism": 1,
                        "template": {"spec": task(module._args(REQUEST))},
                    },
                }
            },
        }
        if state["mutate_job"]:
            state["mutate_job"](value)
        return value

    def execution(name):
        args = next(args for identity, args in state["runs"] if identity == name)
        value = {
            "metadata": {
                "name": name,
                "labels": {
                    "run.googleapis.com/job": module.JOB,
                    "run.googleapis.com/jobGeneration": "4",
                },
                "ownerReferences": [{"name": module.JOB, "uid": "job-uid", "kind": "Job"}],
            },
            "spec": {
                "taskCount": 1,
                "parallelism": 1,
                "template": {
                    "metadata": {
                        "annotations": {"run.googleapis.com/cloudsql-instances": module.CLOUD_SQL}
                    },
                    "spec": task(args),
                },
            },
            "status": {
                "conditions": [{"type": "Completed", "status": "True"}],
                "succeededCount": 1,
                "failedCount": 0,
                "cancelledCount": 0,
                "startTime": (datetime.now(UTC) - timedelta(seconds=2)).isoformat(),
                "completionTime": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            },
        }
        if state.get("real_execution_shape"):
            value["metadata"]["annotations"] = value["spec"]["template"].pop("metadata")[
                "annotations"
            ]
        if state["mutate_execution"]:
            state["mutate_execution"](value)
        return value

    def receipt(name):
        if name.endswith("inspect"):
            data = {
                "schema_version": 1,
                "mode": "inspect",
                "company_id": REQUEST["company_id"],
                "subscription_id": REQUEST["subscription_id"],
                "before_sha256": state["inspect_fingerprint"],
            }
        else:
            request = {**REQUEST, "expected_before_sha256": REQUEST["before_sha256"]}
            del request["before_sha256"]
            data = {
                **REQUEST,
                "mode": "grant",
                "replayed": False,
                "after_sha256": "d" * 64,
                "request_sha256": hashlib.sha256(
                    json.dumps(
                        request,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "audit_event_id": str(
                    uuid5(
                        NAMESPACE_URL, f"caseops:qa-manual-ip-entitlement:{REQUEST['operation_id']}"
                    )
                ),
            }
        if state["mutate_receipt"]:
            state["mutate_receipt"](data)
        return [
            {
                "resource": {
                    "type": "cloud_run_job",
                    "labels": {
                        "job_name": module.JOB,
                        "project_id": module.PROJECT,
                        "location": module.REGION,
                    },
                },
                "labels": {
                    "run.googleapis.com/execution_name": name,
                    "run.googleapis.com/task_index": "0",
                    "run.googleapis.com/task_attempt": "0",
                },
                "textPayload": json.dumps(data),
            }
        ]

    def cloud(argv, **kwargs):
        assert kwargs["expect_json"] is True
        state["calls"].append(argv)
        prefix = state.get("cloud_failure_prefix")
        failure_mode = state.get("cloud_failure_mode")
        matches_mode = failure_mode is None or (
            any(item.startswith("--args=") for item in argv)
            and failure_mode in _args_value(argv).split(",")
        )
        if prefix and prefix == tuple(argv[:len(prefix)]) and matches_mode:
            raise state["cloud_failure"]
        state.setdefault("timeouts", []).append((argv[:3], kwargs["timeout"]))
        if argv[:3] == ["run", "services", "describe"]:
            value = {
                "metadata": {"generation": 8},
                "status": {
                    "observedGeneration": 8,
                    "latestReadyRevisionName": "caseops-api-008-ready",
                    "latestCreatedRevisionName": "caseops-api-008-ready",
                    "traffic": [{"revisionName": "caseops-api-008-ready", "percent": 100}],
                    "conditions": [
                        {"type": key, "status": "True"}
                        for key in ("Ready", "ConfigurationsReady", "RoutesReady")
                    ],
                },
            }
            if state.get("mutate_serving"):
                state["mutate_serving"](value)
            return value
        if argv[:3] == ["run", "revisions", "describe"]:
            value = {
                "metadata": {"name": "caseops-api-008-ready"},
                "spec": {
                    "containers": [
                        {
                            "name": "api",
                            "image": image,
                            "env": [{"name": "CASEOPS_RELEASE_SHA", "value": SHA}],
                        }
                    ]
                },
            }
            value["spec"]["containers"][0]["env"].extend(
                {
                    "name": name,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": "caseops-database-url"
                            if name == "CASEOPS_DATABASE_URL"
                            else "caseops-auth-secret",
                            "key": reference,
                        }
                    },
                }
                for name, reference in state["serving_refs"].items()
            )
            if state.get("mutate_revision"):
                state["mutate_revision"](value)
            return value
        if argv[:3] == ["scheduler", "jobs", "list"]:
            return state["scheduler"]
        if argv[:3] == ["run", "jobs", "list"]:
            return [job()] if state.get("history") else []
        if argv[:4] == ["run", "jobs", "executions", "list"]:
            assert "--limit=101" in argv
            return state["history"]
        if argv[:2] == ["projects", "describe"]:
            return {"projectId": module.PROJECT, "projectNumber": "123456789"}
        if argv[:3] == ["secrets", "versions", "describe"]:
            secret = argv[argv.index("--secret") + 1]
            key = (
                "CASEOPS_DATABASE_URL"
                if secret == "caseops-database-url"
                else "CASEOPS_AUTH_SECRET"
            )
            version = state["latest_versions"][key] if argv[3] == "latest" else argv[3]
            return {
                "name": (f"projects/{state['secret_project']}/secrets/{secret}/versions/{version}"),
                "state": "ENABLED",
            }
        if argv[:3] == ["run", "jobs", "deploy"]:
            assert "--execute-now" not in argv
            state["deployed_versions"] = {
                part.split("=", 1)[0]: part.rsplit(":", 1)[-1]
                for part in argv[argv.index("--set-secrets") + 1].split(",")
            }
            if state.get("rotate_after_deploy"):
                state["latest_versions"]["CASEOPS_DATABASE_URL"] = "8"
            return job()
        if argv[:3] == ["run", "jobs", "describe"]:
            return job()
        if argv[:3] == ["run", "jobs", "execute"]:
            if state["fail_execute"]:
                raise RuntimeError("secret-value-must-not-escape")
            args = (
                _args_value(argv).split(",")
                if any(item.startswith("--args=") for item in argv)
                else module._args(REQUEST)
            )
            name = module.JOB + ("-inspect" if args[2] == "inspect" else "-grant")
            state["runs"].append((name, args))
            return {"metadata": {"name": name}}
        if argv[:4] == ["run", "jobs", "executions", "describe"]:
            return execution(argv[4])
        if argv[:2] == ["logging", "read"]:
            state["log_reads"] = state.get("log_reads", 0) + 1
            if state.get("empty_forever") or state["log_reads"] <= state.get("empty_reads", 0):
                return []
            rows = receipt(state["runs"][-1][0])
            if state.get("structured"):
                for row in rows:
                    row["jsonPayload"] = json.loads(row.pop("textPayload"))
                    if state.get("protobuf_structured"):
                        from google.protobuf.json_format import MessageToJson
                        from google.protobuf.struct_pb2 import Struct

                        value = Struct()
                        value.update(row["jsonPayload"])
                        row["jsonPayload"] = json.loads(MessageToJson(value))
            for row in rows:
                row["logName"] = f"projects/{module.PROJECT}/logs/run.googleapis.com%2Fstdout"
            if state.get("duplicate_log"):
                rows += copy.deepcopy(rows)
            if state.get("mutate_log"):
                for row in rows:
                    state["mutate_log"](row)
            return rows
        return pytest.fail(f"Unexpected offline CLI invocation: {argv[:4]}")

    def current(release):
        assert release == SHA
        state["checks"] += 1
        if state["checks"] == state["main_race"]:
            raise module.ReleaseError("canonical_main_changed")

    # Patch the full transport, never PATH: no test can fall through to a real CLI.
    real_current_main = module.assert_current_main
    monkeypatch.setattr(module, "run_gcloud", cloud)
    monkeypatch.setattr(module, "assert_current_main", current)
    return SimpleNamespace(
        module=module,
        real_current_main=real_current_main,
        state=state,
        source=source,
        output=output,
        image=image,
        secrets=secrets,
        job=job,
        execution=execution,
        cloud=cloud,
    )


def run(harness):
    digest = harness.module.preflight(str(harness.source), str(harness.output))[1]
    return harness.module.execute(
        str(harness.source),
        str(harness.output),
        release=SHA,
        image=harness.image,
        expected_input_sha256=digest,
    )


def test_absent_configuration_has_zero_tools_and_zero_grant(harness):
    assert harness.module.execute(None, None, release="", image="", expected_input_sha256="") == {
        "status": "not_requested"
    }
    assert harness.state["calls"] == [] and harness.state["checks"] == 0
    assert not harness.output.exists()


def test_complete_release_uses_one_grant_and_separate_readonly_inspection(harness):
    evidence = run(harness)
    assert evidence["status"] == "verified"
    assert [args[2] for _, args in harness.state["runs"]] == ["grant", "inspect"]
    assert evidence["inspection"]["before_sha256"] == evidence["receipt"]["after_sha256"]
    assert evidence["readiness_scope"] == "job_ready_and_locked_entitlement_readback_only"
    assert json.loads(harness.output.read_text()) == evidence
    deploy = next(args for args in harness.state["calls"] if args[:3] == ["run", "jobs", "deploy"])
    assert deploy[deploy.index("--max-retries") + 1] == "0"
    assert deploy[deploy.index("--task-timeout") + 1] == "180s"
    assert deploy[deploy.index("--set-secrets") + 1] == (
        "CASEOPS_DATABASE_URL=caseops-database-url:7,CASEOPS_AUTH_SECRET=caseops-auth-secret:11"
    )
    assert "latest" not in deploy[deploy.index("--set-secrets") + 1]


@pytest.mark.parametrize("mode", ["grant", "inspect"])
def test_operator_args_use_default_comma_without_cmd_metacharacters(harness, mode):
    run(harness)
    calls = [
        argv for argv in harness.state["calls"]
        if any(item.startswith("--args=") for item in argv)
        and (argv[:3] == ["run", "jobs", "deploy"] if mode == "grant"
                                else argv[:3] == ["run", "jobs", "execute"])
    ]
    assert len(calls) == 1
    expected = harness.module._args(REQUEST) if mode == "grant" else [
        "-m", harness.module.MODULE, "inspect", "--company-id", REQUEST["company_id"],
        "--subscription-id", REQUEST["subscription_id"],
    ]
    assert _args_value(calls[0]) == ",".join(expected)
    parser = argparse.ArgumentParser(exit_on_error=False)
    parser.add_argument("--args")
    parsed, _unknown = parser.parse_known_args(calls[0])
    assert parsed.args.split(",") == expected


def test_unbound_dash_prefixed_container_args_fail_parser_admission():
    parser = argparse.ArgumentParser(exit_on_error=False)
    parser.add_argument("--args")
    with pytest.raises(argparse.ArgumentError, match="expected one argument"):
        parser.parse_known_args(["--args", "-m,caseops_api.scripts.qa_manual_ip_entitlement"])


@pytest.mark.parametrize(
    "prefix,stage",
    [
        (("run", "services", "describe"), "serving_service"),
        (("run", "revisions", "describe"), "serving_revision"),
        (("scheduler", "jobs", "list"), "scheduler_inventory"),
        (("run", "jobs", "list"), "job_inventory"),
        (("projects", "describe"), "secret_project"),
        (("secrets", "versions", "describe"), "secret_version"),
        (("run", "jobs", "deploy"), "job_deploy"),
        (("run", "jobs", "describe"), "job_readback"),
        (("run", "jobs", "execute"), "grant_execution"),
        (("run", "jobs", "executions", "describe"), "execution_readback"),
        (("logging", "read"), "receipt_readback"),
    ],
)
@pytest.mark.parametrize(
    "kind",
    ["command_failed", "deadline_exceeded", "invalid_json", "transport_error", "unexpected_error"],
)
def test_failed_output_retains_only_allowlisted_stage_and_typed_category(
    harness, prefix, stage, kind,
):
    inventory = importlib.import_module("scheduler_inventory")
    sensitive = "CANARY_PASSWORD_AND_RAW_ARGV_MUST_NOT_ESCAPE"
    if kind in {"command_failed", "deadline_exceeded", "invalid_json"}:
        error = inventory.InventoryError(sensitive)
        if kind == "deadline_exceeded":
            error.__cause__ = subprocess.TimeoutExpired([sensitive], 30, output=sensitive)
        elif kind == "invalid_json":
            error.__cause__ = json.JSONDecodeError(sensitive, sensitive, 0)
    else:
        error = OSError(sensitive) if kind == "transport_error" else RuntimeError(sensitive)
    harness.state.update(cloud_failure_prefix=prefix, cloud_failure=error)
    with pytest.raises(harness.module.ReleaseError, match="cloud_command_failed"):
        run(harness)
    raw = harness.output.read_text()
    evidence = json.loads(raw)
    assert evidence["error_code"] == "cloud_command_failed"
    assert evidence["cloud_error"] == {"stage": stage, "category": kind}
    assert evidence["status"] == "failed_closed"
    assert sensitive not in raw
    assert sum(tuple(argv[:len(prefix)]) == prefix for argv in harness.state["calls"]) == 1
    assert evidence["execute_attempted"] is (
        stage in {"grant_execution", "execution_readback", "receipt_readback"}
    )


def test_inspection_failure_retains_one_grant_and_separate_safe_cloud_stage(harness):
    harness.state.update(
        cloud_failure_prefix=("run", "jobs", "execute"), cloud_failure_mode="inspect",
        cloud_failure=RuntimeError("DO_NOT_RETAIN_SECRET_EXCEPTION"),
    )
    with pytest.raises(harness.module.ReleaseError, match="cloud_command_failed"):
        run(harness)
    raw = harness.output.read_text()
    evidence = json.loads(raw)
    assert evidence["cloud_error"] == {
        "stage": "inspection_execution", "category": "unexpected_error",
    }
    assert evidence["receipt"]["operation_id"] == REQUEST["operation_id"]
    assert evidence["execute_attempted"] is evidence["inspection_execute_attempted"] is True
    assert [args[2] for _, args in harness.state["runs"]] == ["grant"]
    assert "DO_NOT_RETAIN_SECRET_EXCEPTION" not in raw


@pytest.mark.parametrize(
    "value", ["a,b", "^,^a,b", "a|b", "a&b", "%TOKEN%", "a b", "a\nb", "", None],
)
def test_fixed_operator_serializer_rejects_commas_and_shell_metacharacters(harness, value):
    with pytest.raises(harness.module.ReleaseError, match="invalid_operator_args"):
        harness.module._serialized_args(["-m", harness.module.MODULE, value])
    assert harness.state["calls"] == []


def test_execution_inventory_failure_has_safe_stage_without_dispatch(harness):
    harness.state.update(
        history=[{"metadata": {"name": "old"}}],
        cloud_failure_prefix=("run", "jobs", "executions", "list"),
        cloud_failure=OSError("DO_NOT_RETAIN_RAW_ERROR"),
    )
    with pytest.raises(harness.module.ReleaseError, match="cloud_command_failed"):
        run(harness)
    evidence = json.loads(harness.output.read_text())
    assert evidence["cloud_error"] == {
        "stage": "execution_inventory", "category": "transport_error",
    }
    assert harness.state["runs"] == []


def test_cloud_diagnostics_do_not_extend_deadlines_or_repeat_mutations(harness):
    run(harness)
    assert [timeout for prefix, timeout in harness.state["timeouts"]
            if prefix == ["run", "jobs", "deploy"]] == [180]
    assert [timeout for prefix, timeout in harness.state["timeouts"]
            if prefix == ["run", "jobs", "execute"]] == [30, 30]
    assert all(timeout <= 30 for prefix, timeout in harness.state["timeouts"]
               if prefix != ["run", "jobs", "deploy"])


_CMD_LOGGER = '''import sys
def offline(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.startfile'):
        raise PermissionError('OFFLINE_FIXTURE_DENIED')
sys.addaudithook(offline)
import ctypes
import json
import os
from pathlib import Path
import socket
import argparse
try:
    socket.socket()
except PermissionError:
    denied = True
else:
    raise RuntimeError('Socket fence failed')
ctypes.windll.kernel32.GetCommandLineW.restype = ctypes.c_wchar_p
value = dict(received=sys.argv[1:], stage=os.environ['CMD_CAPTURE_STAGE'], pid=os.getpid(),
    raw_command_line=ctypes.windll.kernel32.GetCommandLineW(), no_site=sys.flags.no_site,
    python=sys.executable, socket_denied=denied)
parser = argparse.ArgumentParser(exit_on_error=False)
parser.add_argument('--args')
parsed, _unknown = parser.parse_known_args(sys.argv[1:])
value['parsed_container_args'] = parsed.args.split(',') if parsed.args is not None else None
path = Path(os.environ['CMD_CAPTURE_DIR']) / (value['stage'] + '-' + str(value['pid']) + '.json')
with path.open('x', encoding='utf-8') as stream:
    json.dump(value, stream)
print(json.dumps(value))
'''


@pytest.fixture
def windows_cmd_cli(harness, monkeypatch, tmp_path):
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, r"Software\Microsoft\Command Processor") as key:
                autorun = winreg.QueryValueEx(key, "AutoRun")[0]
        except FileNotFoundError:
            autorun = ""
        assert not autorun, "Refuse implicit native CMD AutoRun"
    root = (tmp_path / "owned-cmd").absolute()
    root.mkdir()
    assert root.resolve() == root and root.is_relative_to(tmp_path.resolve())
    owner = str(uuid4())
    marker = root / "owner.json"
    marker.write_text(json.dumps({"owner": owner}), encoding="utf-8")
    library, captures = root / "lib", root / "captures"
    library.mkdir()
    captures.mkdir()
    logger = library / "gcloud.py"
    logger.write_text(_CMD_LOGGER, encoding="utf-8")
    system32 = Path(os.environ["SystemRoot"]) / "System32"
    fake = root / "gcloud.cmd"
    forwarding = (
        '"%CLOUDSDK_PYTHON%" %CLOUDSDK_PYTHON_ARGS% "%CLOUDSDK_ROOT_DIR%\\lib\\gcloud.py" '
        '%* & goto lastline 2>NUL || "%COMSPEC%" /C exit 0\n:lastline\n'
        '"%COMSPEC%" /C exit %ERRORLEVEL%\n'
    )
    fixture_files = [marker, logger]
    tokens = set(harness.module._args(REQUEST)) | {"inspect"}
    for token in ["gcloud", *sorted(tokens)]:
        path = root / (token + ".cmd")
        path.write_text('@echo off\nSETLOCAL DisableDelayedExpansion\n'
                        f'SET "CMD_CAPTURE_STAGE={token}"\n' + forwarding, encoding="utf-8")
        fixture_files.append(path)
    env = {
        "SystemRoot": str(system32.parent), "WINDIR": str(system32.parent),
        "COMSPEC": str(system32 / "cmd.exe"), "PATH": str(root) + os.pathsep + str(system32),
        "PATHEXT": ".CMD", "TEMP": str(root), "TMP": str(root),
        "CLOUDSDK_PYTHON": sys.executable, "CLOUDSDK_PYTHON_ARGS": "-S",
        "CLOUDSDK_ROOT_DIR": str(root), "CMD_CAPTURE_DIR": str(captures),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
    }
    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setenv("PATHEXT", env["PATHEXT"])
    assert Path(shutil.which("gcloud") or "").resolve() == fake.resolve()
    inventory = importlib.import_module("scheduler_inventory")
    real_run = subprocess.run

    def isolated_run(argv, **kwargs):
        assert Path(argv[0]).resolve() == fake.resolve()
        assert fake.resolve().parent == root.resolve()
        kwargs["timeout"] = min(kwargs["timeout"], 20)
        return real_run(argv, cwd=root, env=env, **kwargs)

    monkeypatch.setattr(inventory.subprocess, "run", isolated_run)
    try:
        yield SimpleNamespace(root=root, captures=captures, inventory=inventory)
    finally:
        assert root.resolve() == root and json.loads(marker.read_text())["owner"] == owner
        for path in [*fixture_files, *captures.glob("*.json")]:
            assert path.resolve().is_relative_to(root) and not path.is_symlink()
            path.unlink()
        captures.rmdir()
        library.rmdir()
        root.rmdir()
        assert not root.exists()


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows CMD argument dispatch")
@pytest.mark.parametrize("mode", ["grant", "inspect"])
def test_actual_windows_cmd_roundtrips_complete_grant_and_inspection_argv(
    harness, windows_cmd_cli, monkeypatch, record_property, mode,
):
    observed = []

    def transport(argv, **kwargs):
        if any(item.startswith("--args=") for item in argv):
            value = windows_cmd_cli.inventory.run_gcloud(argv, **kwargs)
            record_property("native_cmd_" + str(len(observed)), json.dumps(value, sort_keys=True))
            assert value["stage"] == "gcloud" and value["received"] == argv
            assert value["socket_denied"] is True and value["no_site"] == 1
            assert Path(value["python"]).resolve() == Path(sys.executable).resolve()
            observed.append(value)
        return harness.cloud(argv, **kwargs)

    monkeypatch.setattr(harness.module, "run_gcloud", transport)
    assert run(harness)["status"] == "verified"
    assert len(observed) == 2
    value = observed[0 if mode == "grant" else 1]["received"]
    expected = harness.module._args(REQUEST) if mode == "grant" else [
        "-m", harness.module.MODULE, "inspect", "--company-id", REQUEST["company_id"],
        "--subscription-id", REQUEST["subscription_id"],
    ]
    assert _args_value(value).split(",") == expected
    assert observed[0 if mode == "grant" else 1]["parsed_container_args"] == expected
    assert value[-1] == "--format=json"
    assert [args[2] for _, args in harness.state["runs"]] == ["grant", "inspect"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(schema_version=True),
        lambda value: value.update(company_id="not-a-uuid"),
        lambda value: value.update(subscription_id="not-a-uuid"),
        lambda value: value.update(operation_id="not-a-uuid"),
        lambda value: value.update(before_sha256="latest"),
        lambda value: value.update(provider_key="forbidden"),
        lambda value: value.pop("operation_id"),
    ],
)
def test_invalid_approval_never_reaches_cloud(harness, mutation):
    value = copy.deepcopy(REQUEST)
    mutation(value)
    harness.source.write_text(json.dumps(value))
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert harness.state["calls"] == [] and not harness.output.exists()


@pytest.mark.parametrize(
    "payload", ["{", "[]", '{"schema_version":1,"schema_version":1}', "x" * 8193]
)
def test_malformed_duplicate_and_oversized_input_rejected(harness, payload):
    harness.source.write_text(payload)
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert harness.state["calls"] == []


def test_output_reserved_and_input_bound_before_cloud(harness):
    harness.output.write_text("old evidence")
    with pytest.raises(harness.module.ReleaseError, match="evidence_already_exists"):
        run(harness)
    assert harness.output.read_text() == "old evidence" and harness.state["calls"] == []


def test_changed_approved_input_fingerprint_has_zero_tools(harness):
    with pytest.raises(harness.module.ReleaseError, match="grant_input_changed"):
        harness.module.execute(
            str(harness.source),
            str(harness.output),
            release=SHA,
            image=harness.image,
            expected_input_sha256="0" * 64,
        )
    assert harness.state["calls"] == [] and not harness.output.exists()


@pytest.mark.parametrize("race", [1, 2, 3, 4, 5])
def test_current_main_races_stop_and_never_repeat_grant(harness, race):
    harness.state["main_race"] = race
    with pytest.raises(harness.module.ReleaseError, match="canonical_main_changed"):
        run(harness)
    assert sum(args[2] == "grant" for _, args in harness.state["runs"]) <= 1
    if race <= 3:
        assert harness.state["runs"] == []
    assert json.loads(harness.output.read_text())["status"] == "failed_closed"


@pytest.mark.parametrize(
    "path",
    [
        "/v2/projects/perfect-period-305406/locations/asia-south1/jobs/{job}:run",
        "/v2/projects/123456789/locations/asia-south1/jobs/{job}:run",
        "/v2/projects/123456789/locations/us-central1/jobs/{job}:run",
        "/apis/run.googleapis.com/v1/namespaces/perfect-period-305406/jobs/{job}:run",
        "/apis/run.googleapis.com/v1/namespaces/123456789/jobs/{job}:run",
        "/apis/run.googleapis.com/v1/namespaces/123456789/jobs/{job}%3Arun",
        "/v2/projects/123456789/locations/asia-south1/jobs/%63aseops-test-legal-manual-ip-grant:run",
    ],
)
def test_equivalent_scheduler_targets_block_before_job_mutation(harness, path):
    harness.state["scheduler"] = [
        {"httpTarget": {"uri": "https://run.googleapis.com" + path.format(job=harness.module.JOB)}}
    ]
    with pytest.raises(harness.module.ReleaseError, match="unexpected_scheduler"):
        run(harness)
    assert not any(args[:3] == ["run", "jobs", "deploy"] for args in harness.state["calls"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("maxRetries", 1),
        ("maxRetries", True),
        ("timeoutSeconds", 181),
        ("serviceAccountName", "wrong@invalid"),
        ("volumes", [{"secret": "forbidden"}]),
    ],
)
def test_task_drift_never_dispatches(harness, field, value):
    harness.state["mutate_job"] = lambda job: job["spec"]["template"]["spec"]["template"][
        "spec"
    ].update({field: value})
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert harness.state["runs"] == []


@pytest.mark.parametrize("timeout", [180, "180", "180s"])
def test_equivalent_v1_timeout_shapes_are_accepted(harness, timeout):
    harness.state["mutate_job"] = lambda job: job["spec"]["template"]["spec"]["template"][
        "spec"
    ].update(timeoutSeconds=timeout)
    assert run(harness)["status"] == "verified"


@pytest.mark.parametrize(
    "kind", ["image", "args", "secret", "provider", "parallelism", "generation", "ready"]
)
def test_complete_job_readback_rejects_drift(harness, kind):
    def mutate(job):
        spec = job["spec"]["template"]["spec"]
        container = spec["template"]["spec"]["containers"][0]
        if kind == "image":
            container["image"] += "old"
        elif kind == "args":
            container["args"] = ["-m", "other"]
        elif kind == "secret":
            container["env"][-1]["valueFrom"]["secretKeyRef"]["key"] = "latest"
        elif kind == "provider":
            container["env"].append({"name": "CASEOPS_LLM_API_KEY", "value": "forbidden"})
        elif kind == "parallelism":
            spec["parallelism"] = 2
        elif kind == "generation":
            job["status"]["observedGeneration"] = 3
        else:
            job["status"]["conditions"][0]["status"] = "Unknown"

    harness.state["mutate_job"] = mutate
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert harness.state["runs"] == []


@pytest.mark.parametrize(
    "kind", ["failed", "image", "generation", "owner", "secret", "count", "time"]
)
def test_execution_drift_remains_failed_closed_without_mutation_retry(harness, kind):
    def mutate(value):
        container = value["spec"]["template"]["spec"]["containers"][0]
        if kind == "failed":
            value["status"]["conditions"][0]["status"] = "False"
        elif kind == "image":
            container["image"] += "old"
        elif kind == "generation":
            value["metadata"]["labels"]["run.googleapis.com/jobGeneration"] = "3"
        elif kind == "owner":
            value["metadata"]["ownerReferences"][0]["uid"] = "foreign"
        elif kind == "secret":
            container["env"][-1]["valueFrom"]["secretKeyRef"]["key"] = "latest"
        elif kind == "count":
            value["status"]["succeededCount"] = True
        else:
            value["status"]["completionTime"] = "invalid"

    harness.state["mutate_execution"] = mutate
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert len(harness.state["runs"]) == 1


def test_failed_execute_is_not_retried_and_errors_are_sanitized(harness, capsys):
    harness.state["fail_execute"] = True
    digest = harness.module.preflight(str(harness.source), str(harness.output))[1]
    assert (
        harness.module.main(
            [
                "execute",
                "--input",
                str(harness.source),
                "--output",
                str(harness.output),
                "--release-sha",
                SHA,
                "--image",
                harness.image,
                "--expected-input-sha256",
                digest,
            ]
        )
        == 1
    )
    evidence = harness.output.read_text()
    assert "secret-value-must-not-escape" not in evidence + capsys.readouterr().err
    assert json.loads(evidence)["execute_attempted"] is True
    assert sum(args[:3] == ["run", "jobs", "execute"] for args in harness.state["calls"]) == 1


def test_foreign_secret_project_blocked(harness):
    harness.state["secret_project"] = "999999999"
    with pytest.raises(harness.module.ReleaseError, match="secret_version_unavailable"):
        run(harness)
    assert harness.state["runs"] == []


def test_readonly_after_state_drift_is_not_verified(harness):
    harness.state["inspect_fingerprint"] = "e" * 64
    with pytest.raises(harness.module.ReleaseError, match="inspection_state_mismatch"):
        run(harness)
    assert [args[2] for _, args in harness.state["runs"]] == ["grant", "inspect"]
    assert json.loads(harness.output.read_text())["status"] == "failed_closed"


def test_cloud_output_bound_is_fail_closed(harness, monkeypatch):
    monkeypatch.setattr(harness.module, "run_gcloud", lambda *args, **kwargs: "x" * 200001)
    with pytest.raises(harness.module.ReleaseError, match="cloud_output_bounds"):
        run(harness)
    assert harness.state["runs"] == []


def test_deploy_hook_is_optional_precloud_and_postcanary_before_dispatch():
    source = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
    validate = source.index("python scripts/qa_manual_ip_grant_release.py validate")
    assert validate < source.index('assert_current_main "release preflight"')
    execute = source.index("python scripts/qa_manual_ip_grant_release.py execute")
    assert (
        source.index('echo "--- production QA bootstrap exact-generation execution ---"') < execute
    )
    assert execute < source.index("gh workflow run prod-verify.yml")
    assert 'if [[ -n "${TEST_LEGAL_MANUAL_IP_GRANT_INPUT}" ]]; then' in source
    assert source.index('assert_current_main "pre-test-legal-manual-ip-grant gate"') < execute
    assert execute < source.index('assert_current_main "post-test-legal-manual-ip-grant gate"')


@pytest.mark.parametrize("kind", ["image", "release", "traffic", "generation"])
def test_actual_serving_release_mismatch_blocks_before_cloud_mutation(harness, kind):
    if kind == "image":
        harness.state["mutate_revision"] = lambda value: value["spec"]["containers"][0].update(
            image=harness.image + "wrong"
        )
    elif kind == "release":
        harness.state["mutate_revision"] = lambda value: value["spec"]["containers"][0]["env"][
            0
        ].update(value="f" * 40)
    elif kind == "traffic":
        harness.state["mutate_serving"] = lambda value: value["status"]["traffic"][0].update(
            percent=99
        )
    else:
        harness.state["mutate_serving"] = lambda value: value["status"].update(observedGeneration=7)
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert harness.state["runs"] == []
    assert not any(args[:3] == ["run", "jobs", "deploy"] for args in harness.state["calls"])


def test_failed_readback_retains_exact_grant_execution(harness):
    harness.state["mutate_execution"] = lambda value: value["status"].update(succeededCount=0)
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    evidence = json.loads(harness.output.read_text())
    assert evidence["execution"] == harness.module.JOB + "-grant"
    assert evidence["execute_attempted"] is True
    assert evidence["status"] == "failed_closed"


def test_inspection_boolean_schema_is_not_integer_version(harness):
    def mutate(receipt):
        if receipt["mode"] == "inspect":
            receipt["schema_version"] = True

    harness.state["mutate_receipt"] = mutate
    with pytest.raises(harness.module.ReleaseError, match="inspection_state_mismatch"):
        run(harness)


@pytest.mark.parametrize("image,release", [("tag:latest", SHA), ("invalid", "wrong")])
def test_unpinned_image_and_invalid_release_never_reach_cloud(harness, image, release):
    digest = harness.module.preflight(str(harness.source), str(harness.output))[1]
    with pytest.raises(harness.module.ReleaseError):
        harness.module.execute(
            str(harness.source),
            str(harness.output),
            release=release,
            image=image,
            expected_input_sha256=digest,
        )
    assert harness.state["calls"] == [] and not harness.output.exists()


@pytest.mark.parametrize("result", ["exact", "advanced", "error", "oversized"])
def test_real_main_guard_uses_explicit_readonly_git_arrays(harness, monkeypatch, result):
    calls = []

    def command(argv, **kwargs):
        calls.append(argv)
        assert kwargs["cwd"] == ROOT
        assert kwargs["timeout"] == 30 and kwargs["capture_output"] is True
        assert argv in (
            ["git", "rev-parse", "HEAD"],
            ["git", "ls-remote", "origin", "refs/heads/main"],
        )
        stdout = SHA + "\n"
        if "ls-remote" in argv:
            stdout = ("f" * 40 if result == "advanced" else SHA) + "\trefs/heads/main\n"
        if result == "oversized":
            stdout = "x" * 1025
        return SimpleNamespace(
            returncode=1 if result == "error" else 0,
            stdout=stdout,
            stderr="sensitive error never printed",
        )

    monkeypatch.setattr(harness.module.subprocess, "run", command)
    if result == "exact":
        harness.real_current_main(SHA)
        assert len(calls) == 2
    else:
        with pytest.raises(harness.module.ReleaseError):
            harness.real_current_main(SHA)


def test_real_cloud_run_structured_payload_shape(harness):
    harness.state["structured"] = True
    assert run(harness)["status"] == "verified"
    queries = [args[2] for args in harness.state["calls"] if args[:2] == ["logging", "read"]]
    assert queries and all("jsonPayload" in query for query in queries)
    assert sum(args[2] == "grant" for _, args in harness.state["runs"]) == 1


def test_empty_observation_then_receipt_does_not_repeat_grant(harness, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(harness.module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        harness.module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    harness.state["empty_reads"] = 1
    harness.state["structured"] = True
    assert run(harness)["status"] == "verified"
    assert harness.state["log_reads"] == 3  # Empty+grant, then independent inspection.
    assert sum(args[2] == "grant" for _, args in harness.state["runs"]) == 1


def test_receipt_observation_deadline_does_not_retry_mutation(harness, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(harness.module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        harness.module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    harness.state["empty_forever"] = True
    with pytest.raises(harness.module.ReleaseError, match="receipt_observation_deadline"):
        run(harness)
    assert clock[0] == 45.0
    assert sum(args[2] == "grant" for _, args in harness.state["runs"]) == 1
    assert json.loads(harness.output.read_text())["execution"] == harness.module.JOB + "-grant"


@pytest.mark.parametrize("field", ["input", "output", "inside_checkout"])
def test_approval_paths_must_be_absolute_and_outside_checkout(harness, monkeypatch, field):
    monkeypatch.chdir(harness.source.parent)
    source, output = str(harness.source), str(harness.output)
    if field == "input":
        source = harness.source.name
    elif field == "output":
        output = harness.output.name
    else:
        monkeypatch.setattr(harness.module, "ROOT", harness.source.parent)
    with pytest.raises(harness.module.ReleaseError, match="invalid_grant_paths"):
        harness.module.preflight(source, output)
    assert harness.state["calls"] == []


def test_official_v1_execution_metadata_annotations(harness):
    harness.state["real_execution_shape"] = True
    assert run(harness)["status"] == "verified"


def test_wrong_template_metadata_execution_shape_is_rejected(harness):
    harness.state["real_execution_shape"] = False
    with pytest.raises(harness.module.ReleaseError):
        run(harness)


def test_serving_numeric_secret_references_not_independent_latest(harness):
    harness.state["serving_refs"] = {"CASEOPS_DATABASE_URL": "3", "CASEOPS_AUTH_SECRET": "5"}
    evidence = run(harness)
    assert evidence["secret_versions"] == {"CASEOPS_DATABASE_URL": "3", "CASEOPS_AUTH_SECRET": "5"}
    assert harness.state["deployed_versions"] == evidence["secret_versions"]


@pytest.mark.parametrize(
    "history_count,unfinished",
    [
        (100, False),
        (101, False),
        (100, True),
        (101, True),
    ],
)
def test_execution_history_sentinel_and_unfinished_are_fail_closed(
    harness, history_count, unfinished
):
    harness.state["history"] = [
        {
            "metadata": {
                "name": harness.module.JOB + f"-old{index}",
                "labels": {"run.googleapis.com/job": harness.module.JOB},
            },
            "status": {"completionTime": "2026-10-13T00:00:00Z"},
        }
        for index in range(history_count)
    ]
    if unfinished:
        harness.state["history"][-1]["status"]["completionTime"] = ""
    if history_count == 100 and not unfinished:
        assert run(harness)["status"] == "verified"
    else:
        with pytest.raises(harness.module.ReleaseError):
            run(harness)
        assert harness.state["runs"] == []
        assert not any(args[:3] == ["run", "jobs", "deploy"] for args in harness.state["calls"])


@pytest.mark.parametrize("kind", ["duplicate", "invalid", "mismatch", "origin", "dual"])
def test_nonempty_invalid_receipts_fail_immediately_without_retry(harness, kind):
    harness.state["structured"] = True
    if kind == "duplicate":
        harness.state["duplicate_log"] = True
    elif kind == "invalid":
        harness.state["mutate_log"] = lambda row: row.update(jsonPayload=[])
    elif kind == "mismatch":
        harness.state["mutate_receipt"] = lambda receipt: receipt.update(company_id="wrong")
    elif kind == "origin":
        harness.state["mutate_log"] = lambda row: row["labels"].update(
            {"run.googleapis.com/task_attempt": "1"}
        )
    else:
        harness.state["mutate_log"] = lambda row: row.update(textPayload="{}")
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert harness.state["log_reads"] == 1
    assert sum(args[2] == "grant" for _, args in harness.state["runs"]) == 1


def test_latest_rotation_before_execute_aborts_grant(harness):
    harness.state["rotate_after_deploy"] = True
    with pytest.raises(harness.module.ReleaseError, match="serving_secret_changed"):
        run(harness)
    assert harness.state["runs"] == []


def test_changed_serving_secret_reference_aborts_before_grant(harness):
    harness.state["mutate_revision"] = lambda value: value["spec"]["containers"][0]["env"][1][
        "valueFrom"
    ]["secretKeyRef"].update(name="unreviewed-secret")
    with pytest.raises(harness.module.ReleaseError, match="serving_secret_drift"):
        run(harness)
    assert harness.state["runs"] == []


def test_real_protobuf_struct_receipts_accept_logical_numeric_version(harness):
    harness.state["structured"] = True
    harness.state["protobuf_structured"] = True
    result = run(harness)
    assert result["status"] == "verified"
    assert type(result["receipt"]["schema_version"]) is float
    assert type(result["inspection"]["schema_version"]) is float
    assert result["receipt"]["schema_version"] == result["inspection"]["schema_version"] == 1.0


@pytest.mark.parametrize("version", [True, False, "1", 1.5, 0])
def test_invalid_logged_schema_versions_remain_fail_closed(harness, version):
    harness.state["structured"] = True
    harness.state["mutate_receipt"] = lambda receipt: receipt.update(schema_version=version)
    with pytest.raises(harness.module.ReleaseError):
        run(harness)
    assert sum(args[2] == "grant" for _, args in harness.state["runs"]) == 1


@pytest.mark.parametrize("mode", ["grant", "inspect"])
def test_plain_text_float_schema_version_is_rejected_without_retry(harness, mode):
    def mutate(receipt):
        if receipt["mode"] == mode:
            receipt["schema_version"] = 1.0

    harness.state["mutate_receipt"] = mutate
    expected = "grant_receipt_mismatch" if mode == "grant" else "inspection_state_mismatch"
    with pytest.raises(harness.module.ReleaseError, match=expected):
        run(harness)
    assert sum(args[2] == "grant" for _, args in harness.state["runs"]) == 1
    assert sum(args[2] == "inspect" for _, args in harness.state["runs"]) == (mode == "inspect")
    assert harness.state["log_reads"] == (1 if mode == "grant" else 2)


def test_unknown_offline_cli_invocation_fails_without_mutation(harness):
    with pytest.raises(pytest.fail.Exception, match="Unexpected offline CLI invocation"):
        harness.module._cloud(["unsupported-offline-command"])
    assert harness.state["runs"] == []
