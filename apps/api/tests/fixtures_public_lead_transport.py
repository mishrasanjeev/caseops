"""Scoped offline adapter admission for independently owned native test databases."""

import json
import os
import re
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy.engine import make_url

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.core.settings import get_settings
from caseops_api.services import billing_demo


def install_offline_lead_adapter(request, monkeypatch):
    endpoint = f"http://127.0.0.1:1/pytest-public-leads/{uuid4()}"
    messages = []
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "")
    get_settings.cache_clear()

    def admitted_adapter():
        if not paid_providers_blocked_for_request():
            return None
        settings = get_settings()
        if (
            request.node.path.name
            not in {"test_seo_demo_20261009.py", "test_rate_identity_edge_20261009.py"}
            or settings.env != "local"
            or settings.sendgrid_api_key
            or str(settings.public_app_url).rstrip("/") != "http://testserver"
            or any(
                os.environ.get(key)
                for key in (
                    "K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB",
                    "GOOGLE_CLOUD_PROJECT",
                )
            )
        ):
            raise billing_demo.NotificationFenceClosed
        database = make_url(settings.database_url)
        if database.get_backend_name() == "postgresql":
            engine = request.getfixturevalue("http_pg_engine")
            owned = (
                database == engine.url
                and database.host in {"127.0.0.1", "localhost"}
                and re.fullmatch(r"caseops_http_[0-9a-f]{32}", database.database or "")
            )
        else:
            owned = (
                database.drivername == "sqlite+pysqlite"
                and database.database
                and Path(database.database).resolve().is_relative_to(
                    request.getfixturevalue("tmp_path").resolve()
                )
            )
        if not owned:
            raise billing_demo.NotificationFenceClosed
        return endpoint

    def offline_http(_transport, wire_request):
        if str(wire_request.url) != endpoint or wire_request.method != "POST":
            raise AssertionError("Unexpected HTTP transport in the offline lead fixture.")
        body = json.loads(wire_request.read())
        identity = str(UUID(body["lead_id"]))
        assert set(body) == {"lead_id", "to", "subject", "body"}
        assert body == {
            "lead_id": identity,
            "to": "sanjeev@orchestrum.in",
            "subject": "CaseOps public enquiry saved",
            "body": (
                f"Public enquiry {identity} is saved.\n"
                "Review its details in the protected administrative dashboard: "
                "https://caseops.ai/platform/leads\n"
            ),
        }
        messages.append(body)
        return httpx.Response(202, request=wire_request)

    # Only adapter admission is substituted. The production no-paid predicates,
    # persisted marker, eligibility, durable claim and final send fence remain real.
    monkeypatch.setattr(billing_demo, "_local_notification_adapter", admitted_adapter)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", offline_http)
    return {"endpoint": endpoint, "messages": messages}
