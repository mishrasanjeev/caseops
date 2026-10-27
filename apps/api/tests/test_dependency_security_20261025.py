"""QG-SEC-004: patched cache-lock closure without external model/provider calls."""

import importlib.metadata
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from filelock import Timeout
from huggingface_hub.utils import WeakFileLock
from packaging.version import Version


@pytest.mark.parametrize(
    "name,minimum",
    [
        ("opentelemetry-api", "1.45.1"),
        ("opentelemetry-sdk", "1.45.1"),
        ("opentelemetry-exporter-otlp-proto-http", "1.45.1"),
        ("opentelemetry-instrumentation-fastapi", "0.66b1"),
        ("opentelemetry-instrumentation-sqlalchemy", "0.66b1"),
        ("opentelemetry-instrumentation-httpx", "0.66b1"),
    ],
)
def test_observability_manifest_and_lock_exclude_vulnerable_tracestate_parser(name, minimum):
    api = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((api / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((api / "uv.lock").read_text(encoding="utf-8"))
    assert f"{name}>={minimum}" in manifest["project"]["optional-dependencies"]["observability"]
    rows = [row for row in lock["package"] if row["name"] == name]
    assert len(rows) == 1
    assert Version(rows[0]["version"]) >= Version(minimum)
    assert rows[0]["wheels"]
    assert all(wheel["hash"].startswith("sha256:") for wheel in rows[0]["wheels"])


@pytest.mark.parametrize("whitespace", [" ", "\t"])
def test_patched_optional_tracestate_parser_uses_literal_comma_split(whitespace, caplog):
    trace = pytest.importorskip(
        "opentelemetry.trace", reason="Observability extra is not installed"
    )
    assert Version(importlib.metadata.version("opentelemetry-api")) >= Version("1.45.1")
    splits = []

    class Header(str):
        def split(self, sep=None, maxsplit=-1):
            splits.append((sep, maxsplit))
            return super().split(sep, maxsplit)

    # Exercise the upstream fix without a load-sensitive wall-clock assertion.
    malformed = Header("a=b" + whitespace * 100_000 + "x")
    with caplog.at_level("CRITICAL", logger="opentelemetry.trace.span"):
        assert list(trace.TraceState.from_header([malformed]).items()) == []
    assert splits == [(",", -1)]
    valid = trace.TraceState.from_header([f"a=b{whitespace},{whitespace}vendor=legal"])
    assert list(valid.items()) == [
        ("a", "b"), ("vendor", "legal"),
    ]


def test_filelock_manifest_lock_and_installed_distribution_are_reviewed():
    api = Path(__file__).resolve().parents[1]
    manifest = tomllib.loads((api / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((api / "uv.lock").read_text(encoding="utf-8"))
    assert "filelock==4.2.4" in manifest["project"]["dependencies"]
    rows = [row for row in lock["package"] if row["name"] == "filelock"]
    assert len(rows) == 1
    assert rows[0]["version"] == "4.2.4"
    assert all(wheel["hash"].startswith("sha256:") for wheel in rows[0]["wheels"])
    assert importlib.metadata.version("filelock") == "4.2.4"


def test_huggingface_cache_lock_excludes_another_process_and_recovers(tmp_path):
    lock_path = tmp_path / "model-cache.lock"
    code = """
import json,sys
from filelock import Timeout
from huggingface_hub.utils import WeakFileLock
try:
    with WeakFileLock(sys.argv[1], timeout=0.1):
        print(json.dumps({'acquired': True}))
except Timeout:
    print(json.dumps({'acquired': False}))
"""

    def child():
        result = subprocess.run(
            [sys.executable, "-c", code, str(lock_path)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return json.loads(result.stdout)

    with WeakFileLock(lock_path, timeout=1):
        assert child() == {"acquired": False}
        with pytest.raises(Timeout), WeakFileLock(lock_path, timeout=0.01):
            pass
    assert child() == {"acquired": True}
