"""The local-only Gmail fixture used by the B4-ADJ-23 browser journey.

It gives one fresh batch-4 tester tenant a connected Gmail mailbox whose
provider returns an escaped snippet, so the product's own import route writes
the ``gmail_provider_import`` Communication. These tests pin its guards: the
e2e-only entrypoint, the no-paid marker, a batch-4 owner, the caller's own
operational Matter, and that every other tenant keeps the real provider.
"""

import importlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.request_context import RequestContextMiddleware
from caseops_api.core.settings import get_settings
from caseops_api.db.models import Communication
from caseops_api.db.session import get_session_factory
from caseops_api.services import gmail_sync
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company, _create_matter

MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}
FIXTURES = "/_e2e/gmail-import/fixtures"


@pytest.fixture
def emulator_app(client, monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[3] / "tests/e2e/support/oauth")
    )
    cloud = ("K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB", "GOOGLE_CLOUD_PROJECT")
    for key in cloud:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_E2E_OAUTH_EMULATOR", "calendar-20261008")
    monkeypatch.setenv("CASEOPS_PUBLIC_APP_URL", "http://127.0.0.1:3100")
    get_settings.cache_clear()
    # The emulator replaces the module's provider factory; restore it afterwards.
    monkeypatch.setattr(gmail_sync, "_gmail_provider", gmail_sync._gmail_provider)
    module = importlib.import_module("gmail_import_emulator")
    from caseops_api.api.routes.mailbox import router

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router, prefix="/api/mailbox")
    module.install_gmail_import_emulator(app)
    try:
        with TestClient(app) as api:
            yield api, module
    finally:
        get_settings.cache_clear()


def test_requires_the_e2e_entrypoint(monkeypatch) -> None:
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[3] / "tests/e2e/support/oauth")
    )
    monkeypatch.setenv("CASEOPS_ENV", "production")
    module = importlib.import_module("gmail_import_emulator")
    with pytest.raises(RuntimeError, match="explicit e2e entrypoint"):
        module.install_gmail_import_emulator(FastAPI())


def test_fixture_tenant_imports_an_escaped_gmail_snippet_through_the_product_route(
    client: TestClient, emulator_app
) -> None:
    api, module = emulator_app
    owner = _bootstrap_company(client, slug="bugs4-gmail-owner", email="owner@bugs4-gmail.example")
    token = str(owner["access_token"])
    matter = _create_matter(client, token, "B4GMAIL-001")
    headers = {**_auth(token), **MARKER}

    unmarked = api.post(FIXTURES, headers=_auth(token), json={"matter_id": matter["id"]})
    assert unmarked.status_code == 403, unmarked.text
    seeded = api.post(FIXTURES, headers=headers, json={"matter_id": matter["id"]})
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["snippet"] == module.SNIPPET
    again = api.post(FIXTURES, headers=headers, json={"matter_id": matter["id"]})
    assert again.status_code == 409, again.text

    imported = api.post("/api/mailbox/gmail/import", headers=headers, json={"limit": 10})
    assert imported.status_code == 200, imported.text
    assert imported.json()["summary"]["imported"] == 1
    with get_session_factory()() as session:
        row = session.scalar(select(Communication).where(Communication.matter_id == matter["id"]))
        assert row is not None
        assert row.body == module.SNIPPET
        assert row.metadata_json["source"] == "gmail_provider_import"


def test_other_tenants_keep_the_real_provider_and_cannot_seed(
    client: TestClient, emulator_app
) -> None:
    api, _module = emulator_app
    owner = _bootstrap_company(client, slug="bugs4-gmail-a", email="owner@bugs4-gmail-a.example")
    other = _bootstrap_company(client, slug="other-gmail-b", email="owner@other-gmail-b.example")
    matter = _create_matter(client, str(owner["access_token"]), "B4GMAIL-002")
    other_headers = {**_auth(str(other["access_token"])), **MARKER}
    # Not a batch-4 tester tenant.
    refused = api.post(FIXTURES, headers=other_headers, json={"matter_id": matter["id"]})
    assert refused.status_code == 403, refused.text
    # A batch-4 tenant cannot seed against another tenant's Matter.
    third = _bootstrap_company(client, slug="bugs4-gmail-c", email="owner@bugs4-gmail-c.example")
    foreign = api.post(
        FIXTURES,
        headers={**_auth(str(third["access_token"])), **MARKER},
        json={"matter_id": matter["id"]},
    )
    assert foreign.status_code == 404, foreign.text
    # Nothing was registered for the other tenant: its import has no mailbox.
    imported = api.post("/api/mailbox/gmail/import", headers=other_headers, json={"limit": 10})
    assert imported.status_code == 409, imported.text
