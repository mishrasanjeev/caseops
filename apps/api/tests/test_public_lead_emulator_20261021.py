"""Guarded real local capture; production provider access remains prohibited."""

import importlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.request_context import RequestContextMiddleware
from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingEnrollment
from caseops_api.db.session import get_session_factory
from caseops_api.services import billing_demo as demo

WEB = "http://127.0.0.1:3100"
BASE = "/_e2e/platform-console/fixtures"
MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}


@pytest.fixture
def local_leads(client, monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[3] / "tests/e2e/support/oauth")
    )
    for key in (
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "CLOUD_RUN_JOB",
        "GOOGLE_CLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        "CASEOPS_ENV": "e2e",
        "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
        "CASEOPS_PUBLIC_APP_URL": WEB,
        "CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL": "founder@example.com",
        "CASEOPS_SENDGRID_API_KEY": "",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    console = importlib.import_module("platform_console_emulator")
    leads = importlib.import_module("public_lead_emulator")
    closers = []
    monkeypatch.setattr(console, "register_shutdown", closers.append)
    monkeypatch.setattr(leads, "register_shutdown", closers.append)
    from caseops_api.api.routes.billing import router

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router, prefix="/api/billing")
    capture = console.install_platform_console_emulator(app)
    leads.install_public_lead_emulator(app, capture)
    run = str(uuid4())
    try:
        with TestClient(app, headers=MARKER) as api:
            seeded = api.post(BASE, json={"run_id": run, "web_origin": WEB})
            assert seeded.status_code == 201, seeded.text
            manager = seeded.json()["manager"]["id"]
            path = f"{BASE}/{run}/leads"
            prepared = api.post(
                path, json={"web_origin": WEB, "manager_id": manager, "historical_count": 251}
            )
            assert prepared.status_code == 201, prepared.text
            yield api, capture, run, manager, path, prepared.json()
    finally:
        for close in reversed(closers):
            close()
        assert capture.server is None
        get_settings.cache_clear()


def payload(run, index):
    return {
        "idempotency_key": str(uuid4()),
        "contact_name": f"Synthetic lead {index}",
        "contact_email": f"lead-{index}-{run}@example.com",
        "segment": "solo",
        "role": "solo_advocate",
        "intent": "demo",
        "source": "homepage",
        "notes": "Synthetic private note never copied into mail",
        "privacy_notice_version": "2026-10-21",
    }


def test_seven_marked_admissions_capture_only_references_and_retain_history(local_leads):
    api, capture, run, manager, path, prepared = local_leads
    admitted = []
    for index in range(7):
        data = payload(run, index)
        response = api.post("/api/billing/enrollments/demo-request", json=data)
        if index == 5:
            assert response.status_code == 429
            assert api.post(path + "/window", json={"web_origin": WEB}).status_code == 200
            response = api.post("/api/billing/enrollments/demo-request", json=data)
        assert response.status_code == 200, response.text
        admitted.append(response.json()["id"])
    queued = api.get(path + "/mail").json()
    assert queued == {
        "items": [], "external_calls": 0,
        "outbox": [
            {
                "id": identity, "status": "pending", "attempts": 0,
                "has_claim": False, "has_lease": False, "automated_request_preserved": True,
            }
            for identity in sorted(admitted)
        ],
    }
    assert api.post(path + "/drain", json={"web_origin": WEB}).status_code == 200
    mail = api.get(path + "/mail").json()
    assert mail["external_calls"] == 0 and len(mail["items"]) == 7
    assert {item["lead_id"] for item in mail["items"]} == set(admitted)
    assert mail["outbox"] == [
        {
            "id": identity, "status": "sent", "attempts": 1,
            "has_claim": False, "has_lease": False, "automated_request_preserved": True,
        }
        for identity in sorted(admitted)
    ]
    for item in mail["items"]:
        assert item["provider_call_performed"] is False
        assert item["automated_request_preserved"] is True
        assert item["recipient_email"] == "sanjeev@orchestrum.in"
        assert "Synthetic private note" not in item["body"]
        assert "@example.com" not in item["body"]
    with get_session_factory()() as session:
        rows = list(
            session.scalars(select(BillingEnrollment).where(BillingEnrollment.id.in_(admitted)))
        )
        assert len(rows) == 7
        assert all(demo._state(row)["automated_request"] is True for row in rows)
        assert all(demo._state(row)["notification_status"] == "sent" for row in rows)
        historical = list(
            session.scalars(
                select(BillingEnrollment).where(
                    BillingEnrollment.id.in_(prepared["historical_ids"]),
                )
            )
        )
        assert len(historical) == 251 and all(
            not demo._notification_eligible(row) for row in historical
        )
    closure = api.post(path + "/cleanup", json={"web_origin": WEB, "manager_id": manager})
    assert closure.status_code == 200, closure.text
    assert closure.json()["pending_fixture_notifications"] == 0
    assert closure.json()["retained"] and closure.json()["founder_unchanged"]
    assert api.post(path + "/window", json={"web_origin": WEB}).status_code == 409
    assert (
        api.post("/api/billing/enrollments/demo-request", json=payload(run, 0)).status_code == 409
    )
    assert capture.external_calls == 0


@pytest.mark.parametrize("adapter", ["https://example.com/mail", "http://127.0.0.1:80/?x=1"])
def test_invalid_local_adapter_never_falls_through_to_sendgrid(local_leads, monkeypatch, adapter):
    api, capture, run, _manager, path, _prepared = local_leads
    monkeypatch.setenv("CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL", adapter)
    response = api.post("/api/billing/enrollments/demo-request", json=payload(run, 0))
    assert response.status_code == 200
    identity = response.json()["id"]
    assert api.get(path + "/mail").json() == {
        "items": [], "external_calls": 0,
        "outbox": [{
            "id": identity, "status": "pending", "attempts": 0,
            "has_claim": False, "has_lease": False, "automated_request_preserved": True,
        }],
    }
    assert api.post(path + "/drain", json={"web_origin": WEB}).status_code == 200
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, response.json()["id"])
        assert demo._state(row)["notification_status"] == "exhausted"
        assert demo._state(row)["last_error_code"] == "test_transport_not_admitted"
        assert demo._state(row)["automated_request"] is True
    assert api.get(path + "/mail").json() == {
        "items": [], "external_calls": 0,
        "outbox": [{
            "id": identity, "status": "exhausted", "attempts": 0,
            "has_claim": False, "has_lease": False, "automated_request_preserved": True,
        }],
    }
    assert capture.external_calls == 0


def test_local_fixture_marker_origin_replay_and_pii_fences(local_leads):
    api, capture, run, manager, path, _prepared = local_leads
    assert api.post(path, json={"web_origin": WEB, "manager_id": manager}).status_code == 409
    assert api.post(path + "/window", json={"web_origin": "https://caseops.ai"}).status_code == 409
    assert api.get(path + "/mail", headers={"X-CaseOps-Automated-Test": "wrong"}).status_code == 403
    assert api.get(f"{BASE}/{uuid4()}/leads/mail").status_code == 409
    with pytest.raises(ValueError, match="canonical reference-only"):
        capture.receive(
            {
                "lead_id": str(uuid4()),
                "to": "sanjeev@orchestrum.in",
                "subject": "CaseOps public enquiry saved",
                "body": "private contact body",
            }
        )
    assert api.get(path + "/mail").json()["items"] == []
