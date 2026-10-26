"""Offline request receipts for issue561's companion verification clients."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[3]
HEADER = "X-CaseOps-Automated-Test"
VALUE = "no-paid-providers"
API = "https://api.invalid"
WEB = "https://web.invalid"
PYTHON_CLIENTS = (
    "prod_billing_safe_smoke.py",
    "prod_billing_authenticated_smoke.py",
    "run_ip_golden_queries.py",
    "prod_password_reset_smoke.py",
    "write_machine_readiness_evidence.py",
)
CURL_CLIENTS = (
    ("deploy-prod.sh", 0),
    ("verify-release.sh", 0),
    ("verify-release.sh", 1),
    ("cron/ingest-vm-watchdog.sh", 0),
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("External transport is forbidden in marker regressions")

    with asyncio.Runner() as runner:
        # Windows initializes its local self-pipe before application transport is fenced.
        runner.get_loop()
        monkeypatch.setattr(socket.socket, "connect", denied)
        monkeypatch.setattr(socket, "create_connection", denied)
        monkeypatch.setattr(urllib.request, "urlopen", denied)
        yield runner


def _load(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(
        f"marker_regression_{Path(name).stem}", ROOT / "scripts" / name
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    spec.loader.exec_module(module)
    return module


class Response(io.BytesIO):
    def __init__(self, body=b"{}", status=200):
        super().__init__(body)
        self.status = status
        self.headers = {"content-type": "application/json"}
        self.read_limits = []

    def read(self, size=-1):
        self.read_limits.append(size)
        return super().read(size)


def _capture(monkeypatch, owner, answers):
    calls = []
    pending = iter(answers)

    def open_request(request, *, timeout):
        response = next(pending)
        calls.append((request, timeout, response))
        return response

    monkeypatch.setattr(owner, "urlopen", open_request)
    return calls


def _assert_request(call, url, method, headers, body=None, timeout=20, read_limit=1_000_000):
    request, actual_timeout, response = call
    assert request.full_url == url
    assert request.get_method() == method
    assert request.data == body
    assert actual_timeout == timeout
    assert response.read_limits == [read_limit]
    assert {key.lower(): value for key, value in request.header_items()} == {
        key.lower(): value for key, value in {**headers, HEADER: VALUE}.items()
    }


def _curl_commands(name):
    source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    return re.findall(r"\$\((curl [^\n]+?)\)", source)


def test_exact_companion_request_constructor_inventory():
    python_sites = {}
    for name in PYTHON_CLIENTS:
        tree = ast.parse((ROOT / "scripts" / name).read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        names = [
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
            for node in calls
        ]
        python_sites[name] = (names.count("Request"), names.count("urlopen"))
    assert python_sites == {
        "prod_billing_safe_smoke.py": (1, 1),
        "prod_billing_authenticated_smoke.py": (1, 1),
        "run_ip_golden_queries.py": (1, 1),
        "prod_password_reset_smoke.py": (1, 1),
        "write_machine_readiness_evidence.py": (1, 1),
    }
    assert {name: len(_curl_commands(name)) for name, _ in CURL_CLIENTS} == {
        "deploy-prod.sh": 1,
        "verify-release.sh": 2,
        "cron/ingest-vm-watchdog.sh": 1,
    }
    powershell = (ROOT / "scripts/verify-release.ps1").read_text(encoding="utf-8")
    assert powershell.count("Start-Process -FilePath $curlExe") == 1
    shell = (ROOT / "scripts/verify-release.sh").read_text(encoding="utf-8")
    assert re.findall(r'^\s*url_check "[^"]+" "\$(\w+)" "(\d+)"$', shell, re.M) == [
        ("API_HEALTH_URL", "200"),
        ("WEB_URL", "200"),
        ("CODE_AVAILABLE_URL", "401"),
        ("REMINDERS_URL", "401"),
    ]
    assert re.findall(r"^\s+build_check$", shell, re.M) == ["  build_check"]
    assert re.findall(
        r'Invoke-UrlCheck -Name "[^"]+" -Url \$(\w+) -ExpectedStatus (\d+)', powershell
    ) == [
        ("ApiHealthUrl", "200"),
        ("WebUrl", "200"),
        ("CodeAvailableUrl", "401"),
        ("RemindersUrl", "401"),
        ("BuildInfoUrl", "200"),
    ]


def test_public_smoke_exact_four_request_inventory(monkeypatch):
    module = _load(monkeypatch, "prod_billing_safe_smoke.py")
    calls = _capture(
        monkeypatch,
        module,
        [
            Response(b'{"status":"ok"}'),
            Response(b'{"plans":[{}]}'),
            Response(b"CaseOps pricing"),
            Response(status=401),
        ],
    )
    assert module.main(["--api-base", API, "--web-base", WEB, "--timeout", "7.5"]) == 0
    assert len(calls) == 4
    for call, url in zip(
        calls,
        [
            API + "/api/health",
            API + "/api/billing/plans",
            WEB + "/pricing",
            API + "/api/platform-admin/overview",
        ],
        strict=True,
    ):
        _assert_request(
            call,
            url,
            "GET",
            {
                "Accept": "application/json,text/html,text/plain,*/*",
                "User-Agent": "caseops-prod-billing-safe-smoke/1.0",
            },
            timeout=7.5,
        )


@pytest.mark.parametrize("auth", ["bearer", "cookie", "both"])
def test_authenticated_smoke_exact_nine_request_inventory(monkeypatch, auth):
    module = _load(monkeypatch, "prod_billing_authenticated_smoke.py")
    monkeypatch.setenv("CASEOPS_SMOKE_API_BASE", API)
    monkeypatch.delenv("CASEOPS_SMOKE_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("CASEOPS_SMOKE_COOKIE", raising=False)
    headers = {"Accept": "application/json,text/csv,*/*"}
    if auth in {"bearer", "both"}:
        monkeypatch.setenv("CASEOPS_SMOKE_BEARER_TOKEN", "test-only-bearer")
        headers["Authorization"] = "Bearer test-only-bearer"
    if auth in {"cookie", "both"}:
        monkeypatch.setenv("CASEOPS_SMOKE_COOKIE", "session=test-only-cookie")
        headers["Cookie"] = "session=test-only-cookie"
    calls = _capture(monkeypatch, module, [Response() for _ in range(9)])
    assert module.main() == 0
    paths = [
        "/api/platform-admin/overview",
        "/api/platform-admin/profit-report",
        "/api/platform-admin/cost-profiles",
        "/api/platform-admin/integrations",
        "/api/platform-admin/provider-events",
        "/api/billing/current",
        "/api/billing/credit-ledger/export",
        "/api/billing/payments/export",
        "/api/billing/reports/spend/export",
    ]
    assert len(calls) == 9
    for call, path in zip(calls, paths, strict=True):
        _assert_request(call, API + path, "GET", headers)


def test_golden_queries_capture_each_authenticated_post(monkeypatch):
    module = _load(monkeypatch, "run_ip_golden_queries.py")
    answer = json.dumps(
        {
            "outcome": "results_found",
            "results": [{"title": "patent"}],
            "corpus_coverage": {"index_state": "ready"},
        }
    ).encode()
    calls = _capture(monkeypatch, module.request, [Response(answer), Response(answer)])
    rows = [
        {
            "id": f"IP-GOLDEN-{mode}",
            "query": "patent review",
            "mode": mode,
            "minimum_results": 1,
            "expected_terms": ["patent"],
        }
        for mode in ("keyword", "contextual")
    ]
    assert len(module._execute(API, "test-only-bearer", rows, 8.5)) == 2
    assert len(calls) == 2
    for call, row in zip(calls, rows, strict=True):
        body = json.dumps(
            {
                "query": "patent review",
                "mode": row["mode"],
                "limit": 10,
                "language": "en",
                "forum_level": None,
                "court_name": None,
                "document_type": None,
            }
        ).encode()
        _assert_request(
            call,
            API + "/api/authorities/search",
            "POST",
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": "Bearer test-only-bearer",
            },
            body,
            timeout=8.5,
            read_limit=-1,
        )


def test_golden_fixture_validation_has_no_http_requests(monkeypatch):
    module = _load(monkeypatch, "run_ip_golden_queries.py")
    monkeypatch.setattr(sys, "argv", ["run_ip_golden_queries.py"])
    assert module.main() == 0


def test_password_reset_captures_one_post_without_sending(monkeypatch):
    module = _load(monkeypatch, "prod_password_reset_smoke.py")
    monkeypatch.setenv("CASEOPS_SMOKE_API_BASE", API)
    monkeypatch.setenv("CASEOPS_RESET_SMOKE_EMAIL", "qa@example.invalid")
    monkeypatch.setenv("CASEOPS_RESET_SMOKE_COMPANY_SLUG", "test-only-workspace")
    calls = _capture(monkeypatch, module, [Response()])
    assert module.main() == 0
    assert len(calls) == 1
    body = json.dumps(
        {"email": "qa@example.invalid", "company_slug": "test-only-workspace"}
    ).encode()
    _assert_request(
        calls[0],
        API + "/api/auth/password-reset/start",
        "POST",
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        body,
        read_limit=100_000,
    )


@pytest.mark.parametrize("tamper", ["none", "body", "signature", "stale", "missing"])
def test_machine_evidence_marker_preserves_exact_body_authentication(
    monkeypatch, no_network, tamper
):
    from caseops_api.api.routes import machine_readiness as route
    from caseops_api.core.automated_test_context import (
        paid_providers_blocked_for_request,
        reset_automated_test_request,
        set_automated_test_request,
    )

    module = _load(monkeypatch, "write_machine_readiness_evidence.py")
    secret = "test-only-machine-secret-" * 2
    monkeypatch.setenv("CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET", secret)
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 1_000_000))
    monkeypatch.setattr(route, "time", SimpleNamespace(time=lambda: 1_000_000))
    monkeypatch.setattr(
        route, "get_settings", lambda: SimpleNamespace(machine_readiness_evidence_secret=secret)
    )
    result = {
        "release_sha": "a" * 40,
        "producer": "github-actions/prod-verify",
        "run_id": "test-only-run",
        "recorded_count": 1,
    }
    calls = _capture(monkeypatch, module.urllib.request, [Response(json.dumps(result).encode())])
    assert (
        module.main(
            [
                "--api-base",
                API,
                "--producer",
                result["producer"],
                "--release-sha",
                result["release_sha"],
                "--run-id",
                result["run_id"],
                "--evidence-ref",
                "https://evidence.invalid/run",
                "--operational",
                "public_claims_reviewed=pass",
            ]
        )
        == 0
    )
    assert len(calls) == 1
    outgoing = calls[0][0]
    body = json.dumps(
        {
            "schema": "caseops.machine-readiness-write/v1",
            **{key: result[key] for key in ("producer", "release_sha", "run_id")},
            "items": [
                {
                    "kind": "operational_gate",
                    "subject": "public_claims_reviewed",
                    "conclusion": "pass",
                    "evidence_ref": "https://evidence.invalid/run",
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = module.machine_readiness_signature(secret=secret, timestamp="1000000", body=body)
    _assert_request(
        calls[0],
        API + "/api/internal/machine-readiness/evidence",
        "POST",
        {
            "Content-Type": "application/json",
            "X-CaseOps-Machine-Timestamp": "1000000",
            "X-CaseOps-Machine-Signature": signature,
        },
        body,
        timeout=30,
        read_limit=-1,
    )

    async def receive():
        return {
            "type": "http.request",
            "body": body + (b" " if tamper == "body" else b""),
            "more_body": False,
        }

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/evidence",
            "headers": [
                (key.lower().encode(), value.encode()) for key, value in outgoing.header_items()
            ],
        },
        receive,
    )
    timestamp = "999000" if tamper == "stale" else "1000000"
    signature = "invalid" if tamper == "signature" else None if tamper == "missing" else signature
    token = set_automated_test_request(request.headers.get(HEADER))
    try:
        assert paid_providers_blocked_for_request()
        if tamper == "none":
            payload = no_network.run(
                route.require_machine_readiness_evidence_auth(
                    request, timestamp=timestamp, signature=signature
                )
            )
            assert payload.release_sha == result["release_sha"]
        else:
            with pytest.raises(HTTPException) as exc:
                no_network.run(
                    route.require_machine_readiness_evidence_auth(
                        request, timestamp=timestamp, signature=signature
                    )
                )
            assert exc.value.status_code == 401
    finally:
        reset_automated_test_request(token)


def _bash_path(path):
    value = path.resolve().as_posix()
    return f"/{value[0].lower()}{value[2:]}" if os.name == "nt" else value


def _bash():
    path = shutil.which("bash")
    if os.name == "nt":
        path = "C:/Program Files/Git/bin/bash.exe"
    assert path and Path(path).is_file(), "Installed Bash required; never install during tests"
    return path


def _guarded_curl(tmp_path, command, *, install=True):
    stub = tmp_path / "curl"
    if install:
        stub.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            'printf \'%s\\0\' "$@" >> "$MARKER_ARGV_FILE"\n'
            "printf '%s' '200'\n",
            encoding="utf-8",
            newline="\n",
        )
        stub.chmod(0o755)
        assert os.access(stub, os.X_OK), "Stub must be executable before launching its shell"
    guard = (
        'export PATH="$1:$PATH"; '
        '[[ "$(command -v curl)" == "$1/curl" && -x "$1/curl" ]] || exit 99; '
    )
    log = tmp_path / "request.argv"
    env = {
        **os.environ,
        "MARKER_ARGV_FILE": _bash_path(log),
        "url": API + "/api/health?q=%2F&x=1",
        "BUILD_INFO_URL": API + "/api/build",
        "body_file": "body output.txt",
    }
    if install:
        receipt = tmp_path / "executable.argv"
        proof = subprocess.run(
            [
                _bash(),
                "-c",
                guard + "curl --marker-stub-self-test",
                "stub-proof",
                _bash_path(tmp_path),
            ],
            env={**env, "MARKER_ARGV_FILE": _bash_path(receipt)},
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert proof.returncode == 0, proof.stdout + proof.stderr
        assert receipt.read_bytes() == b"--marker-stub-self-test\0"
    result = subprocess.run(
        [_bash(), "-c", guard + command, "request-proof", _bash_path(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, log


@pytest.mark.parametrize(
    ("name", "index"),
    CURL_CLIENTS,
    ids=["deploy-health", "signoff-url", "signoff-build", "watchdog-health"],
)
def test_native_curl_argv_from_only_the_actual_request_expression(tmp_path, name, index):
    result, log = _guarded_curl(tmp_path, _curl_commands(name)[index])
    assert result.returncode == 0, result.stdout + result.stderr
    args = log.read_bytes().decode().removesuffix("\0").split("\0")
    if name == "deploy-prod.sh":
        expected = [
            "-fsS",
            "--connect-timeout",
            "10",
            "--max-time",
            "30",
            "--header",
            HEADER + ":" + VALUE,
            "https://api.caseops.ai/api/health",
        ]
    elif name == "verify-release.sh":
        expected = [
            "-sS",
            "-L",
            "--header",
            HEADER + ":" + VALUE,
            "-o",
            "body output.txt",
            "-w",
            "%{http_code}",
            API + ("/api/build" if index else "/api/health?q=%2F&x=1"),
        ]
    else:
        expected = [
            "-sS",
            "-m",
            "60",
            "--header",
            HEADER + ":" + VALUE,
            "https://api.caseops.ai/api/health/ingest",
        ]
    assert args == expected


def test_native_curl_guard_refuses_path_fallback(tmp_path):
    result, log = _guarded_curl(tmp_path, "curl --must-never-run", install=False)
    assert result.returncode == 99
    assert not log.exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows curl.exe argument boundary")
def test_native_powershell_curl_argument_list(tmp_path):
    shell = shutil.which("powershell.exe")
    assert shell, "Use installed Windows PowerShell, without dependency installation"
    source = (ROOT / "scripts/verify-release.ps1").read_text(encoding="utf-8")
    commands = re.findall(
        r"\$process = Start-Process -FilePath \$curlExe .*?\$stderrFile", source, re.S
    )
    assert len(commands) == 1
    harness = tmp_path / "capture.ps1"
    harness.write_text(
        """$ErrorActionPreference = 'Stop'
