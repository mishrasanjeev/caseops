"""Actual loopback socket proof; no DB, provider or production requests."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route

from caseops_api.api.routes.health import rate_identity_readiness
from caseops_api.core.canonical_redirects import CanonicalSlashRedirectMiddleware
from caseops_api.core.rate_identity import RateIdentityMiddleware, request_rate_identity
from tests import test_rate_identity_edge_20261009 as edge_tests
from tests.test_rate_identity_edge_20261009 import edge_headers, forward_headers

purpose_key = edge_tests.edge_key


async def inspect_scheme(request):
    return JSONResponse(
        {
            "scheme": request.url.scheme,
            "url": str(request.url_for("scheme")),
            "peer": request.client.host,
            "identity": request_rate_identity(request).client_ip,
        }
    )


# This test-only app is also used by the ignored native web/API chain proof.
app = Starlette(
    routes=[
        Route("/api/scheme", inspect_scheme, name="scheme"),
        Route("/api/health/rate-identity", rate_identity_readiness),
    ],
    middleware=[Middleware(RateIdentityMiddleware), Middleware(CanonicalSlashRedirectMiddleware)],
)


@pytest.fixture
def socket_client(purpose_key):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            proxy_headers=False,
            access_log=False,
            log_level="error",
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    try:
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "Isolated socket server failed to start"
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        ) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        assert not thread.is_alive(), "Owned socket server did not terminate"


def test_actual_socket_peer_and_http_scheme_ignore_raw_forwarding(socket_client):
    data = socket_client.get(
        "/api/scheme",
        headers={
            "x-forwarded-for": "198.51.100.99",
            "x-real-ip": "198.51.100.98",
            "x-forwarded-proto": "https",
        },
    ).json()
    assert data["scheme"] == "http" and data["url"].startswith("http://127.0.0.1:")
    assert data["peer"] == data["identity"] == "127.0.0.1"


def test_verified_https_scheme_preserves_url_for_without_mutating_peer(socket_client, purpose_key):
    data = socket_client.get(
        "/api/scheme",
        headers=edge_headers(purpose_key)
        | {"x-forwarded-for": "198.51.100.99", "x-forwarded-proto": "http"},
    ).json()
    assert data["scheme"] == "https" and data["url"].startswith("https://127.0.0.1:")
    assert data["identity"] == "192.0.2.4" and data["peer"] == "127.0.0.1"
    response = socket_client.get("/api/scheme/?campaign=a%20b", headers=edge_headers(purpose_key))
    assert (
        response.status_code == 307 and response.headers["location"] == "/api/scheme?campaign=a%20b"
    )


def test_actual_signed_health_get_is_nonidentifying(socket_client, purpose_key):
    response = socket_client.get("/api/health/rate-identity", headers=forward_headers(purpose_key))
    assert response.status_code == 200
    assert response.json()["ready"] is True and response.json()["provenance"] == "web-forward"
    assert set(response.json()) == {"ready", "provenance", "release_sha"}
    assert purpose_key not in response.text and "2001:db8" not in response.text


def test_actual_direct_forged_claims_are_not_authoritative(socket_client, purpose_key):
    response = socket_client.get(
        "/api/health/rate-identity",
        headers={"x-caseops-edge-client-ip": "192.0.2.4", "x-caseops-edge-attestation": "wrong"},
    )
    assert response.status_code == 403
    assert response.json()["ready"] is False and response.json()["provenance"] == "unavailable"
    assert set(response.json()) == {"ready", "provenance", "release_sha"}
