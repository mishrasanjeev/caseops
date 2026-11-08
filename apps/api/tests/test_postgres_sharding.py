from __future__ import annotations

import hashlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
import yaml

from tests.postgres_sharding import (
    _junit_identity,
    partition,
    pytest_collection_modifyitems,
    verify_reports,
)
from tests.test_deploy_prod_hardening import _bash_path, _find_working_bash, _write_fake_executable

UV_ACTION = "./.github/actions/verified-linux-uv"
UV_ARCHIVE = "uv-x86_64-unknown-linux-gnu.tar.gz"
UV_ARCHIVE_URL = f"https://releases.astral.sh/github/uv/releases/download/0.13.7/{UV_ARCHIVE}"
UV_ARCHIVE_SHA256 = "c5221ff41b7892bfc223543883600125f6a47fe845093e0f5bdff4f359196d83"


def _verified_uv_step(root: Path) -> str:
    action = yaml.safe_load((root / UV_ACTION / "action.yml").read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    step, = action["runs"]["steps"]
    assert step["shell"] == "bash"
    return step["run"]


def test_affected_ci_jobs_use_the_official_uv_archive_before_work():
    root = Path(__file__).resolve().parents[3]
    workflows = {
        name: yaml.safe_load((root / f".github/workflows/{name}.yml").read_text(encoding="utf-8"))
        for name in ("ci", "security")
    }
    using_action = [
        (workflow, job, step)
        for workflow, source in workflows.items()
        for job, definition in source["jobs"].items()
        for step in definition.get("steps", [])
        if step.get("uses") == UV_ACTION
    ]
    assert len(using_action) == 4
    assert {(workflow, job): step for workflow, job, step in using_action} == {
        ("ci", "api-test-shards"): {
            "name": "Install uv", "timeout-minutes": 5, "uses": UV_ACTION,
        },
        ("ci", "postgres-validation-shards"): {
            "name": "Install uv", "timeout-minutes": 5, "uses": UV_ACTION,
        },
        ("ci", "postgres-validation"): {"name": "Install uv", "uses": UV_ACTION},
        ("security", "pip-audit"): {"name": "Install uv", "uses": UV_ACTION},
    }
    for workflow, job, install in using_action:
        definition = workflows[workflow]["jobs"][job]
        assert definition["runs-on"] == "ubuntu-latest"
        steps = definition["steps"]
        checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
        assert steps.index(checkout) < steps.index(install)
        following = steps[steps.index(install) + 1]
        if (workflow, job) == ("ci", "postgres-validation"):
            assert following["name"] == "Download PostgreSQL evidence"
        else:
            assert following["run"] == "uv python install 3.13"
    action = _verified_uv_step(root)
    assert f"artifact={UV_ARCHIVE}" in action
    assert UV_ARCHIVE_URL.replace(UV_ARCHIVE, "${artifact}") in action
    assert action.count(UV_ARCHIVE_SHA256) == 1


@pytest.mark.parametrize(
    "mode",
    [
        "ok", "http-504", "transfer-timeout", "corrupt-archive",
        "wrong-version", "wrong-architecture",
    ],
)
def test_verified_uv_install_verifies_before_activation(tmp_path: Path, mode: str):
    root = Path(__file__).resolve().parents[3]
    runner = tmp_path / "runner"
    runner.mkdir()
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    output_path, output_env = tmp_path / "github-path", tmp_path / "github-env"
    curl_trace, uv_trace = tmp_path / "curl-attempt", tmp_path / "uv-attempt"
    fixture_archive = tmp_path / UV_ARCHIVE
    version = "uv 0.13.70" if mode == "wrong-version" else "uv 0.13.7 (fixture)"
    with tarfile.open(fixture_archive, "w:gz") as archive:
        for binary in ("uv", "uvx"):
            contents = (
                '#!/usr/bin/env bash\n'
                'printf "%s\\n" "$*" >> "$FAKE_UV_TRACE"\n'
                '[[ "$*" == --version ]] || exit 93\n'
                f'printf "%s\\n" "{version}"\n'
            ).encode()
            member = tarfile.TarInfo(f"uv-x86_64-unknown-linux-gnu/{binary}")
            member.size = len(contents)
            member.mode = 0o755
            archive.addfile(member, io.BytesIO(contents))
    fixture_hash = hashlib.sha256(fixture_archive.read_bytes()).hexdigest()
    if mode == "corrupt-archive":
        with fixture_archive.open("ab") as archive:
            archive.write(b"corrupt")
    _write_fake_executable(fake_bin / "curl", """#!/usr/bin/env bash
set -euo pipefail
printf 'attempt\\n' >> "$FAKE_CURL_TRACE"
expected=(--disable --proto '=https' --fail --silent --show-error
          --connect-timeout 15 --max-time 90 --max-filesize 16671812 --output)
[[ "$#" == 15 && "${*:1:13}" == "${expected[*]}" ]]
[[ "${15}" == "$FAKE_UV_URL" && "${14}" == "$RUNNER_TEMP"/caseops-linux-uv.*/"$FAKE_UV_NAME" ]]
case "$FAKE_UV_MODE" in
  http-504) exit 22 ;;
  transfer-timeout) exit 28 ;;
esac
cp -- "$FAKE_UV_ARCHIVE" "${14}"
""")
    env = {
        **os.environ,
        "RUNNER_TEMP": _bash_path(runner),
        "RUNNER_OS": "Linux",
        "RUNNER_ARCH": "ARM64" if mode == "wrong-architecture" else "X64",
        "GITHUB_PATH": _bash_path(output_path),
        "GITHUB_ENV": _bash_path(output_env),
        "FAKE_CURL_TRACE": _bash_path(curl_trace),
        "FAKE_UV_TRACE": _bash_path(uv_trace),
        "FAKE_UV_MODE": mode,
        "FAKE_UV_URL": UV_ARCHIVE_URL,
        "FAKE_UV_NAME": UV_ARCHIVE,
        "FAKE_UV_ARCHIVE": _bash_path(fixture_archive),
    }
    # Synthetic archive and version process only. The unmodified source pin
    # is independently bound to the upstream archive by the source contract.
    command = (
        'export PATH="$1:$PATH"; [[ "$(command -v curl)" == "$1/curl" ]] || exit 92; '
        + _verified_uv_step(root).replace(UV_ARCHIVE_SHA256, fixture_hash)
    )
    result = subprocess.run(
        [_find_working_bash(), "-c", command, "postgres-uv-test", _bash_path(fake_bin)],
        env=env, capture_output=True, text=True, timeout=15, check=False,
    )
    if mode == "wrong-architecture":
        assert not curl_trace.exists()
        assert "requires a Linux X64 runner" in result.stderr
    else:
        assert curl_trace.read_text().splitlines() == ["attempt"]
    if mode in {"ok", "wrong-version"}:
        assert uv_trace.read_text().splitlines() == ["--version"]
    else:
        assert not uv_trace.exists()
    if mode == "ok":
        assert result.returncode == 0, result.stdout + result.stderr
        binary, = runner.glob("caseops-linux-uv.*/uv-x86_64-unknown-linux-gnu")
        assert (binary / "uvx").is_file()
        assert output_path.read_text().splitlines() == [_bash_path(binary)]
        assert output_env.read_text().splitlines() == [
            f"UV_CACHE_DIR={_bash_path(runner)}/setup-uv-cache",
        ]
    else:
        assert result.returncode == {"http-504": 22, "transfer-timeout": 28}.get(mode, 1)
        assert not output_path.exists() and not output_env.exists()


def _render_postgres_matrix(value: str, shard: int, total: int) -> str:
    for key, replacement in {"shard": shard, "total_shards": total}.items():
        value = value.replace("${{ matrix." + key + " }}", str(replacement))
    assert "${{" not in value, "Every workflow placeholder must be resolved"
    return value


def test_ci_postgres_capacity_keeps_bounded_complete_acceptance():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["postgres-validation-shards"]
    assert job["timeout-minutes"] == 12
    strategy = job["strategy"]
    assert strategy["fail-fast"] is False
    assert strategy.get("max-parallel") == 4
    assert strategy["matrix"] == {"total_shards": [32], "shard": list(range(1, 33))}
    total = strategy["matrix"]["total_shards"][0]
    assert job["name"] == "Postgres + pgvector shard ${{ matrix.shard }}/${{ matrix.total_shards }}"
    step = next(item for item in job["steps"] if item.get("name") == "Pytest -m postgres")
    # Pytest timing excludes launcher overhead; retain the original whole-job budget.
    assert "timeout-minutes" not in step
    assert shlex.split(step["run"]) == [
        "uv", "run", "python", "../../scripts/pytest_native_receipt.py",
        "postgres-native-exit-${{ matrix.shard }}.json", "--", "-q", "-m", "postgres",
    ]
    assert "--postgres-shards=${{ matrix.total_shards }}" in step["env"]["PYTEST_ADDOPTS"]
    assert step["env"]["CASEOPS_READTHROUGH_EVIDENCE_DIR"] == (
        "${{ github.workspace }}/apps/api/postgres-shard-${{ matrix.shard }}-readthrough"
    )
    for shard in strategy["matrix"]["shard"]:
        options = shlex.split(_render_postgres_matrix(step["env"]["PYTEST_ADDOPTS"], shard, total))
        assert options == [
            "-p", "tests.postgres_sharding", f"--postgres-shard={shard}",
            f"--postgres-shards={total}", f"--postgres-inventory=postgres-shard-{shard}.json",
            f"--junitxml=postgres-shard-{shard}.xml",
            "-o", "faulthandler_timeout=60",
        ]
        journal = _render_postgres_matrix(step["env"]["CASEOPS_TEST_RESULT_JOURNAL"], shard, total)
        assert journal == f"postgres-shard-{shard}.jsonl"
        native = _render_postgres_matrix(
            step["env"]["CASEOPS_FINALIZER_EVIDENCE_DIR"], shard, total,
        )
        assert native == f"postgres-shard-{shard}-native"
    upload = next(item for item in job["steps"]
                  if item.get("name") == "Upload exact PostgreSQL collection and results")
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["path"].splitlines() == [
        f"apps/api/postgres-shard-${{{{ matrix.shard }}}}.{extension}"
        for extension in ("json", "xml", "jsonl")
    ] + [
        "apps/api/postgres-native-exit-${{ matrix.shard }}.json",
        "apps/api/postgres-shard-${{ matrix.shard }}-native/*.jsonl",
        "apps/api/postgres-shard-${{ matrix.shard }}-readthrough/",
        "apps/api/postgres-shard-${{ matrix.shard }}-query-plans/",
        "apps/api/postgres-shard-${{ matrix.shard }}-native/ip-preflight-plans/**/*.json",
        "apps/api/postgres-shard-${{ matrix.shard }}-native/ip-preflight-plans/**/*.jsonl",
    ]
    aggregate = workflow["jobs"]["postgres-validation"]
    assert aggregate["needs"] == ["postgres-validation-shards"]
    assert aggregate["if"] == "always() && !cancelled()"
    guard = next(item for item in aggregate["steps"]
                 if item.get("name") == "Require every PostgreSQL shard")
    assert guard["if"] == "needs.postgres-validation-shards.result != 'success'"
    assert guard["run"] == "exit 1"
    reconcile = next(item for item in aggregate["steps"]
                     if item.get("name") == "Reconcile complete PostgreSQL acceptance")
    assert shlex.split(reconcile["run"]) == [
        "uv", "run", "--python", "3.13", "python", "-m", "tests.postgres_sharding",
        "postgres-evidence", "--total", str(total),
        "--require-native-exit",
    ]
    assert "postgres-validation" in workflow["jobs"]["e2e"]["needs"]


@pytest.mark.parametrize("job", [
    "api-ruff", "api-test-shards", "api", "postgres-validation-shards", "postgres-validation",
])
def test_every_ci_api_consumer_selects_the_supported_python_before_resolution(job):
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    selected = False
    for step in workflow["jobs"][job]["steps"]:
        command = shlex.split(step.get("run", ""))
        if not command or command[0] != "uv":
            continue
        if command == ["uv", "python", "install", "3.13"]:
            selected = True
            continue
        versions = [
            command[index + 1] if argument == "--python" else argument.split("=", 1)[1]
            for index, argument in enumerate(command)
            if argument == "--python" or argument.startswith("--python=")
        ]
        assert all(version == "3.13" for version in versions), f"{job}: conflicting Python selector"
        assert selected or versions, (
            f"{job}: unpinned project resolution can select an unsupported Python"
        )


def test_ci_postgres_launcher_collects_and_executes_without_inherited_pythonpath(tmp_path):
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["postgres-validation-shards"]
    matrix = job["strategy"]["matrix"]
    total = matrix["total_shards"][0]
    steps = job["steps"]
    assert job["timeout-minutes"] == 12
    assert total == 32 and matrix["shard"] == list(range(1, total + 1))
    step = next(item for item in steps if item.get("name") == "Pytest -m postgres")
    command_template = shlex.split(step["run"])
    assert command_template[:4] == [
        "uv", "run", "python", "../../scripts/pytest_native_receipt.py",
    ]
    # This owned replay substitutes only the validated uv/bootstrap prefix.
    # It still runs the real helper and actual pytest child; live uv activation
    # is a separate Linux admission, not implied by this offline replay.
    fixture_python = sys.executable
    fixture_site = None
    if sys.platform == "win32":
        # CPython's Windows venv executable is a redirector with another child
        # PID. This offline fixture observes the actual base interpreter and
        # admits only its existing pytest site directory, never inherited app
        # PYTHONPATH. The Linux CI launcher still uses uv's real activation.
        fixture_python = str(Path(sys._base_executable).resolve(strict=True))
        fixture_site = Path(sys.prefix) / "Lib/site-packages"
        assert Path(pytest.__file__).resolve().is_relative_to(fixture_site.resolve(strict=True))
    command_template[:4] = [fixture_python, str(root / "scripts/pytest_native_receipt.py")]
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    shutil.copyfile(
        Path(__file__).with_name("postgres_sharding.py"), tests / "postgres_sharding.py"
    )
    shutil.copyfile(
        Path(__file__).with_name("retained_results.py"), tests / "retained_results.py"
    )
    (tests / "conftest.py").write_text('pytest_plugins = ["tests.retained_results"]\n')
    (tests / "test_sample.py").write_text(
        "import json,os,sys\nfrom pathlib import Path\nimport pytest\n"
        "@pytest.mark.postgres\n@pytest.mark.parametrize('item', range(64))\n"
        "def test_marked(item):\n    assert item >= 0\n"
        "    expected=json.loads(Path('owned-child-environment.json').read_text())\n"
        "    assert {key:os.environ.get(key) for key in expected} == expected\n"
        "    runtime=json.loads(Path('owned-child-runtime.json').read_text())\n"
        "    assert str(Path(sys.executable).resolve()) == runtime['executable']\n"
        "    assert str(Path(pytest.__file__).resolve()) == runtime['pytest_file']\n"
        "def test_unmarked():\n    raise AssertionError('Non-PostgreSQL test selected')\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers = postgres: PostgreSQL acceptance\n")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTEST_ADDOPTS", "COVERAGE_PROCESS_START",
                                  "CASEOPS_TEST_RESULT_JOURNAL",
                                  "CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID"}}
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    environment["GITHUB_SHA"] = "a" * 40
    environment["CASEOPS_NATIVE_ENV_LITERAL"] = "owned-pass-through"
    if fixture_site is not None:
        environment["PYTHONPATH"] = str(fixture_site.resolve(strict=True))
    (tmp_path / "owned-child-runtime.json").write_text(json.dumps({
        "executable": str(Path(fixture_python).resolve(strict=True)),
        "pytest_file": str(Path(pytest.__file__).resolve(strict=True)),
    }))
    expected = sorted(f"tests/test_sample.py::test_marked[{item}]" for item in range(64))
    executed = []
    for shard in matrix["shard"]:
        for key in ("PYTEST_ADDOPTS", "CASEOPS_TEST_RESULT_JOURNAL"):
            environment[key] = _render_postgres_matrix(step["env"][key], shard, total)
        expected_environment = {key: environment.get(key) for key in (
            "PATH", "VIRTUAL_ENV", "UV_RUN_RECURSION_DEPTH", "UV_CACHE_DIR", "PYTEST_ADDOPTS",
            "CASEOPS_NATIVE_ENV_LITERAL", "PYTHONPATH",
        )}
        (tmp_path / "owned-child-environment.json").write_text(json.dumps(expected_environment))
        command = [_render_postgres_matrix(value, shard, total) for value in command_template]
        result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True,
                                text=True, timeout=30, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        inventory = json.loads((tmp_path / f"postgres-shard-{shard}.json").read_text())
        selected = partition(expected, shard, total)
        assert inventory == {"shard": shard, "total": total, "nodeids": expected,
                             "selected": selected}
        executed.extend(selected)
        journal = [json.loads(line) for line in
                   (tmp_path / environment["CASEOPS_TEST_RESULT_JOURNAL"]).read_text().splitlines()]
        assert sorted(next(row["nodeids"] for row in journal if row["event"] == "collection")) == (
            selected
        )
        assert journal[-1] == {"event": "session_finished", "exitstatus": 0}
        native = json.loads((tmp_path / f"postgres-native-exit-{shard}.json").read_text())
        assert native["stage"] == "exited" and native["native_returncode"] == 0
        assert native["native_signal"] is None and native["publication_errors"] == []
        assert native["source_sha"] == environment["GITHUB_SHA"]
        assert journal[0] == {"event": "session_started", "pid": native["child_pid"]}
        reports = [row for row in journal if row["event"] == "test_report"]
        assert len(reports) == len(selected) * 3
        assert all(row["outcome"] == "passed" for row in reports)
        for phase in ("setup", "call", "teardown"):
            assert sorted(row["nodeid"] for row in reports if row["when"] == phase) == selected
    assert sorted(executed) == expected
    summary = {"status": "passed", "shards": total, "collected": len(expected), "skipped": 0}
    assert verify_reports(tmp_path, total) == summary
    native_summary = {**summary, "native_exit_receipts": total,
                      "source_sha": environment["GITHUB_SHA"]}
    reconciled_native = verify_reports(
        tmp_path, total, require_native_exit=True, source_sha=environment["GITHUB_SHA"],
    )
    assert reconciled_native == native_summary
    evidence = tmp_path / "postgres-evidence"
    evidence.mkdir()
    for path in [*tmp_path.glob("postgres-shard-*.*"),
                 *tmp_path.glob("postgres-native-exit-*.json")]:
        shutil.copyfile(path, evidence / path.name)
    aggregate = next(item for item in workflow["jobs"]["postgres-validation"]["steps"]
                     if item.get("name") == "Reconcile complete PostgreSQL acceptance")
    aggregate_command = shlex.split(aggregate["run"])
    assert aggregate_command[:5] == ["uv", "run", "--python", "3.13", "python"]
    aggregate_command = [fixture_python, *aggregate_command[5:]]
    result = subprocess.run(aggregate_command, cwd=tmp_path, env=environment, capture_output=True,
                            text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == native_summary


@pytest.mark.parametrize("damage", ["omit_native_flag", "omit_native_artifact", "bypass_helper"])
def test_current_ci_cannot_omit_native_exit_admission_or_publication(monkeypatch, damage):
    root = Path(__file__).resolve().parents[3]
    target = root / ".github/workflows/ci.yml"
    original_read = Path.read_text
    workflow = yaml.safe_load(original_read(target, encoding="utf-8"))
    if damage == "omit_native_flag":
        steps = workflow["jobs"]["postgres-validation"]["steps"]
        step = next(item for item in steps
                    if item.get("name") == "Reconcile complete PostgreSQL acceptance")
        step["run"] = step["run"].replace(" --require-native-exit", "")
    else:
        steps = workflow["jobs"]["postgres-validation-shards"]["steps"]
        if damage == "bypass_helper":
            step = next(item for item in steps if item.get("name") == "Pytest -m postgres")
            step["run"] = "uv run python -m pytest -q -m postgres"
        else:
            step = next(item for item in steps if item.get("name") == (
                "Upload exact PostgreSQL collection and results"
            ))
            step["with"]["path"] = "\n".join(
                line for line in step["with"]["path"].splitlines()
                if "postgres-native-exit-" not in line
            )

    def read(path, *args, **kwargs):
        return yaml.safe_dump(workflow) if path == target else original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(AssertionError):
        test_ci_postgres_capacity_keeps_bounded_complete_acceptance()


@pytest.mark.parametrize("fault", [
    None, "missing", "extra", "source", "source_missing", "stage", "schema", "child_pid",
    "same_pid", "boolean_pid", "journal_pid", "journal_missing", "journal_incomplete",
    "journal_boolean_exit",
    "exit17", "normal139", "negative_signal", "boolean_return", "runtime_sha",
    "runtime_missing", "runtime_path", "runtime_boolean_bytes", "time_naive", "time_order",
    "publication", "unknown_key",
])
def test_native_exit_protocol_requires_every_source_bound_successful_pytest_child(
    tmp_path, monkeypatch, fault,
):
    nodes = [f"tests/test_owned.py::test_item[{item}]" for item in range(64)]
    for shard in range(1, 33):
        selected = partition(nodes, shard, 32)
        (tmp_path / f"postgres-shard-{shard}.json").write_text(json.dumps({
            "shard": shard, "total": 32, "nodeids": nodes, "selected": selected,
        }))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{shard}.xml")
        (tmp_path / f"postgres-shard-{shard}.jsonl").write_text("\n".join([
            json.dumps({"event": "session_started", "pid": 10000 + shard}),
            json.dumps({"event": "session_finished", "exitstatus": 0}),
        ]) + "\n")
        row = {
            "schema_version": 1, "stage": "exited", "source_sha": "a" * 40,
            "launcher_pid": 9000 + shard, "child_pid": 10000 + shard,
            "planned_at": "2026-11-03T01:00:00+00:00",
            "started_at": "2026-11-03T01:00:01+00:00",
            "finished_at": "2026-11-03T01:00:02+00:00",
            "native_returncode": 0, "native_signal": None, "exit_code": 0,
            "publication_errors": [],
            "runtime": {"executable": sys.executable,
                        "resolved": str(Path(sys.executable).resolve()),
                        "sha256": "2" * 64, "bytes": 1234, "device": 1, "inode": 7},
        }
        if shard == 1:
            if fault == "source":
                row["source_sha"] = "b" * 40
            elif fault == "stage":
                row["stage"] = "started"
            elif fault == "schema":
                row["schema_version"] = 2
            elif fault == "child_pid":
                row["child_pid"] = 0
            elif fault == "same_pid":
                row["child_pid"] = row["launcher_pid"]
            elif fault == "boolean_pid":
                row["child_pid"] = True
            elif fault in {"exit17", "normal139", "negative_signal"}:
                code = {"exit17": 17, "normal139": 139, "negative_signal": -15}[fault]
                row.update(native_returncode=code, native_signal=15 if code < 0 else None,
                           exit_code=143 if code < 0 else code)
            elif fault == "boolean_return":
                row["native_returncode"] = False
            elif fault == "runtime_sha":
                row["runtime"]["sha256"] = None
            elif fault == "runtime_missing":
                row.pop("runtime")
            elif fault == "runtime_path":
                row["runtime"]["resolved"] = "python"
            elif fault == "runtime_boolean_bytes":
                row["runtime"]["bytes"] = True
            elif fault == "time_naive":
                row["finished_at"] = "2026-11-03T01:00:02"
            elif fault == "time_order":
                row["planned_at"] = "2026-11-03T01:00:03+00:00"
            elif fault == "publication":
                row["publication_errors"] = ["started"]
            elif fault == "unknown_key":
                row["unreviewed"] = "unexpected"
        if shard != 1 or fault != "missing":
            (tmp_path / f"postgres-native-exit-{shard}.json").write_text(json.dumps(row))
    if fault == "extra":
        (tmp_path / "postgres-native-exit-33.json").write_text(json.dumps(row))
    journal = tmp_path / "postgres-shard-1.jsonl"
    if fault == "journal_pid":
        journal.write_text(journal.read_text().replace('"pid": 10001', '"pid": 10002'))
    elif fault == "journal_missing":
        journal.unlink()
    elif fault == "journal_incomplete":
        journal.write_text(journal.read_text().splitlines()[0] + "\n")
    elif fault == "journal_boolean_exit":
        journal.write_text(journal.read_text().replace('"exitstatus": 0', '"exitstatus": false'))
    expected_source = "a" * 40
    if fault == "source_missing":
        expected_source = None
        monkeypatch.delenv("GITHUB_SHA", raising=False)
    if fault is None:
        result = verify_reports(tmp_path, 32, require_native_exit=True, source_sha=expected_source)
        assert result == {"status": "passed", "shards": 32, "collected": 64, "skipped": 0,
                          "native_exit_receipts": 32, "source_sha": "a" * 40}
    else:
        with pytest.raises(ValueError, match="native"):
            verify_reports(tmp_path, 32, require_native_exit=True, source_sha=expected_source)


@pytest.mark.parametrize("total", [4, 8, 16, 24, 32])
def test_postgres_partition_is_complete_disjoint_and_order_independent(total):
    nodes = [f"tests/test_example.py::test_item[{index}]" for index in range(2301)]
    selections = [partition(nodes, shard, total) for shard in range(1, total + 1)]
    assert sorted(node for selected in selections for node in selected) == sorted(nodes)
    assert max(map(len, selections)) - min(map(len, selections)) == 1
    assert selections == [
        partition(list(reversed(nodes)), shard, total) for shard in range(1, total + 1)
    ]
    floor, remainder = divmod(len(nodes), total)
    assert sorted(map(len, selections)) == [floor] * (total - remainder) + [floor + 1] * remainder


def test_sixteen_shards_split_each_previous_shard_without_changing_its_inventory():
    nodes = [f"tests/test_example.py::test_item[{index}]" for index in range(3005)]
    for shard in range(1, 9):
        prior = partition(nodes, shard, 8)
        first, second = partition(nodes, shard, 16), partition(nodes, shard + 8, 16)
        assert set(first).isdisjoint(second)
        assert sorted(first + second) == prior
        assert abs(len(first) - len(second)) <= 1


@pytest.mark.parametrize("nodes,shard,total", [([], 1, 4), (["a", "a"], 1, 1),
    (["a"], 2, 4), (["a"], 0, 1), (["a"], 1, 33),
    (["a"], True, 1), (["a"], 1, True), (["a"], 1.0, 1), (["a"], 1, 1.0),
    ("abc", 1, 1), ({"a": None}, 1, 1), ([None], 1, 1), ([""], 1, 1), (["a", 1], 1, 1)])
def test_postgres_partition_rejects_incomplete_or_invalid_selections(nodes, shard, total):
    with pytest.raises(ValueError):
        partition(nodes, shard, total)


@pytest.mark.parametrize(
    "fault", [None, "missing", "drift", "skipped", "failure", "error", "wrong-node"]
)
@pytest.mark.parametrize("total", [4, 8, 16, 24, 32])
def test_postgres_report_gate_requires_every_actual_success(tmp_path, fault, total):
    nodes = [f"tests/test_example.py::TestCases::test_item[{index}]" for index in range(64)]
    for shard in range(1, total + 1):
        selected = partition(nodes, shard, total)
        inventory = {"shard": shard, "total": total, "nodeids": nodes, "selected": selected}
        if fault == "drift" and shard == 1:
            inventory["nodeids"] = nodes[:-1]
        if fault != "missing" or shard != 1:
            (tmp_path / f"postgres-shard-{shard}.json").write_text(json.dumps(inventory))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            case = ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
            if shard == 1 and fault in ("skipped", "failure", "error"):
                ElementTree.SubElement(case, fault)
            if shard == 1 and fault == "wrong-node":
                case.set("name", "test_unselected")
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{shard}.xml")
    if fault is None:
        assert verify_reports(tmp_path, total) == {
            "status": "passed", "shards": total, "collected": 64, "skipped": 0
        }
    else:
        with pytest.raises(ValueError):
            verify_reports(tmp_path, total)


# Independent literal source685 job/phase evidence, not imported from selector.
MEASURED_CASES = {
    (
        "tests/test_ip_import_review_gaps_20261013.py::"
        "test_thousand_same_mark_distinct_applicants_commit_has_linear_materialization"
    ): 10,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[hearing_pack_items]"
    ): 3,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[hearing_packs]"
    ): 6,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[recommendation_decisions]"
    ): 16,
}


