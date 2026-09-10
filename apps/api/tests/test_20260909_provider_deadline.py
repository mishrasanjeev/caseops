from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import httpx
import pytest

from caseops_api.services.case_tracking_providers import (
    CaseSearchQuery,
    CaseTrackingProviderError,
    EcourtsIndiaApiProvider,
    case_tracking_transport_budget,
    download_provider_source,
)


@pytest.mark.parametrize("phase", ["headers", "body", "retry"])
def test_provider_deadline_includes_headers_body_and_retry_sleep(phase):
    calls = []
    closed = []

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"data":'
            await asyncio.sleep(5)
            yield b"{}}"

        async def aclose(self):
            closed.append(True)

    async def handler(request):
        calls.append(request)
        if phase == "headers":
            await asyncio.sleep(5)
        if phase == "retry":
            return httpx.Response(503)
        return httpx.Response(200, stream=SlowBody())

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.invalid",
        token="deterministic",
        transport=httpx.MockTransport(handler),
        request_budget_seconds=0.05,
    )
    started = time.monotonic()
    with pytest.raises(CaseTrackingProviderError) as raised:
        provider.search_cases(query=CaseSearchQuery(case_number="1/2026", court_code="DLHC"))
    assert raised.value.response_class == "timeout"
    assert time.monotonic() - started < 0.8
    assert len(calls) == 1
    if phase == "body":
        assert closed == [True]


def test_bulk_deadline_keeps_completed_cases_and_stops_unstarted_details():
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        if request.method == "POST":
            assert request.url.path.endswith("/bulk-refresh-status")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "results": [
                            {
                                "cnr": cnr,
                                "status": "COMPLETED",
                                "requestedAt": datetime.now(UTC).isoformat(),
                            }
                            for cnr in json.loads(request.content)["cnrs"]
                        ]
                    }
                },
            )
        if request.url.path.endswith("DLHC010012352026"):
            await asyncio.sleep(5)
        return httpx.Response(
            200,
            json={"cnr_number": request.url.path.rsplit("/", 1)[1], "case_title": "Verified case"},
        )

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.invalid",
        token="deterministic",
        transport=httpx.MockTransport(handler),
        bulk_budget_seconds=0.05,
    )
    started = time.monotonic()
    result = provider.refresh_cases(
        cnrs=["DLHC010012342026", "DLHC010012352026", "DLHC010012362026"]
    )
    assert time.monotonic() - started < 0.8
    assert [row.cnr_number for row in result.snapshots] == ["DLHC010012342026"]
    assert set(result.errors) == {"DLHC010012352026", "DLHC010012362026"}
    assert all("[timeout]" in message for message in result.errors.values())
    assert len(paths) == 3
    assert result.confirmed_cost_minor_by_cnr["DLHC010012342026"] == 150
    assert result.uncertain_charge_cnrs == {"DLHC010012352026"}


def test_exhausted_parent_budget_makes_no_provider_request_and_restores_scope():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"cnr_number": "DLHC010012342026", "case_title": "Verified"}
        )

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.invalid",
        token="deterministic",
        transport=httpx.MockTransport(handler),
    )
    with case_tracking_transport_budget(seconds=0):
        with pytest.raises(CaseTrackingProviderError, match="deadline"):
            provider.get_case_by_cnr(cnr="DLHC010012342026")
    assert calls == []
    assert provider.get_case_by_cnr(cnr="DLHC010012342026").cnr_number == "DLHC010012342026"
    assert len(calls) == 1


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_source_download_deadline_covers_the_complete_response(phase):
    closed = []
    calls = []

    class SourceBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"%PDF-1.4"
            await asyncio.sleep(5)

        async def aclose(self):
            closed.append(True)

    async def handler(request):
        calls.append(request)
        if phase == "headers":
            await asyncio.sleep(5)
        return httpx.Response(200, stream=SourceBody())

    started = time.monotonic()
    with pytest.raises(httpx.ReadTimeout, match="total deadline"):
        download_provider_source(
            url="https://provider.invalid/source",
            token="fixture",
            transport=httpx.MockTransport(handler),
            budget_seconds=0.05,
        )
    assert time.monotonic() - started < 0.8
    assert len(calls) == 1
    assert closed == ([True] if phase == "body" else [])


def test_source_download_does_not_follow_redirects_or_retry_unknown_outcomes():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    with pytest.raises(httpx.HTTPStatusError):
        download_provider_source(
            url="https://provider.invalid/source",
            token="fixture",
            transport=httpx.MockTransport(handler),
        )
    assert len(calls) == 1


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_real_loopback_transport_cancels_stalled_response_without_starvation(phase):
    entered, release = Event(), Event()
    paths = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            paths.append(self.path)
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")
                return
            entered.set()
            if phase == "headers":
                release.wait(3)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "1000")
                self.end_headers()
                self.wfile.write(b'{"data":')
                self.wfile.flush()
                release.wait(3)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    provider = EcourtsIndiaApiProvider(
        base_url=base, token="loopback-only", request_budget_seconds=0.25
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            started = time.monotonic()
            pending = pool.submit(provider.get_case_by_cnr, cnr="DLHC010012342026")
            assert entered.wait(2), "the real TCP request never reached the fixture"
            with httpx.Client(timeout=1, trust_env=False) as client:
                assert client.get(base + "/health").text == "ok"
                with pytest.raises(CaseTrackingProviderError) as error:
                    pending.result(timeout=2)
                assert error.value.response_class == "timeout"
                assert time.monotonic() - started < 2
                assert client.get(base + "/health").text == "ok"
            assert len([path for path in paths if path != "/health"]) == 1
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_case_provider_does_not_forward_authentication_to_redirects():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    provider = EcourtsIndiaApiProvider(
        base_url="https://provider.invalid",
        token="fixture",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CaseTrackingProviderError):
        provider.get_case_by_cnr(cnr="DLHC010012342026")
    assert len(calls) == 1
