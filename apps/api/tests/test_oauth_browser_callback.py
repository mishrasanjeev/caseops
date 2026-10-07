import inspect
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException, Request

from caseops_api.api import oauth_browser
from caseops_api.api.routes import calendar, drive, mailbox


def _request(accept: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/callback",
            "query_string": b"code=secret&state=secret&return_url=https://untrusted.example",
            "headers": [(b"accept", accept.encode()), (b"host", b"untrusted.example")],
        }
    )


@pytest.fixture(autouse=True)
def configured_app_url(monkeypatch):
    monkeypatch.setattr(
        oauth_browser,
        "get_settings",
        lambda: SimpleNamespace(public_app_url="https://caseops.example/"),
    )


@pytest.mark.parametrize(
    "provider,path",
    [
        ("google_calendar", "/app/calendar"),
        ("outlook", "/app/calendar"),
        ("gmail", "/app/calendar"),
        ("google_drive", "/app/drive"),
    ],
)
def test_browser_callback_uses_only_server_owned_destination(provider, path):
    calls = []
    response = oauth_browser.complete_browser_oauth(
        _request("text/html,application/xhtml+xml"),
        provider=provider,
        complete=lambda: calls.append("complete"),
    )
    assert calls == ["complete"]
    assert response.status_code == 303
    assert response.headers["location"] == "https://caseops.example" + path
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "status,code,outcome",
    [
        (409, "calendar_oauth_exchange_in_flight", "in_flight"),
        (409, "calendar_oauth_reconnect_required", "consent_required"),
        (409, "calendar_oauth_callback_consumed", "consumed"),
        (409, "gmail_oauth_attempt_consumed", "consumed"),
        (409, "drive_oauth_attempt_consumed", "consumed"),
        (409, "gmail_oauth_exchange_in_flight", "in_flight"),
        (409, "calendar_oauth_changed", "changed"),
        (403, "forbidden", "access_changed"),
        (503, "unavailable", "unavailable"),
        (502, "provider_failed", "retry"),
        (400, "invalid_state", "retry"),
    ],
)
def test_browser_failure_never_reflects_provider_or_callback_secrets(status, code, outcome):
    def fail():
        raise HTTPException(status, detail={"code": code, "message": "secret code=credential"})

    response = oauth_browser.complete_browser_oauth(
        _request("text/html"), provider="google_calendar", complete=fail
    )
    url = urlsplit(response.headers["location"])
    assert url.netloc == "caseops.example"
    assert parse_qs(url.query) == {"oauth_provider": ["google_calendar"], "oauth_result": [outcome]}


@pytest.mark.parametrize("accept", ["application/json", "*/*", ""])
def test_api_callback_keeps_original_contract_and_error(accept):
    result = {"connected": True}
    assert (
        oauth_browser.complete_browser_oauth(
            _request(accept), provider="gmail", complete=lambda: result
        )
        is result
    )
    error = HTTPException(409, detail={"code": "gmail_oauth_exchange_in_flight"})

    def fail():
        raise error

    with pytest.raises(HTTPException) as raised:
        oauth_browser.complete_browser_oauth(_request(accept), provider="gmail", complete=fail)
    assert raised.value is error


def test_unexpected_programming_failure_is_not_silently_converted_to_success():
    def fail():
        raise RuntimeError("unexpected defect")

    with pytest.raises(RuntimeError):
        oauth_browser.complete_browser_oauth(
            _request("text/html"), provider="outlook", complete=fail
        )


@pytest.mark.parametrize(
    "endpoint",
    [calendar.revoke_calendar_connection, drive.revoke_google_drive, mailbox.revoke_gmail],
)
def test_disconnect_authority_lock_wait_does_not_run_on_the_event_loop(endpoint):
    assert not inspect.iscoroutinefunction(endpoint)