def _measured_fixture_nodes():
    return sorted(
        [
            *(f"tests/test_sample.py::test_item[{i}]" for i in range(130)),
            *MEASURED_CASES,
            *(node + "-near-match" for node in MEASURED_CASES),
        ]
    )


@pytest.mark.parametrize("node,target", list(MEASURED_CASES.items()))
def test_measured_cases_use_only_the_reviewed_literal_target(node, target):
    nodes = _measured_fixture_nodes()
    locations = [shard for shard in range(1, 17) if node in partition(nodes, shard, 16)]
    assert locations == [target]


@pytest.mark.parametrize("total", [1, 2, 4, 8, 16, 32])
def test_measured_routing_keeps_the_complete_union_and_every_other_assignment(total):
    nodes = _measured_fixture_nodes()
    result = [partition(nodes, shard, total) for shard in range(1, total + 1)]
    flat = [node for group in result for node in group]
    assert len(flat) == len(set(flat)) == len(nodes)
    assert sorted(flat) == nodes
    actual = {node: shard for shard, group in enumerate(result, 1) for node in group}
    for index, node in enumerate(nodes):
        if total == 32:
            expected = _independent_child_assignments(nodes)[node]
        else:
            expected = (
                MEASURED_CASES[node] if total == 16 and node in MEASURED_CASES
                else index % total + 1
            )
        assert actual[node] == expected
    assert result == [
        partition(list(reversed(nodes)), shard, total) for shard in range(1, total + 1)
    ]


