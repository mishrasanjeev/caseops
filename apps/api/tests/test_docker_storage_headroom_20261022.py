"""Offline checks of the release-owned Docker filesystem admission, never Docker."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify-docker.ps1"
PROJECT = "caseops-acceptance-111111111111-aaaaaaaaaaaa"
RELEASE = "1" * 40
IMAGE, PG, CID = "sha256:" + "a" * 64, "b" * 64, "c" * 64
MIN_BYTES = 64 * 1024**3


@pytest.fixture
def probe_code():
    source = SCRIPT.read_text(encoding="utf-8")
    matches = re.findall(r"(?ms)^\s*\$DockerStorageProbe = @'\n(.*?)\n'@", source)
    assert len(matches) == 1
    namespace = {"__name__": "offline_storage_control"}
    exec(compile(matches[0], str(SCRIPT), "exec"), namespace)
    return namespace


class OfflineDocker:
    def __init__(self, mode="healthy", stage="pre-build"):
        self.mode, self.stage = mode, stage
        self.calls, self.exists = [], False
        self.name = self.token = None

    def run(self, argv, **kwargs):
        assert argv[0] == "docker"
        assert kwargs == dict(
            capture_output=True, text=True, timeout=15 if argv[1] == "start" else 10, check=False
        )
        self.calls.append(argv)
        args = argv[1:]
        output, code = "", 0
        if args[:2] == ["image", "inspect"]:
            assert args == ["image", "inspect", "python:3.13-slim"]
            config = {} if self.mode != "explicit-null-volumes" else {"Volumes": None}
            if self.mode == "unexpected-image-volumes":
                config = {"Volumes": {"/unexpected": {}}}
            output = json.dumps([dict(Id=IMAGE, Config=config)])
            if self.mode == "missing-image":
                code = 1
        elif args[0] == "ps" and "label=com.docker.compose.service=postgres" in args:
            assert "label=com.docker.compose.project=" + PROJECT in args
            assert "status=running" in args
            output = PG
        elif args[0] == "inspect" and args[-1] == PG:
            output = json.dumps(
                dict(
                    id=PG,
                    labels={
                        "com.docker.compose.project": PROJECT,
                        "com.docker.compose.service": "postgres",
                    },
                    mounts=[
                        dict(
                            Type="bind",
                            Source="C:/canonical/00-extensions.sql",
                            Destination="/docker-entrypoint-initdb.d/00-extensions.sql",
                            RW=False,
                        ),
                        dict(
                            Type="volume",
                            Name=PROJECT + "_postgres_data",
                            Destination="/var/lib/postgresql/data",
                        )
                    ],
                )
            )
            if self.mode == "foreign-pg":
                output = output.replace(PROJECT, "foreign")
            if self.mode in ("bound-data-path", "duplicate-data-path"):
                value = json.loads(output)
                if self.mode == "bound-data-path":
                    value["mounts"][1]["Type"] = "bind"
                else:
                    value["mounts"].append(dict(value["mounts"][1]))
                output = json.dumps(value)
        elif args[:2] == ["volume", "inspect"]:
            assert args == ["volume", "inspect", PROJECT + "_postgres_data"]
            labels = {
                "com.docker.compose.project": PROJECT,
                "com.docker.compose.volume": "postgres_data",
            }
            if self.mode == "foreign-volume":
                labels["com.docker.compose.project"] = "foreign"
            output = json.dumps([dict(Name=PROJECT + "_postgres_data", Labels=labels)])
        elif args[0] == "create":
            assert {
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--entrypoint=python",
            }.issubset(args)
            assert IMAGE in args
            self.name = args[args.index("--name") + 1]
            self.token = args[args.index("--label") + 1].split("=", 1)[1]
            if self.stage in ("pre-postgres", "pre-browser"):
                expected_mount = (
                    "type=volume,source=" + PROJECT
                    + "_postgres_data,target=/var/lib/postgresql/data,readonly,volume-nocopy"
                )
                assert expected_mount in args
                assert not any("--volumes-from" in value or "type=bind" in value for value in args)
            self.exists = True
            output = CID
        elif args[0] == "start":
            assert args == ["start", "--attach", CID]
            if self.mode == "timeout":
                raise subprocess.TimeoutExpired(argv, 15)
            if self.mode == "probe-failed":
                code = 19
            paths = ["/"] + (
                ["/var/lib/postgresql/data"]
                if self.stage in ("pre-postgres", "pre-browser")
                else []
            )
            rows = [dict(path=p, available_bytes=MIN_BYTES, free_inodes=100000) for p in paths]
            if self.mode == "low-bytes":
                rows[0]["available_bytes"] -= 1
            if self.mode == "low-inodes":
                rows[0]["free_inodes"] -= 1
            if self.mode == "low-pg":
                rows[1]["available_bytes"] = 0
            output = json.dumps(dict(version=1, filesystems=rows))
            if self.mode == "malformed":
                output = "not JSON"
        elif args[0] == "ps":
            assert "label=io.caseops.acceptance.storage-probe=" + self.token in args
            output = CID if self.exists else ""
        elif args[0] == "inspect" and args[-1] == CID:
            output = json.dumps(
                dict(
                    name="/" + self.name,
                    labels={
                        "io.caseops.acceptance.storage-probe": self.token
                        if self.mode != "foreign-probe"
                        else "foreign"
                    },
                )
            )
        elif args[0] == "rm":
            assert args == ["rm", "--force", CID]
            if self.mode == "cleanup-failed":
                code = 19
            else:
                self.exists = False
        else:
            raise AssertionError("Unexpected offline Docker operation")
        return subprocess.CompletedProcess(argv, code, output, "private stderr is never retained")


@pytest.mark.parametrize("stage", ["pre-build", "post-build", "pre-postgres", "pre-browser"])
@pytest.mark.parametrize("mode", ["healthy", "explicit-null-volumes"])
def test_exact_threshold_accepts_and_reaps_only_owned_probe(probe_code, stage, mode):
    fake = OfflineDocker(stage=stage, mode=mode)
    probe_code["subprocess"] = SimpleNamespace(
        run=fake.run, TimeoutExpired=subprocess.TimeoutExpired
    )
    result = probe_code["probe"](PROJECT, RELEASE, stage, "C:/owned directory/compose.yml")
    assert result["status"] == "passed" and result["cleanup_complete"] is True
    assert not fake.exists
    assert len([c for c in fake.calls if c[1] == "rm"]) == 1
    assert all("prune" not in c and "pull" not in c and "build" not in c for c in fake.calls)


@pytest.mark.parametrize(
    "mode,error,clean",
    [
        ("missing-image", "docker_command_failed", True),
        ("unexpected-image-volumes", "invalid_image_identity", True),
        ("low-bytes", "insufficient_headroom", True),
        ("low-inodes", "insufficient_headroom", True),
        ("low-pg", "insufficient_headroom", True),
        ("probe-failed", "docker_command_failed", True),
        ("malformed", "invalid_probe_result", True),
        ("timeout", "docker_command_timeout", True),
        ("foreign-pg", "foreign_postgres_mount", True),
        ("foreign-volume", "foreign_postgres_mount", True),
        ("bound-data-path", "foreign_postgres_mount", True),
        ("duplicate-data-path", "foreign_postgres_mount", True),
        ("foreign-probe", "probe_cleanup_failed", False),
        ("cleanup-failed", "probe_cleanup_failed", False),
    ],
)
def test_refuses_without_expensive_work_and_preserves_cleanup_failures(
    probe_code, mode, error, clean
):
    fake = OfflineDocker(mode=mode, stage="pre-postgres")
    probe_code["subprocess"] = SimpleNamespace(
        run=fake.run, TimeoutExpired=subprocess.TimeoutExpired
    )
    result = probe_code["probe"](PROJECT, RELEASE, "pre-postgres", "owned compose.yml")
    assert result["status"] == "refused" and result["error"] == error
    assert result["cleanup_complete"] is clean
    assert "private stderr" not in json.dumps(result)
    assert all(
        "build" not in call and "exec" not in call and "prune" not in call for call in fake.calls
    )
    if mode == "foreign-probe":
        assert not any(c[1] == "rm" for c in fake.calls)


@pytest.mark.parametrize(
    "field,value",
    [
        ("available_bytes", "68719476736"),
        ("available_bytes", -1),
        ("available_bytes", 2**63),
        ("free_inodes", True),
        ("free_inodes", 100000.5),
        ("free_inodes", None),
        ("path", "C:/"),
    ],
)
def test_rejects_malformed_filesystem_facts(probe_code, field, value):
    row = dict(path="/", available_bytes=MIN_BYTES, free_inodes=100000)
    row[field] = value
    with pytest.raises(ValueError, match="invalid_measurement"):
        probe_code["measurements"](dict(version=1, filesystems=[row]), ["/"])


def test_storage_admission_precedes_every_expensive_boundary():
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index('Assert-DockerStorageHeadroom -Stage "pre-build"') < source.index(
        "build --pull api web"
    )
    assert (
        source.index("build --pull api web")
        < source.index('Assert-DockerStorageHeadroom -Stage "post-build"')
        < source.index("up --detach --wait")
    )
    assert source.index('Assert-DockerStorageHeadroom -Stage "pre-postgres"') < source.index(
        "Invoke-IsolatedNativePostgresGate -Validation"
    )
    launch = source.split("function Invoke-CandidatePlaywright {", 1)[1].split(
        "function Get-ComposeServiceState", 1
    )[0]
    assert launch.index('Assert-DockerStorageHeadroom -Stage "pre-browser"') < launch.index(
        "$PlaywrightCli test"
    )
    assert "tests\\docker-storage-headroom-guard.ps1" in source


@pytest.mark.parametrize("shell", ["powershell", "pwsh"] if os.name == "nt" else ["pwsh"])
def test_actual_powershell_admission_controls_are_offline(shell, tmp_path):
    executable = shutil.which(shell)
    assert executable, f"Required native shell is missing: {shell}"
    evidence = tmp_path / "retained controls"
    child = subprocess.run(
        [
            executable,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "tests/docker-storage-headroom-guard.ps1"),
            "-EvidenceDirectory",
            str(evidence),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=120,
        check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    inventory = json.loads((evidence / "guard-inventory.json").read_text(encoding="utf-8-sig"))
    rows = [
        json.loads(line)
        for line in (evidence / "guard-results.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    assert len(inventory) == len(rows) == 18
    assert [r["nodeid"] for r in rows] == inventory
    assert all(r["outcome"] == "passed" for r in rows)
    assert all(r["expensive_calls"] == 0 for r in rows[4:])
    assert (
        json.loads((evidence / "guard-completion.json").read_text(encoding="utf-8-sig"))[
            "exit_code"
        ]
        == 0
    )
