"""Review probes of the real callback route/dependency boundary, with no I/O."""

import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from caseops_api.api import oauth_browser
from caseops_api.api.routes import calendar, drive, mailbox


def _consumed_code(endpoint):
    if endpoint.startswith("/api/mailbox/"):
        return "gmail_oauth_attempt_consumed"
    if endpoint.startswith("/api/drive/"):
        return "drive_oauth_attempt_consumed"
    return "calendar_oauth_callback_consumed"


@pytest.fixture(
    params=[
        (
            calendar,
            "/api/calendar",
            "/connections/google-calendar/callback",
            "complete_google_calendar_connection",
        ),
        (calendar, "/api/calendar", "/connections/outlook/callback", "complete_outlook_connection"),
        (drive, "/api/drive", "/google/callback", "complete_google_drive_connection"),
        (mailbox, "/api/mailbox", "/gmail/callback", "complete_gmail_connection"),
    ]
)
def callback_route(request, monkeypatch):
    module, prefix, path, service_name = request.param
    app = FastAPI()
    app.include_router(module.router, prefix=prefix)
    endpoint = prefix + path
    route = next(
        route for route in app.routes if isinstance(route, APIRoute) and route.path == endpoint
    )
    context_dependency = next(
        dep.call for dep in route.dependant.dependencies if dep.name == "context"
    )
    session_dependency = next(
        dep.call for dep in route.dependant.dependencies if dep.name == "session"
    )
    app.dependency_overrides[context_dependency] = lambda: object()
    app.dependency_overrides[session_dependency] = lambda: object()
    monkeypatch.setattr(
        oauth_browser,
        "get_settings",
        lambda: SimpleNamespace(public_app_url="https://caseops.example"),
    )
    calls = []

    def service(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            calls.append("off-event-loop")
        else:
            pytest.fail("Blocking OAuth exchange is on the event loop")
        raise HTTPException(
            409, detail={"code": _consumed_code(endpoint), "message": "secret"}
        )

    monkeypatch.setattr(module, service_name, service)
    with TestClient(app, follow_redirects=False) as client:
        yield client, app, endpoint, context_dependency, calls


def test_callback_json_error_and_provider_execution_remain_compatible(callback_route):
    client, _, endpoint, _, calls = callback_route
    response = client.get(
        endpoint,
        params={"code": "one-use-code", "state": "signed-state"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == _consumed_code(endpoint)
    assert calls == ["off-event-loop"]


def test_browser_consumed_callback_returns_explicit_rejection_notice(callback_route):
    client, _, endpoint, _, calls = callback_route
    response = client.get(
        endpoint,
        params={"code": "one-use-code", "state": "signed-state"},
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 303, response.text
    target = urlsplit(response.headers["location"])
    assert target.netloc == "caseops.example"
    assert parse_qs(target.query)["oauth_result"] == ["consumed"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "one-use-code" not in response.headers["location"]
    assert "signed-state" not in response.headers["location"]
    assert calls == ["off-event-loop"]


def test_callback_does_not_redirect_when_html_is_explicitly_unacceptable(callback_route):
    client, _, endpoint, _, calls = callback_route
    response = client.get(
        endpoint,
        params={"code": "one-use-code", "state": "signed-state"},
        headers={"Accept": "application/json,text/html;q=0"},
    )
    assert response.status_code == 409, response.text
    assert "location" not in response.headers
    assert calls == ["off-event-loop"]


def test_browser_consent_denial_returns_to_app_without_exchange(callback_route):
    client, _, endpoint, _, calls = callback_route
    response = client.get(
        endpoint,
        params={
            "error": "access_denied",
            "state": "signed-state",
            "error_description": "untrusted private description",
        },
        headers={"Accept": "text/html"},
    )
    assert calls == []
    assert response.status_code == 303, response.text
    target = urlsplit(response.headers["location"])
    assert target.netloc == "caseops.example"
    assert target.path in {"/app/calendar", "/app/drive"}
    assert parse_qs(target.query)["oauth_result"] == ["consent_required"]
    assert "signed-state" not in response.headers["location"]
    assert "description" not in response.headers["location"]


def test_browser_pre_callback_authority_loss_rejects_safely_and_returns_to_app(callback_route):
    client, app, endpoint, context_dependency, calls = callback_route

    def denied_context():
        raise HTTPException(403, detail="private permission detail")

    app.dependency_overrides[context_dependency] = denied_context
    response = client.get(
        endpoint,
        params={"code": "one-use-code", "state": "signed-state"},
        headers={"Accept": "text/html"},
    )
    assert calls == []
    assert response.status_code == 303, response.text
    target = urlsplit(response.headers["location"])
    assert target.netloc == "caseops.example"
    assert parse_qs(target.query)["oauth_result"] == ["access_changed"]


def test_json_pre_callback_authority_loss_preserves_original_403(callback_route):
    client, app, endpoint, context_dependency, calls = callback_route

    def denied_context():
        raise HTTPException(403, detail="permission denied")

    app.dependency_overrides[context_dependency] = denied_context
    response = client.get(
        endpoint,
        params={"code": "one-use-code", "state": "signed-state"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "permission denied"}
    assert "location" not in response.headers
    assert calls == []


def test_json_consent_denial_preserves_required_code_validation(callback_route):
    client, _, endpoint, _, calls = callback_route
    response = client.get(
        endpoint,
        params={"error": "access_denied", "state": "signed-state"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert any(item["loc"] == ["query", "code"] for item in response.json()["detail"])
    assert "location" not in response.headers
    assert calls == []


def test_unmarked_connector_start_does_not_redirect_browser_denials(callback_route):
    client, app, endpoint, context_dependency, calls = callback_route
    start_path = endpoint.removesuffix("/callback") + "/start"
    route = next(
        route for route in app.routes if isinstance(route, APIRoute) and route.path == start_path
    )
    assert isinstance(route, oauth_browser.OAuthCallbackRoute)
    assert getattr(route.endpoint, "oauth_provider", None) is None

    def denied_context():
        raise HTTPException(403, detail="permission denied")

    app.dependency_overrides[context_dependency] = denied_context
    response = client.post(
        start_path,
        params={"error": "access_denied"},
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "permission denied"}
    assert "location" not in response.headers
    assert calls == []
