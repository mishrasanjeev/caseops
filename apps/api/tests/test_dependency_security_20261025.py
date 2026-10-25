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
