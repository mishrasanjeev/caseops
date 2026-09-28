"""Execute the Docker acceptance harness guards (2026-09-28).

`scripts/verify-docker.ps1` runs both guards when an acceptance run starts.
Running them here too means a harness change cannot quietly drop a guard's
behaviour between workstation runs. Each guard executes the harness's own
functions, extracted from its PowerShell syntax tree, and is launched from an
unrelated working directory: on 2026-09-28 the harness ran another
checkout's browser suite because Playwright resolved its config from the
caller's working directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GUARDS = {
    "tests/docker-candidate-source-guard.ps1": (
        "[docker-acceptance] candidate-source guard: 4 regression cases passed"
    ),
    "tests/docker-acceptance-repo-root-guard.ps1": (
        "[docker-acceptance] repository-root guard: 14 regression cases passed"
    ),
}


def _required_tool(*names: str) -> str:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    wanted = " or ".join(names)
    if os.environ.get("CI"):
        pytest.fail(f"CI must provide {wanted} to execute the Docker acceptance guards")
    pytest.skip(f"{wanted} is not installed")


@pytest.mark.parametrize("guard", sorted(GUARDS))
def test_docker_acceptance_guard_passes_from_an_unrelated_directory(
    guard: str, tmp_path: Path
) -> None:
    shell = _required_tool("pwsh", "powershell")
    _required_tool("node")
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / guard),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert GUARDS[guard] in result.stdout, output
    assert list(tmp_path.iterdir()) == [], "a guard wrote into the caller's directory"
