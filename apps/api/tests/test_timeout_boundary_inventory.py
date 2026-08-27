from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = REPO_ROOT / "apps" / "api" / "src"
WEB_SOURCE = REPO_ROOT / "apps" / "web"
WEB_TIMEOUT_CLIENT = WEB_SOURCE / "lib" / "api" / "client.ts"
DIRECT_FETCH = re.compile(r"\bfetch\s*\(")


def _python_files() -> list[Path]:
    return sorted(API_SOURCE.rglob("*.py"))


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        owner = call.func.value.id if isinstance(call.func.value, ast.Name) else ""
        return f"{owner}.{call.func.attr}" if owner else call.func.attr
    return ""


def _has_timeout(call: ast.Call, name: str) -> bool:
    if any(keyword.arg == "timeout" for keyword in call.keywords):
        return True
    return name == "urlopen" and len(call.args) >= 3


def _direct_fetch_lines(source: str) -> list[str]:
    return [
        line
        for line in source.splitlines()
        if not line.lstrip().startswith(("//", "*")) and DIRECT_FETCH.search(line)
    ]


def test_first_party_web_fetches_use_the_shared_deadline_boundary() -> None:
    offenders: list[str] = []
    for path in sorted(WEB_SOURCE.rglob("*")):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        if any(part in {".next", "node_modules"} for part in path.parts):
            continue
        matches = _direct_fetch_lines(path.read_text(encoding="utf-8"))
        if path == WEB_TIMEOUT_CLIENT:
            assert len(matches) == 1
        elif matches:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_python_http_clients_declare_finite_timeouts() -> None:
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name in {"httpx.Client", "httpx.AsyncClient", "urlopen"} and not _has_timeout(
                node, name
            ):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}:{name}")
    assert offenders == []