@pytest.mark.parametrize(
    "fault", [None, "old-allocation", "missing-relocated-case", "duplicate-relocated-case"]
)
def test_measured_routing_report_gate_rejects_old_or_incomplete_allocation(tmp_path, fault):
    nodes = _measured_fixture_nodes()
    ordinal = {node: index % 16 + 1 for index, node in enumerate(nodes)}
    expected = {node: MEASURED_CASES.get(node, ordinal[node]) for node in nodes}
    chosen = next(iter(MEASURED_CASES))
    for shard in range(1, 17):
        # Build expected artifacts independently of partition() under test.
        assignment = ordinal if fault == "old-allocation" else expected
        selected = [node for node in nodes if assignment[node] == shard]
        if shard == expected[chosen]:
            if fault == "missing-relocated-case":
                selected.remove(chosen)
            elif fault == "duplicate-relocated-case":
                selected.append(chosen)
        inventory = {"shard": shard, "total": 16, "nodeids": nodes, "selected": selected}
        (tmp_path / f"postgres-shard-{shard}.json").write_text(json.dumps(inventory))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{shard}.xml")
    if fault is None:
        assert verify_reports(tmp_path, 16) == {
            "status": "passed",
            "shards": 16,
            "collected": len(nodes),
            "skipped": 0,
        }
    else:
        with pytest.raises(ValueError):
            verify_reports(tmp_path, 16)


