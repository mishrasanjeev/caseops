"""Real platform fallback and strict no-process/no-DNS fixture regressions."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from tests import pdf_offline_boundary_20261104 as boundary


def test_metadata_fixture_uses_real_platform_fallback_without_process_execution(tmp_path):
    api = Path(__file__).resolve().parents[1]
    fixture = Path(__file__).parent / "fixtures" / "pdf_offline_metadata_probe_20261104.py"
    result_path = tmp_path / "control.json"
    environment = {
        key: os.environ[key]
        for key in ("OS", "USERPROFILE", "APPDATA", "LOCALAPPDATA")
        if key in os.environ
    }
    environment.update(
        SystemRoot=r"C:\Windows",
        WINDIR=r"C:\Windows",
        COMSPEC=r"C:\Windows\System32\cmd.exe",
        PYTHONDONTWRITEBYTECODE="1",
        CASEOPS_PDF_OFFLINE_RECEIPT=str(tmp_path / "offline.json"),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            "-X",
            f"pycache_prefix={tmp_path / 'pycache'}",
            str(fixture),
            str(api),
            str(result_path),
        ],
        env=environment,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    proof = json.loads(result_path.read_bytes())
    assert proof["state"] == "REAL_METADATA_DENIAL_AND_SUBJECT_BOUNDARIES_PROVED"
    assert proof["native_CreateProcess_entries"] == 0
    assert proof["unknown_origin_subject_command_and_DNS_denied"] is True
    assert proof["platform_function_codes_unchanged"] is True
    assert proof["normal_metadata_receipt_precedes_subject"] is True
    assert proof["fresh_compiled_cache_prefix_verified"] is True
    assert proof["windows_native_control"] is (os.name == "nt")


def test_metadata_bootstrap_never_replaces_platform_cache_or_functions():
    source = Path(boundary.__file__).read_bytes()
    tree = ast.parse(source)
    assigned = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            assigned.extend(
                target.attr
                for target in targets
                if isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "platform"
            )
    assert assigned == []
    assert b"setattr(platform" not in source
    assert b"invalidate_caches" not in source
