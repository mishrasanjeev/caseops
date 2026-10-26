from __future__ import annotations

import importlib.util
import json
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "verify_deployed_release.py"
SPEC = importlib.util.spec_from_file_location("verify_deployed_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def identity(service: str, sha: str = "a" * 40):
    return MODULE.ReleaseIdentity(service, sha, f"caseops-{service}-00001-abc")


@pytest.mark.parametrize("service", ["api", "web"])
def test_fetch_identity_marks_actual_request_without_weakening_transport(
    monkeypatch: pytest.MonkeyPatch, service: str
) -> None:
    url = f"https://{service}.invalid/build?release=public"
    observed = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "service": service,
                    "release_sha": "a" * 40,
                    "revision": f"caseops-{service}-00001-abc",
                }
            ).encode()

    def transport(request, *, timeout):
        observed.append((request, timeout))
        return Response()

    monkeypatch.setattr(MODULE, "urlopen", transport)
    assert MODULE.fetch_identity(url, expected_service=service) == identity(service)
    assert len(observed) == 1
    request, timeout = observed[0]
    assert request.full_url == url
    assert request.get_method() == "GET"
    assert {name.lower(): value for name, value in request.header_items()} == {
        "accept": "application/json",
        "x-caseops-automated-test": "no-paid-providers",
    }
    assert timeout == MODULE.FETCH_TIMEOUT_SECONDS == 5


def test_fetch_identity_marks_failed_reads_and_preserves_certificate_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    failure = URLError(ssl.SSLCertVerificationError("synthetic untrusted certificate"))

    def transport(request, *, timeout):
        calls.append((request.full_url, dict(request.header_items()), timeout))
        raise failure

    monkeypatch.setattr(MODULE, "urlopen", transport)
    with pytest.raises(URLError) as caught:
        MODULE.fetch_identity("https://api.invalid/build", expected_service="api")
    assert caught.value is failure
    assert len(calls) == 1
    assert calls[0][0] == "https://api.invalid/build"
    assert {name.lower(): value for name, value in calls[0][1].items()} == {
        "accept": "application/json",
        "x-caseops-automated-test": "no-paid-providers",
    }
    assert calls[0][2] == 5


def test_wait_marks_every_bounded_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    now = 100.0
    calls = []
    sleeps = []

    def transport(request, *, timeout):
        calls.append((request, timeout))
        raise URLError("synthetic unavailable metadata")

    def sleeper(seconds):
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    monkeypatch.setattr(MODULE, "urlopen", transport)
    with pytest.raises(MODULE.ReleaseIdentityError, match="within 7s"):
        MODULE.wait_for_release(
            api_url="https://api.invalid/build",
            web_url="https://web.invalid/build",
            expected_sha="a" * 40,
            wait_seconds=7,
            interval_seconds=5,
            monotonic=lambda: now,
            sleeper=sleeper,
        )
    assert sleeps == [5.0, 2.0]
    assert len(calls) == 3
    for request, timeout in calls:
        assert request.full_url == "https://api.invalid/build"
        assert {name.lower(): value for name, value in request.header_items()}[
            "x-caseops-automated-test"
        ] == "no-paid-providers"
        assert timeout == 5


def test_cli_sends_marked_identity_reads_on_real_loopback_transport() -> None:
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append((self.path, dict(self.headers.items())))
            service = "api" if self.path == "/api/build" else "web"
            body = json.dumps(
                {
                    "service": service,
                    "release_sha": "a" * 40,
                    "revision": f"caseops-{service}-00001-abc",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--api-url",
                f"{origin}/api/build",
                "--web-url",
                f"{origin}/api/release-identity",
                "--expected-sha",
                "a" * 40,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "release_sha": "a" * 40,
        "api_revision": "caseops-api-00001-abc",
        "web_revision": "caseops-web-00001-abc",
    }
    assert [path for path, _headers in observed] == ["/api/build", "/api/release-identity"]
    for _path, headers in observed:
        normalized = {name.lower(): value for name, value in headers.items()}
        assert normalized["accept"] == "application/json"
        assert normalized["x-caseops-automated-test"] == "no-paid-providers"
        assert "cookie" not in normalized
        assert "authorization" not in normalized


def test_parse_identity_rejects_abbreviated_sha() -> None:
    with pytest.raises(MODULE.ReleaseIdentityError, match="exact 40-character"):
        MODULE.parse_identity(
            {
                "service": "api",
                "release_sha": "abcdef1",
                "revision": "caseops-api-00001-abc",
            },
            expected_service="api",
        )


def test_verify_pair_requires_api_web_and_expected_sha_to_match() -> None:
    assert MODULE.verify_pair(identity("api"), identity("web"), expected_sha="a" * 40) == "a" * 40

    with pytest.raises(MODULE.ReleaseIdentityError, match="mixed release"):
        MODULE.verify_pair(identity("api"), identity("web", "b" * 40))

    with pytest.raises(MODULE.ReleaseIdentityError, match="stale release"):
        MODULE.verify_pair(identity("api"), identity("web"), expected_sha="c" * 40)


def test_wait_rejects_invalid_expected_sha_before_network_io() -> None:
    calls: list[str] = []

    def fetcher(url: str, *, expected_service: str):
        calls.append(url)
        return identity(expected_service)

    with pytest.raises(MODULE.ReleaseIdentityError, match="exactly 40"):
        MODULE.wait_for_release(
            api_url="https://api.invalid/build",
            web_url="https://web.invalid/build",
            expected_sha="not-a-release",
            wait_seconds=180,
            interval_seconds=5,
            fetcher=fetcher,
        )

    assert calls == []


def test_wait_never_sleeps_past_its_deadline() -> None:
    now = 100.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    def sleeper(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    def fetcher(_url: str, *, expected_service: str):
        raise OSError(f"{expected_service} unavailable")

    with pytest.raises(MODULE.ReleaseIdentityError, match="within 7s"):
        MODULE.wait_for_release(
            api_url="https://api.invalid/build",
            web_url="https://web.invalid/build",
            expected_sha="a" * 40,
            wait_seconds=7,
            interval_seconds=5,
            fetcher=fetcher,
            monotonic=monotonic,
            sleeper=sleeper,
        )

    assert sleeps == [5.0, 2.0]
