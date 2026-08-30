from __future__ import annotations

import time
from collections.abc import Container
from typing import Any

import httpx

RETRYABLE_READ_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
SAFE_RETRY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
DEFAULT_SAFE_HTTP_RETRY_MAX_ATTEMPTS = 3
DEFAULT_SAFE_HTTP_RETRY_BACKOFF_SECONDS = 0.25


def _send_safe_request(
    method: str,
    url: str,
    *,
    client: httpx.Client | None,
    **kwargs: Any,
) -> httpx.Response:
    if client is None:
        return httpx.request(method, url, **kwargs)
    if method == "GET":
        return client.get(url, **kwargs)
    if method == "HEAD":
        return client.head(url, **kwargs)
    if method == "OPTIONS":
        return client.options(url, **kwargs)
    raise ValueError(f"Refusing to send unsupported HTTP method {method!r}.")


def _raise_for_status(response: httpx.Response, *, method: str, url: str) -> None:
    raise_for_status = getattr(response, "raise_for_status", None)
    if callable(raise_for_status):
        try:
            raise_for_status()
            return
        except RuntimeError:
            # httpx.Response test doubles may not carry the originating request.
            pass
    raise httpx.HTTPStatusError(
        f"HTTP status {response.status_code} while requesting {url}",
        request=httpx.Request(method, url),
        response=response,
    )


def _close_response(response: httpx.Response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def request_with_retries(
    method: str,
    url: str,
    *,
    client: httpx.Client | None = None,
    max_attempts: int = DEFAULT_SAFE_HTTP_RETRY_MAX_ATTEMPTS,
    backoff_seconds: float = DEFAULT_SAFE_HTTP_RETRY_BACKOFF_SECONDS,
    retry_status_codes: Container[int] = RETRYABLE_READ_STATUS_CODES,
    raise_for_status: bool = True,
    **kwargs: Any,
) -> httpx.Response:
    """Run an idempotent HTTP request with bounded transient retries."""
    method_upper = method.upper()
    if method_upper not in SAFE_RETRY_METHODS:
        raise ValueError(f"Refusing to retry unsafe HTTP method {method_upper!r}.")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    last_exc: httpx.HTTPError | None = None
    for attempt in range(max_attempts):
        try:
            response = _send_safe_request(method_upper, url, client=client, **kwargs)
            if response.status_code not in retry_status_codes:
                if raise_for_status and response.status_code >= 400:
                    _raise_for_status(response, method=method_upper, url=url)
                return response
            if attempt == max_attempts - 1:
                if raise_for_status:
                    _raise_for_status(response, method=method_upper, url=url)
                return response
            _close_response(response)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in retry_status_codes or attempt == max_attempts - 1:
                raise
            last_exc = exc
        except httpx.TransportError as exc:
            if attempt == max_attempts - 1:
                raise
            last_exc = exc
        time.sleep(backoff_seconds * (2**attempt))

    if last_exc is not None:  # pragma: no cover - loop exits by return/raise.
        raise last_exc
    raise RuntimeError("request retry loop exited unexpectedly.")  # pragma: no cover