def test_measured_collection_hook_keeps_selected_items_in_declaration_order(tmp_path):
    original = list(reversed(_measured_fixture_nodes()))
    ordered = sorted(original)
    destinations = {node: MEASURED_CASES.get(node, i % 16 + 1) for i, node in enumerate(ordered)}
    observed_targets = []
    for shard in (3, 6, 10, 16):
        inventory = tmp_path / f"postgres-shard-{shard}.json"
        options = {
            "--postgres-shard": shard,
            "--postgres-shards": 16,
            "--postgres-inventory": str(inventory),
        }
        deselected = []
        config = SimpleNamespace(
            getoption=options.__getitem__,
            hook=SimpleNamespace(
                pytest_deselected=lambda *, items, recorded=deselected: recorded.extend(
                    item.nodeid for item in items
                )
            ),
        )
        items = [
            SimpleNamespace(
                nodeid=node,
                get_closest_marker=lambda name: object() if name == "postgres" else None,
            )
            for node in original
        ]
        pytest_collection_modifyitems(config, items)
        assert [item.nodeid for item in items] == [
            node for node in original if destinations[node] == shard
        ]
        assert deselected == [node for node in original if destinations[node] != shard]
        assert json.loads(inventory.read_text())["selected"] == [
            node for node in ordered if destinations[node] == shard
        ]
        observed_targets.append(shard)
    assert observed_targets == [3, 6, 10, 16]


