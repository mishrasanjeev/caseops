from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from caseops_api.services.http_retries import request_with_retries


def test_request_with_retries_retries_transient_status() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = request_with_retries(
            "GET",
            "https://provider.example.test/resource",
            client=client,
            backoff_seconds=0,
        )

    assert response.json() == {"ok": True}
    assert calls == [
        "https://provider.example.test/resource",
        "https://provider.example.test/resource",
    ]


def test_request_with_retries_retries_transport_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("network unavailable", request=request)
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = request_with_retries(
            "GET",
            "https://provider.example.test/resource",
            client=client,
            backoff_seconds=0,
        )

    assert response.json() == {"ok": True}
    assert calls == 2


def test_request_with_retries_does_not_retry_non_transient_status() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            request_with_retries(
                "GET",
                "https://provider.example.test/missing",
                client=client,
                backoff_seconds=0,
            )

    assert calls == 1


def test_request_with_retries_refuses_unsafe_methods() -> None:
    with pytest.raises(ValueError, match="unsafe HTTP method"):
        request_with_retries(
            "POST",
            "https://provider.example.test/create",
            backoff_seconds=0,
        )


def test_request_with_retries_uses_injected_client_get_method() -> None:
    client = MagicMock()
    client.get.side_effect = [
        httpx.Response(503, json={"error": "temporary"}),
        httpx.Response(200, json={"ok": True}),
    ]

    response = request_with_retries(
        "GET",
        "https://provider.example.test/resource",
        client=client,
        backoff_seconds=0,
    )

    assert response.json() == {"ok": True}
    assert client.get.call_count == 2
    client.request.assert_not_called()
