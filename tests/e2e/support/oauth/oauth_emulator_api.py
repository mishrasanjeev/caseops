"""Test-only Uvicorn entrypoint; never copied into the production API image."""

from __future__ import annotations

import atexit
from html import escape
from urllib.parse import urlsplit, urlunsplit

from calendar_oauth_emulator import (
    CLIENT_ID,
    PREFIX,
    CalendarOAuthEmulator,
    loopback_origin,
    redirected_google_url,
    require_test_environment,
)

require_test_environment()

import httpx  # noqa: E402
from fastapi import HTTPException, Request  # noqa: E402
from fastapi.responses import HTMLResponse, RedirectResponse  # noqa: E402

from caseops_api.main import app  # noqa: E402
from caseops_api.services.calendar_sync import GoogleCalendarProvider  # noqa: E402

emulator = CalendarOAuthEmulator()
transport_origin = emulator.start()
atexit.register(emulator.stop)
original_send = httpx.Client.send
original_authorization_url = GoogleCalendarProvider.authorization_url


def offline_send(
    self: httpx.Client, request: httpx.Request, **kwargs: object
) -> httpx.Response:
    target = redirected_google_url(str(request.url), transport_origin)
    if target:
        request.read()
        request = httpx.Request(
            request.method,
            target,
            headers=request.headers,
            content=request.content,
            extensions=request.extensions,
        )
    return original_send(self, request, **kwargs)


def offline_authorization_url(self: GoogleCalendarProvider, *, state: str) -> str:
    config = self._runtime_config()
    if config.client_id != CLIENT_ID:
        raise RuntimeError(
            "Only the offline tenant's OAuth client can use this harness."
        )
    parsed = urlsplit(original_authorization_url(self, state=state))
    origin = urlsplit(loopback_origin(str(config.redirect_uri)))
    return urlunsplit(
        (origin.scheme, origin.netloc, PREFIX + "/authorize", parsed.query, "")
    )


httpx.Client.send = offline_send
GoogleCalendarProvider.authorization_url = offline_authorization_url


@app.get(PREFIX + "/health", include_in_schema=False)
def offline_health() -> dict[str, str]:
    return {"mode": "calendar-20261008", "transport": "loopback-only"}


@app.get(PREFIX + "/authorize", response_class=HTMLResponse, include_in_schema=False)
def offline_authorize(request: Request) -> HTMLResponse:
    try:
        attempt = emulator.authorize(dict(request.query_params))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    buttons = "".join(
        f'<button type="submit" name="outcome" value="{value}">{label}</button>'
        for value, label in (
            ("success", "Allow calendar access"),
            ("decline", "Decline consent"),
            ("identity_failure", "Simulate identity rejection"),
            ("hold", "Hold token exchange"),
        )
    )
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width">'
        "<title>Offline Calendar consent</title></head><body><main>"
        "<h1>Offline Calendar consent</h1><p>calendar-emulator@example.test</p>"
        f"<ul>{''.join('<li>' + escape(scope) + '</li>' for scope in attempt.scopes)}</ul>"
        f'<form action="{PREFIX}/consent" method="get">'
        f'<input type="hidden" name="attempt" value="{attempt.identity}" data-testid="oauth-emulator-attempt">'
        f"{buttons}</form></main></body></html>",
        headers={"Cache-Control": "no-store"},
    )


@app.get(PREFIX + "/consent", include_in_schema=False)
def offline_consent(attempt: str, outcome: str) -> RedirectResponse:
    try:
        target = emulator.consent(attempt, outcome)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, "Invalid offline consent.") from exc
    return RedirectResponse(target, status_code=303)


@app.get(PREFIX + "/evidence/{attempt}", include_in_schema=False)
def offline_evidence(attempt: str) -> dict[str, object]:
    try:
        return emulator.evidence(attempt)
    except KeyError as exc:
        raise HTTPException(404, "Unknown offline attempt.") from exc


@app.post(PREFIX + "/release/{attempt}", include_in_schema=False)
def offline_release(attempt: str) -> dict[str, bool]:
    try:
        emulator.attempts[attempt].release.set()
    except KeyError as exc:
        raise HTTPException(404, "Unknown offline attempt.") from exc
    return {"released": True}
