"""Microsoft redirect URIs must be addresses Microsoft can actually call back.

The Outlook and Microsoft 365 tenant settings stored the redirect URI as free
text, the same defect fixed for Google Workspace in PR #473. Outlook drives a
real OAuth flow from one served callback, so its path is pinned. Microsoft 365
is registration and readiness only, with no callback route yet, so only the
rules every redirect must meet apply there; no path is invented.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    TenantMicrosoft365Configuration,
    TenantOutlookConfiguration,
)
from caseops_api.db.session import get_session_factory
from caseops_api.main import create_application
from caseops_api.schemas.calendar import OUTLOOK_OAUTH_CALLBACK_PATH
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company

HOST = "https://api.tenant.example"
OUTLOOK_URI = f"{HOST}{OUTLOOK_OAUTH_CALLBACK_PATH}"
M365_PATH = "/auth/microsoft/callback"

# Rules every redirect must meet regardless of which callback path it names.
STRUCTURAL_CASES = [
    ("plain http on a public host", "http://api.tenant.example{path}"),
    ("no origin", "{path}"),
    ("query string", "https://api.tenant.example{path}?next=/app"),
    ("fragment", "https://api.tenant.example{path}#done"),
    ("port that is not a number", "https://api.tenant.example:notaport{path}"),
    ("port 0", "https://api.tenant.example:0{path}"),
    ("credentials in the address", "https://user:pass@api.tenant.example{path}"),
]


def _outlook_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "client_id": "client-id-value",
        "client_secret": "fixture-credential-value",
        "tenant_id": "organizations",
        "redirect_uri": OUTLOOK_URI,
        "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
        "oauth_consent_model_approved": True,
        "scopes_approved": True,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def _microsoft365_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "client_id": "graph-client-id",
        "client_secret": "graph-client-secret",
        "tenant_id": "graph-tenant-id",
        "redirect_uri": f"https://api.caseops.test{M365_PATH}",
        "scopes": ["User.Read", "Mail.Read", "Calendars.ReadWrite", "Files.Read.All"],
        "admin_consent_approved": True,
        "scopes_approved": True,
        "mail_enabled": True,
        "calendar_enabled": True,
        "drive_enabled": True,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def _company(client: TestClient, name: str) -> str:
    bootstrap = _bootstrap_company(
        client,
        slug=f"ms-redirect-{name}",
        email=f"owner@ms-redirect-{name}.example",
    )
    return str(bootstrap["access_token"])


def _item(body: dict[str, object], name: str) -> dict[str, object]:
    return next(i for i in body["required_config"] if i["name"] == name)  # type: ignore[union-attr]


def test_pinned_outlook_path_is_the_callback_the_api_serves() -> None:
    """The validator cannot drift from the mounted route without failing here."""

    mounted = {getattr(route, "path", None) for route in create_application().routes}
    assert OUTLOOK_OAUTH_CALLBACK_PATH in mounted


OUTLOOK_REJECTIONS = [
    (reason, shape.format(path=OUTLOOK_OAUTH_CALLBACK_PATH))
    for reason, shape in STRUCTURAL_CASES
] + [
    ("trailing slash", f"{OUTLOOK_URI}/"),
    ("typo in the path", f"{HOST}/api/calendar/connections/outlook/calback"),
    (
        "the Google calendar callback pasted in",
        f"{HOST}/api/calendar/connections/google-calendar/callback",
    ),
    ("upper-cased path", f"{HOST}{OUTLOOK_OAUTH_CALLBACK_PATH.upper()}"),
    (
        "line break inside the address",
        "https://api.tenant.example" + chr(10) + OUTLOOK_OAUTH_CALLBACK_PATH,
    ),
]


@pytest.mark.parametrize(("reason", "value"), OUTLOOK_REJECTIONS)
def test_outlook_rejects_a_redirect_uri_microsoft_will_refuse(
    client: TestClient,
    reason: str,
    value: str,
) -> None:
    token = _company(client, f"outlook-{abs(hash(reason)) % 100000}")
    response = client.patch(
        "/api/admin/outlook-configuration",
        headers=_auth(token),
        json=_outlook_payload(redirect_uri=value),
    )
    assert response.status_code == 422, f"{reason} was accepted: {response.text}"
    assert "redirect_uri" in response.text
    # The message names the exact address Microsoft expects.
    assert OUTLOOK_OAUTH_CALLBACK_PATH in response.text
    assert "fixture-credential-value" not in response.text


def test_outlook_accepts_the_exact_callback_and_blank_leaves_it_alone(
    client: TestClient,
) -> None:
    token = _company(client, "outlook-valid")
    saved = client.patch(
        "/api/admin/outlook-configuration",
        headers=_auth(token),
        json=_outlook_payload(),
    )
    assert saved.status_code == 200, saved.text

    # Blank input means "leave this field alone": assert the stored row, because
    # a 200 alone would not show whether it was kept or cleared.
    blank = client.patch(
        "/api/admin/outlook-configuration",
        headers=_auth(token),
        json=_outlook_payload(redirect_uri="   "),
    )
    assert blank.status_code == 200, blank.text
    with get_session_factory()() as session:
        row = session.scalar(select(TenantOutlookConfiguration))
        assert row is not None
        assert row.redirect_uri == OUTLOOK_URI


def test_outlook_value_stored_before_this_rule_fails_closed(client: TestClient) -> None:
    token = _company(client, "outlook-legacy")
    assert (
        client.patch(
            "/api/admin/outlook-configuration",
            headers=_auth(token),
            json=_outlook_payload(),
        ).status_code
        == 200
    )
    # Write the shape an admin could save before this rule existed.
    with get_session_factory()() as session:
        row = session.scalar(select(TenantOutlookConfiguration))
        assert row is not None
        row.redirect_uri = f"{OUTLOOK_URI}/"
        session.commit()

    status = client.get("/api/admin/outlook-configuration", headers=_auth(token))
    assert status.status_code == 200, status.text
    body = status.json()
    assert _item(body, "OUTLOOK_REDIRECT_URI")["configured"] is False
    assert "OUTLOOK_REDIRECT_URI" in body["missing_config_names"]
    assert body["configured"] is False

    # And no user can be sent to Microsoft with an address it will refuse.
    start = client.post("/api/calendar/connections/outlook/start", headers=_auth(token))
    assert start.status_code == 200, start.text
    assert start.json()["provider_available"] is False
    assert not start.json().get("auth_url")
    assert "login.microsoftonline.com" not in start.text


M365_REJECTIONS = [
    (reason, shape.format(path=M365_PATH)) for reason, shape in STRUCTURAL_CASES
] + [
    (
        "line break inside the address",
        "https://api.tenant.example" + chr(10) + M365_PATH,
    ),
]


@pytest.mark.parametrize(("reason", "value"), M365_REJECTIONS)
def test_microsoft365_rejects_a_structurally_unusable_redirect_uri(
    client: TestClient,
    reason: str,
    value: str,
) -> None:
    token = _company(client, f"m365-{abs(hash(reason)) % 100000}")
    response = client.patch(
        "/api/admin/microsoft365-configuration",
        headers=_auth(token),
        json=_microsoft365_payload(redirect_uri=value),
    )
    assert response.status_code == 422, f"{reason} was accepted: {response.text}"
    assert "redirect_uri" in response.text
    assert "graph-client-secret" not in response.text


def test_microsoft365_does_not_invent_a_callback_path(client: TestClient) -> None:
    """No Microsoft 365 callback route exists, so any well-formed https path saves."""

    token = _company(client, "m365-valid")
    saved = client.patch(
        "/api/admin/microsoft365-configuration",
        headers=_auth(token),
        json=_microsoft365_payload(),
    )
    assert saved.status_code == 200, saved.text
    assert _item(saved.json(), "MICROSOFT_365_REDIRECT_URI")["configured"] is True


def test_microsoft365_value_stored_before_this_rule_is_not_configured(
    client: TestClient,
) -> None:
    token = _company(client, "m365-legacy")
    assert (
        client.patch(
            "/api/admin/microsoft365-configuration",
            headers=_auth(token),
            json=_microsoft365_payload(),
        ).status_code
        == 200
    )
    with get_session_factory()() as session:
        row = session.scalar(select(TenantMicrosoft365Configuration))
        assert row is not None
        row.redirect_uri = f"http://api.tenant.example{M365_PATH}"
        session.commit()

    status = client.get("/api/admin/microsoft365-configuration", headers=_auth(token))
    assert status.status_code == 200, status.text
    body = status.json()
    assert _item(body, "MICROSOFT_365_REDIRECT_URI")["configured"] is False
    assert "MICROSOFT_365_REDIRECT_URI" in body["missing_config_names"]
    assert body["readiness"] == "blocked_pending_admin_configuration"