def _independent_child_assignments(nodes):
    ordered = sorted(nodes)
    parent = {node: MEASURED_CASES.get(node, i % 16 + 1) for i, node in enumerate(ordered)}
    assignment = {}
    for number in range(1, 17):
        members = [node for node in ordered if parent[node] == number]
        # Independent literal ABBA oracle; no partition() call or imported routing map.
        for index, node in enumerate(members):
            assignment[node] = number + (16 if index % 4 in (1, 2) else 0)
    return assignment


@pytest.mark.parametrize("size", [32, 33, 64, 65, 3005])
def test_thirty_two_children_keep_every_measured_parent_and_balance_its_prefix(size):
    nodes = [f"tests/test_sample.py::test_case[{i}]" for i in range(size)] + list(MEASURED_CASES)
    expected = _independent_child_assignments(nodes)
    actual = {}
    for parent in range(1, 17):
        previous = partition(nodes, parent, 16)
        first = partition(nodes, parent, 32)
        second = partition(nodes, parent + 16, 32)
        assert set(first).isdisjoint(second)
        assert sorted(first + second) == previous
        assert abs(len(first) - len(second)) <= 1
        actual.update({node: parent for node in first})
        actual.update({node: parent + 16 for node in second})
    assert actual == expected
    assert len(actual) == len(nodes)


