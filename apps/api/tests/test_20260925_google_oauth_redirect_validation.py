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

    # A blank field still clears rather than tripping the new rule.
    cleared = client.patch(
        "/api/admin/google-workspace-configuration",
        headers=_auth(token),
        json=_valid_payload(gmail_redirect_uri="   "),
    )
    assert cleared.status_code == 200, cleared.text


def test_localhost_development_origins_remain_usable() -> None:
    model = GoogleWorkspaceTenantConfigurationUpdateRequest(
        calendar_redirect_uri=(
            f"http://localhost:8000{GOOGLE_OAUTH_CALLBACK_PATHS['calendar_redirect_uri']}"
        ),
    )
    assert model.calendar_redirect_uri is not None