Add-Type -OutputAssembly (Join-Path $PSScriptRoot 'curl.exe') `
    -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
using System.Text;
public class CurlMarkerStub {
    public static void Main(string[] args) {
        File.WriteAllText(Environment.GetEnvironmentVariable("MARKER_ARGV_FILE"),
            string.Join("\\0", args) + "\\0", new UTF8Encoding(false));
        Console.Write("200");
    }
}
'@
$env:PATH = $PSScriptRoot + ';' + $env:PATH
$curlExe = (Get-Command curl.exe -ErrorAction Stop).Source
if ($curlExe -ne (Join-Path $PSScriptRoot 'curl.exe')) { throw 'PATH fallback refused' }
$env:MARKER_ARGV_FILE = Join-Path $PSScriptRoot 'executable.argv'
& $curlExe --marker-stub-self-test
if ($LASTEXITCODE -ne 0) { throw 'Stub is not executable' }
$env:MARKER_ARGV_FILE = Join-Path $PSScriptRoot 'request.argv'
$bodyFile = Join-Path $PSScriptRoot 'body.txt'
$stdoutFile = Join-Path $PSScriptRoot 'stdout.txt'
$stderrFile = Join-Path $PSScriptRoot 'stderr.txt'
$Url = 'https://api.invalid/api/build?q=%2F&x=1'
"""
        + commands[0]
        + "\nif ($process.ExitCode -ne 0) { throw 'Stub request failed' }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "executable.argv").read_bytes() == b"--marker-stub-self-test\0"
    args = (tmp_path / "request.argv").read_bytes().decode().removesuffix("\0").split("\0")
    assert args == [
        "-sS",
        "-L",
        "--header",
        HEADER + ":" + VALUE,
        "-o",
        str(tmp_path / "body.txt"),
        "-w",
        "%{http_code}",
        "https://api.invalid/api/build?q=%2F&x=1",
    ]