@pytest.mark.parametrize(
    "fault", [None, "old-ordinal32", "old16", "missing-child", "duplicate-child",
              "wrong-parent", "duplicate-case"]
)
def test_thirty_two_report_gate_requires_the_exact_children_and_complete_union(tmp_path, fault):
    nodes = _measured_fixture_nodes()
    expected = _independent_child_assignments(nodes)
    assignment = dict(expected)
    if fault == "old-ordinal32":
        assignment = {node: i % 32 + 1 for i, node in enumerate(nodes)}
    elif fault == "old16":
        assignment = {node: MEASURED_CASES.get(node, i % 16 + 1)
                      for i, node in enumerate(nodes)}
    elif fault == "wrong-parent":
        chosen = next(iter(MEASURED_CASES))
        assignment[chosen] = (expected[chosen] % 16) + 1
    total = 16 if fault == "old16" else 32
    for child in range(1, total + 1):
        if fault == "missing-child" and child == 32:
            continue
        selected = [node for node in nodes if assignment[node] == child]
        if fault == "duplicate-case" and child == expected[nodes[0]]:
            selected.append(nodes[0])
        identity = 1 if fault == "duplicate-child" and child == 32 else child
        inventory = {"shard": identity, "total": total, "nodeids": nodes,
                     "selected": selected}
        (tmp_path / f"postgres-shard-{child}.json").write_text(json.dumps(inventory))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{child}.xml")
    if fault is None:
        assert verify_reports(tmp_path, 32) == {
            "status": "passed", "shards": 32, "collected": len(nodes), "skipped": 0,
        }
    else:
        with pytest.raises(ValueError):
            verify_reports(tmp_path, 32)


def test_child_collection_keeps_the_original_declaration_order(tmp_path):
    original = list(reversed(_measured_fixture_nodes()))
    expected = _independent_child_assignments(original)
    for child in range(1, 33):
        inventory = tmp_path / f"postgres-shard-{child}.json"
        options = {"--postgres-shard": child, "--postgres-shards": 32,
                   "--postgres-inventory": str(inventory)}
        deselected = []
        config = SimpleNamespace(
            getoption=options.__getitem__,
            hook=SimpleNamespace(
                pytest_deselected=lambda *, items, recorded=deselected: recorded.extend(
                    item.nodeid for item in items
                )
            ),
        )
        items = [SimpleNamespace(nodeid=node, get_closest_marker=lambda name: object())
                 for node in original]
        pytest_collection_modifyitems(config, items)
        assert [item.nodeid for item in items] == [
            node for node in original if expected[node] == child
        ]
        assert deselected == [node for node in original if expected[node] != child]
        assert json.loads(inventory.read_text())["selected"] == sorted(
            node for node in original if expected[node] == child
        )
