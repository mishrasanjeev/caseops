"""Nov 27 workbook row 8: Microsoft 365 setup names the exact values to enter.

The admin page could not be completed because nothing said which Redirect URI
or Directory (tenant) ID to enter, and the Microsoft 365 redirect accepted any
path although CaseOps serves exactly one Microsoft callback. These tests pin:

* the server computes the Redirect URI from the API origin the admin reached
  and the one Microsoft callback path, and both Microsoft setup pages show the
  same value;
* that value is the redirect_uri the Outlook OAuth flow actually sends;
* tenant and client ids are validated the way Entra issues them;
* Test explains each blocked item, including a redirect saved for another host.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

import caseops_api
from caseops_api.schemas.calendar import OUTLOOK_OAUTH_CALLBACK_PATH
from caseops_api.schemas.oauth_redirect import public_origin
from caseops_api.services.calendar_sync import OUTLOOK_SCOPES
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company

TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"
CLIENT = "0b6f2a4e-1c3d-4e5f-8a9b-0c1d2e3f4a5b"
EXPECTED = f"https://testserver{OUTLOOK_OAUTH_CALLBACK_PATH}"


def _token(client: TestClient, name: str) -> str:
    return str(
        _bootstrap_company(
            client, slug=f"m365-setup-{name}", email=f"owner@m365-setup-{name}.example"
        )["access_token"]
    )


def _m365(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "client_id": CLIENT,
        "client_secret": "graph-client-secret",
        "tenant_id": TENANT,
        "redirect_uri": EXPECTED,
        "admin_consent_approved": True,
        "scopes_approved": True,
    }
    payload.update(overrides)
    return payload


def test_public_origin_is_https_except_on_loopback() -> None:
    assert public_origin("http", "api.caseops.ai", None) == "https://api.caseops.ai"
    # TLS ends in front of the API: the internal http scheme must not leak out.
    assert public_origin("http", "api.caseops.ai", 80) == "https://api.caseops.ai"
    assert public_origin("https", "api.caseops.ai", 8443) == "https://api.caseops.ai:8443"
    assert public_origin("http", "127.0.0.1", 8117) == "http://127.0.0.1:8117"
    assert public_origin("http", "localhost", 8000) == "http://localhost:8000"


def test_both_microsoft_pages_show_one_redirect_uri_built_from_the_api_origin(
    client: TestClient,
) -> None:
    token = _token(client, "shown")
    m365 = client.get("/api/admin/microsoft365-configuration", headers=_auth(token))
    outlook = client.get("/api/admin/outlook-configuration", headers=_auth(token))
    assert m365.status_code == 200, m365.text
    assert outlook.status_code == 200, outlook.text
    body = m365.json()
    assert body["expected_redirect_uri"] == EXPECTED
    assert outlook.json()["expected_redirect_uri"] == EXPECTED
    assert body["callback_path"] == OUTLOOK_OAUTH_CALLBACK_PATH
    assert body["registration_model"] == "customer_entra_app_registration"
    scopes = [permission["scope"] for permission in body["required_permissions"]]
    assert {"offline_access", "User.Read", "Calendars.ReadWrite"} <= set(scopes)
    assert all(permission["purpose"] for permission in body["required_permissions"])

    # The production host the admin's browser reaches is what is shown.
    prod = client.get(
        "/api/admin/microsoft365-configuration",
        headers={**_auth(token), "host": "api.caseops.ai"},
    )
    assert prod.json()["expected_redirect_uri"] == (
        f"https://api.caseops.ai{OUTLOOK_OAUTH_CALLBACK_PATH}"
    )


def test_the_shown_redirect_uri_is_the_one_the_outlook_flow_sends(client: TestClient) -> None:
    token = _token(client, "flow")
    shown = client.get("/api/admin/outlook-configuration", headers=_auth(token)).json()[
        "expected_redirect_uri"
    ]
    saved = client.patch(
        "/api/admin/outlook-configuration",
        headers=_auth(token),
        json={
            "client_id": CLIENT,
            "client_secret": "outlook-fixture-secret",
            "tenant_id": TENANT,
            "redirect_uri": shown,
            "scopes": ["offline_access", "User.Read", "Calendars.ReadWrite"],
            "oauth_consent_model_approved": True,
            "scopes_approved": True,
            "enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text
    start = client.post("/api/calendar/connections/outlook/start", headers=_auth(token))
    assert start.status_code == 200, start.text
    auth_url = start.json().get("auth_url") or start.json().get("authorization_url")
    assert auth_url, start.text
    query = parse_qs(urlsplit(auth_url).query)
    assert query["redirect_uri"] == [shown]
    assert TENANT in urlsplit(auth_url).path


@pytest.mark.parametrize(
    ("tenant_id", "fragment"),
    [
        ("common", "sign-in mode"),
        ("organizations", "sign-in mode"),
        ("graph-tenant-id", "GUID"),
        ("72f988bf-86f1-41af-91ab", "GUID"),
        ("https://login.microsoftonline.com/x", "GUID"),
    ],
)
def test_tenant_id_must_be_the_firms_directory(
    client: TestClient, tenant_id: str, fragment: str
) -> None:
    token = _token(client, f"tenant-{abs(hash(tenant_id)) % 100000}")
    response = client.patch(
        "/api/admin/microsoft365-configuration",
        headers=_auth(token),
        json=_m365(tenant_id=tenant_id),
    )
    assert response.status_code == 422, response.text
    assert "tenant_id" in response.text
    assert fragment in response.text
    assert "graph-client-secret" not in response.text


@pytest.mark.parametrize(
    "tenant_id", [TENANT, TENANT.upper(), "nova-legal.onmicrosoft.com", "novalegal.in"]
)
def test_guid_or_verified_domain_tenant_ids_save(client: TestClient, tenant_id: str) -> None:
    token = _token(client, f"tenant-ok-{abs(hash(tenant_id)) % 100000}")
    response = client.patch(
        "/api/admin/microsoft365-configuration",
        headers=_auth(token),
        json=_m365(tenant_id=tenant_id),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tenant_id"] == tenant_id
    assert body["client_id"] == CLIENT
    assert body["secret_saved"] is True
    assert "graph-client-secret" not in response.text


def test_client_id_must_be_an_application_guid(client: TestClient) -> None:
    token = _token(client, "client")
    response = client.patch(
        "/api/admin/microsoft365-configuration",
        headers=_auth(token),
        json=_m365(client_id="graph-client-id"),
    )
    assert response.status_code == 422, response.text
    assert "Application (client) ID" in response.text


def test_test_button_explains_a_redirect_saved_for_another_host(client: TestClient) -> None:
    token = _token(client, "mismatch")
    other = f"https://api.other.example{OUTLOOK_OAUTH_CALLBACK_PATH}"
    saved = client.patch(
        "/api/admin/microsoft365-configuration",
        headers=_auth(token),
        json=_m365(redirect_uri=other),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["redirect_uri_matches_expected"] is False

    tested = client.post("/api/admin/microsoft365-configuration/test", headers=_auth(token))
    assert tested.status_code == 200, tested.text
    body = tested.json()
    assert body["status"] == "blocked"
    check = next(c for c in body["checks"] if c["key"] == "redirect_uri_matches_deployment")
    assert check["status"] == "blocked"
    assert EXPECTED in check["detail"]
    labels = {c["key"]: c["label"] for c in body["checks"]}
    assert labels["MICROSOFT_365_TENANT_ID"] == "Directory (tenant) ID saved"

    fixed = client.patch(
        "/api/admin/microsoft365-configuration", headers=_auth(token), json=_m365()
    )
    assert fixed.json()["redirect_uri_matches_expected"] is True
    passed = client.post("/api/admin/microsoft365-configuration/test", headers=_auth(token))
    assert passed.json()["status"] == "passed", passed.text
    assert all(c["status"] == "passed" for c in passed.json()["checks"])


def test_microsoft365_configuration_is_tenant_isolated(client: TestClient) -> None:
    first = _token(client, "iso-a")
    assert (
        client.patch(
            "/api/admin/microsoft365-configuration", headers=_auth(first), json=_m365()
        ).status_code
        == 200
    )
    second = _token(client, "iso-b")
    other = client.get("/api/admin/microsoft365-configuration", headers=_auth(second)).json()
    assert other["client_id"] is None
    assert other["tenant_id"] is None
    assert other["secret_saved"] is False


def test_no_sign_in_flow_reads_the_microsoft365_configuration() -> None:
    """Review finding on row 8: the setup page now says that no CaseOps sign-in
    reads these values and that only connector health uses them. This pins that
    claim to the code: a new reader fails here so the copy is revisited."""

    src = Path(caseops_api.__file__).parent
    readers = sorted(
        path.relative_to(src).as_posix()
        for path in src.rglob("*.py")
        if "TenantMicrosoft365Configuration" in path.read_text(encoding="utf-8")
    )
    assert readers == [
        "db/models.py",
        "services/connector_health.py",
        "services/microsoft365.py",
    ]


def test_setup_copy_says_what_save_and_test_actually_do(client: TestClient) -> None:
    token = _token(client, "honest")
    body = client.get("/api/admin/microsoft365-configuration", headers=_auth(token)).json()
    for permission in body["required_permissions"]:
        requested_today = permission["scope"] in OUTLOOK_SCOPES
        not_requested_note = "No CaseOps sign-in requests this permission yet." in (
            permission["purpose"]
        )
        assert not_requested_note is not requested_today, permission

    openapi = client.app.openapi()  # type: ignore[attr-defined]
    schemas = openapi["components"]["schemas"]
    configuration = schemas["Microsoft365TenantConfigurationResponse"]["description"]
    assert "connects no account" in configuration
    assert "connected through the Outlook configuration" in " ".join(configuration.split())
    tested = schemas["Microsoft365ReadinessTestResponse"]["description"]
    assert "no Microsoft call is made" in tested
    assert "no account is connected" in " ".join(tested.split())
    operations = openapi["paths"]["/api/admin/microsoft365-configuration"]
    assert "connects no account" in operations["patch"]["summary"]
    probe = openapi["paths"]["/api/admin/microsoft365-configuration/test"]["post"]
    assert "without calling Microsoft" in probe["summary"]
    for text in (configuration, tested, operations["patch"]["summary"]):
        assert "completed by the Outlook callback" not in text
