"""A tenant OAuth redirect URI must be the exact callback Google will call back.

Before this, the three redirect URIs were free text: a trailing slash, an http
scheme, or the Drive address pasted into the Gmail field saved with HTTP 200 and
readiness then reported ``configured: true``. The first user to grant consent hit
Google's ``redirect_uri_mismatch`` instead, and the stored value could not be read
back from any endpoint to diagnose it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import TenantGoogleWorkspaceConfiguration
from caseops_api.db.session import get_session_factory
from caseops_api.main import create_application
from caseops_api.schemas.google_workspace import (
    GOOGLE_OAUTH_CALLBACK_PATHS,
    GoogleWorkspaceTenantConfigurationUpdateRequest,
)
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company

HOST = "https://api.tenant.example"


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "client_id": "tenant-google-client",
        "client_secret": "tenant-google-secret",
        "calendar_redirect_uri": f"{HOST}{GOOGLE_OAUTH_CALLBACK_PATHS['calendar_redirect_uri']}",
        "gmail_redirect_uri": f"{HOST}{GOOGLE_OAUTH_CALLBACK_PATHS['gmail_redirect_uri']}",
        "drive_redirect_uri": f"{HOST}{GOOGLE_OAUTH_CALLBACK_PATHS['drive_redirect_uri']}",
        "scopes": [
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/gmail.readonly",
        ],
        "oauth_consent_model_approved": True,
        "scopes_approved": True,
        "calendar_enabled": True,
        "gmail_enabled": True,
        "drive_enabled": True,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def test_accepted_paths_are_the_callbacks_the_api_actually_serves() -> None:
    """The validator cannot drift from the mounted routes without failing here."""

    mounted = {getattr(route, "path", None) for route in create_application().routes}
    for field, path in GOOGLE_OAUTH_CALLBACK_PATHS.items():
        assert path in mounted, f"{field} expects {path}, which the API does not serve"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "gmail_redirect_uri",
            f"{HOST}/api/mailbox/gmail/callback/",
            "trailing slash",
        ),
        (
            "calendar_redirect_uri",
            f"http://api.tenant.example{GOOGLE_OAUTH_CALLBACK_PATHS['calendar_redirect_uri']}",
            "plain http on a public host",
        ),
        (
            "drive_redirect_uri",
            f"{HOST}/api/drive/google/calback",
            "typo in the path",
        ),
        (
            "gmail_redirect_uri",
            f"{HOST}{GOOGLE_OAUTH_CALLBACK_PATHS['drive_redirect_uri']}",
            "another connector's callback pasted in",
        ),
        (
            "drive_redirect_uri",
            GOOGLE_OAUTH_CALLBACK_PATHS["drive_redirect_uri"],
            "path only, no origin",
        ),
        (
            "calendar_redirect_uri",
            f"{HOST}{GOOGLE_OAUTH_CALLBACK_PATHS['calendar_redirect_uri']}?next=/app",
            "query string",
        ),
        (
            "gmail_redirect_uri",
            f"{HOST}{GOOGLE_OAUTH_CALLBACK_PATHS['gmail_redirect_uri']}#done",
            "fragment",
        ),
        (
            "gmail_redirect_uri",
            f"{HOST.upper()}{GOOGLE_OAUTH_CALLBACK_PATHS['gmail_redirect_uri'].upper()}",
            "upper-cased path",
        ),
        (
            "gmail_redirect_uri",
            f"https://api.tenant.example:notaport{GOOGLE_OAUTH_CALLBACK_PATHS['gmail_redirect_uri']}",
            "port that is not a number",
        ),
        (
            "gmail_redirect_uri",
            "https://api.tenant.example"
            + chr(10)
            + GOOGLE_OAUTH_CALLBACK_PATHS["gmail_redirect_uri"],
            "line break inside the address",
        ),
        (
            "gmail_redirect_uri",
            f"https://api.tenant.example:0{GOOGLE_OAUTH_CALLBACK_PATHS['gmail_redirect_uri']}",
            "port 0, which parses but cannot be called back",
        ),
    ],
)
def test_admin_cannot_save_a_redirect_uri_google_will_reject(
    client: TestClient,
    field: str,
    value: str,
    reason: str,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug=f"google-redirect-{abs(hash((field, reason))) % 100000}",
        email=f"owner-{abs(hash((field, reason))) % 100000}@google-redirect.example",
    )
    token = str(bootstrap["access_token"])

    response = client.patch(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
        json=_valid_payload(**{field: value}),
    )

    assert response.status_code == 422, f"{reason} was accepted: {response.text}"
    body = response.text
    assert field in body
    # The message names the exact address Google expects, not a schema error.
    assert GOOGLE_OAUTH_CALLBACK_PATHS[field] in body
    assert "tenant-google-secret" not in body


def test_admin_can_still_save_the_exact_callbacks_and_clear_them(
    client: TestClient,
) -> None:
    bootstrap = _bootstrap_company(
        client,
        slug="google-redirect-valid",
        email="owner@google-redirect-valid.example",
    )
    token = str(bootstrap["access_token"])

    saved = client.patch(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
        json=_valid_payload(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["configured"] is True

    # Blank input is "leave this field alone", not "clear it": the update only
    # assigns a redirect field when the payload carries one. Assert the stored
    # value, because a 200 alone would not show which of the two happened.
    blank = client.patch(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
        json=_valid_payload(gmail_redirect_uri="   "),
    )
    assert blank.status_code == 200, blank.text
    with get_session_factory()() as session:
        row = session.scalar(select(TenantGoogleWorkspaceConfiguration))
        assert row is not None
        assert row.gmail_redirect_uri == (
            f"{HOST}{GOOGLE_OAUTH_CALLBACK_PATHS['gmail_redirect_uri']}"
        )
    assert all(
        item["configured"]
        for item in blank.json()["required_config"]
        if item["name"].endswith("REDIRECT_URI")
    )


def test_a_uri_stored_before_this_rule_is_not_reported_as_configured(
    client: TestClient,
) -> None:
    """The live tenant row predates validation; readiness must not vouch for it."""

    bootstrap = _bootstrap_company(
        client,
        slug="google-redirect-legacy",
        email="owner@google-redirect-legacy.example",
    )
    token = str(bootstrap["access_token"])
    assert (
        client.patch(
            "/api/admin/google-workspace-configuration",
            headers=_auth(token),
            json=_valid_payload(),
        ).status_code
        == 200
    )

    # Write the shape an admin could save before this rule existed.
    with get_session_factory()() as session:
        row = session.scalar(select(TenantGoogleWorkspaceConfiguration))
        assert row is not None
        row.gmail_redirect_uri = f"{HOST}/api/mailbox/gmail/callback/"
        session.commit()

    status = client.get(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
    )
    assert status.status_code == 200, status.text
    body = status.json()
    gmail_item = next(
        item for item in body["required_config"] if item["name"] == "GMAIL_REDIRECT_URI"
    )
    assert gmail_item["configured"] is False
    assert "GMAIL_REDIRECT_URI" in body["missing_config_names"]
    # The connectors whose addresses are still exact stay usable.
    assert body["configured"] is False
    calendar_item = next(
        item
        for item in body["required_config"]
        if item["name"] == "GOOGLE_CALENDAR_REDIRECT_URI"
    )
    assert calendar_item["configured"] is True

    # And no user can be sent to Google with the address Google will refuse:
    # the start route reports the connector unavailable and hands back no link.
    start = client.post("/api/mailbox/gmail/start", headers=_auth(token))
    assert start.status_code == 200, start.text
    started = start.json()
    assert started["provider_available"] is False
    assert started["auth_url"] is None
    assert started["unavailable_reason"]
    assert "accounts.google.com" not in start.text


def test_localhost_development_origins_remain_usable() -> None:
    model = GoogleWorkspaceTenantConfigurationUpdateRequest(
        calendar_redirect_uri=(
            f"http://localhost:8000{GOOGLE_OAUTH_CALLBACK_PATHS['calendar_redirect_uri']}"
        ),
    )
    assert model.calendar_redirect_uri is not None
