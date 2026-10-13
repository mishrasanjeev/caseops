"""Neutral SendGrid transport, unchanged wire contract and offline dispatch."""

from __future__ import annotations

import ast
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from tests.test_ip_service_dependencies_20261014 import _route
from tests.test_ip_service_dependencies_20261014 import dependency_graph as _dependency_graph

dependency_graph = _dependency_graph
SRC = Path(__file__).resolve().parents[1] / "src"
LEAF = "caseops_api.services.sendgrid_transport"
SENDER_AST_SHA256 = "d73d161ff30a6e73191488315213ca83e616ddaaa810446e931b47dc4e210c8a"


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("External HTTP transport is forbidden in this offline regression")

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("External HTTP transport is forbidden in this offline regression")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async)


@pytest.fixture
def transport_settings(monkeypatch):
    from caseops_api.services import sendgrid_transport

    settings = SimpleNamespace(
        sendgrid_api_key="fake-offline-key",
        sendgrid_sender_email="sender@example.invalid",
        sendgrid_sender_name="Offline sender",
    )
    monkeypatch.setattr(sendgrid_transport, "get_settings", lambda: settings)
    return settings


def test_delivery_imports_neutral_sender():
    tree = ast.parse((SRC / "caseops_api/services/notification_delivery.py").read_text())
    owners = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == "_send_via_sendgrid" for alias in node.names)
    }
    assert owners == {LEAF}


def test_leaf_dependencies_are_only_settings_and_httpx():
    source = SRC / "caseops_api/services/sendgrid_transport.py"
    assert source.is_file()
    tree = ast.parse(source.read_text())
    dependencies = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert dependencies == {"__future__", "caseops_api.core.settings", "httpx"}


@pytest.mark.parametrize(
    "workflow", ("communications", "notification_delivery", "ip_operations", "ip_renewals")
)
def test_leaf_cannot_reach_workflows(dependency_graph, workflow):
    assert LEAF in dependency_graph
    assert _route(dependency_graph, LEAF, "caseops_api.services." + workflow) is None


def test_sender_body_matches_immutable_ed():
    tree = ast.parse((SRC / "caseops_api/services/sendgrid_transport.py").read_text())
    sender = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_send_via_sendgrid"
    )
    assert sha256(ast.dump(sender, include_attributes=False).encode()).hexdigest() == (
        SENDER_AST_SHA256
    )


def test_communications_alias_and_settings_getter_are_identical():
    from caseops_api.core.settings import get_settings
    from caseops_api.services import communications, sendgrid_transport

    assert communications._send_via_sendgrid is sendgrid_transport._send_via_sendgrid
    assert communications._send_via_sendgrid.__module__ == LEAF
    assert communications.get_settings is sendgrid_transport.get_settings is get_settings


@pytest.mark.parametrize("status", (200, 202))
@pytest.mark.parametrize("recipient_name", (None, "Offline recipient"))
@pytest.mark.parametrize("custom_args", (None, {"notification_intent_id": "offline-intent"}))
def test_exact_request_payload_and_timeout_without_network(
    monkeypatch, transport_settings, status, recipient_name, custom_args,
):
    from caseops_api.services import sendgrid_transport

    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(status, headers={"X-Message-Id": "offline-message"})

    monkeypatch.setattr(httpx, "post", post)
    assert sendgrid_transport._send_via_sendgrid(
        to_email="recipient@example.invalid",
        recipient_name=recipient_name,
        subject="Offline subject",
        body_text="Offline body",
        custom_args=custom_args,
    ) == (True, "offline-message", None)
    recipient = {"email": "recipient@example.invalid"}
    if recipient_name:
        recipient["name"] = recipient_name
    personalization = {"to": [recipient]}
    if custom_args:
        personalization["custom_args"] = custom_args
    assert calls == [
        (
            "https://api.sendgrid.com/v3/mail/send",
            {
                "headers": {
                    "Authorization": f"Bearer {transport_settings.sendgrid_api_key}",
                    "Content-Type": "application/json",
                },
                "json": {
                    "personalizations": [personalization],
                    "from": {
                        "email": transport_settings.sendgrid_sender_email,
                        "name": transport_settings.sendgrid_sender_name,
                    },
                    "subject": "Offline subject",
                    "content": [{"type": "text/plain", "value": "Offline body"}],
                },
                "timeout": 20,
            },
        )
    ]


@pytest.mark.parametrize("status", (400, 429, 500))
def test_provider_error_and_two_hundred_character_bound_are_unchanged(
    monkeypatch, transport_settings, status,
):
    from caseops_api.services import sendgrid_transport

    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: httpx.Response(
        status, text="synthetic-provider-error-" * 30,
    ))
    assert sendgrid_transport._send_via_sendgrid(
        to_email="recipient@example.invalid", recipient_name=None, subject="Offline", body_text="",
    ) == (False, None, f"sendgrid {status}: " + ("synthetic-provider-error-" * 30)[:200])


def test_transport_exception_still_reaches_the_callers_boundary(monkeypatch, transport_settings):
    from caseops_api.services import sendgrid_transport

    error = httpx.ReadTimeout("Synthetic offline timeout")

    def timeout(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(httpx, "post", timeout)
    with pytest.raises(httpx.ReadTimeout) as caught:
        sendgrid_transport._send_via_sendgrid(
            to_email="recipient@example.invalid", recipient_name=None,
            subject="Offline", body_text="",
        )
    assert caught.value is error


def test_each_send_reads_current_canonical_settings(monkeypatch):
    from caseops_api.services import sendgrid_transport

    reads, calls = [], []

    def settings():
        reads.append(len(reads) + 1)
        return SimpleNamespace(
            sendgrid_api_key=f"fake-offline-key-{len(reads)}",
            sendgrid_sender_email=f"sender-{len(reads)}@example.invalid",
            sendgrid_sender_name=f"Offline sender {len(reads)}",
        )

    def post(_url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(202)

    monkeypatch.setattr(sendgrid_transport, "get_settings", settings)
    monkeypatch.setattr(httpx, "post", post)
    for _ in range(2):
        assert sendgrid_transport._send_via_sendgrid(
            to_email="recipient@example.invalid", recipient_name=None,
            subject="Offline", body_text="",
        ) == (True, None, None)
    assert reads == [1, 2]
    assert [call["headers"]["Authorization"] for call in calls] == [
        "Bearer fake-offline-key-1", "Bearer fake-offline-key-2",
    ]
    assert [call["json"]["from"]["email"] for call in calls] == [
        "sender-1@example.invalid", "sender-2@example.invalid",
    ]


def test_unmocked_http_is_rejected_before_any_socket(transport_settings):
    from caseops_api.services import sendgrid_transport

    with pytest.raises(AssertionError, match="External HTTP transport is forbidden"):
        sendgrid_transport._send_via_sendgrid(
            to_email="recipient@example.invalid", recipient_name=None,
            subject="Offline", body_text="",
        )


def test_notification_dispatch_uses_leaf_fake_with_no_open_transaction(client, monkeypatch):
    from caseops_api.core.settings import get_settings
    from caseops_api.db.session import get_session_factory
    from caseops_api.services import communications, notification_delivery, sendgrid_transport
    from tests.test_auth_company import bootstrap_company
    from tests.test_notification_convergence_20260804 import _context

    bootstrap_company(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "fake-offline-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.invalid")
    calls = []
    sessions = []

    def fake(**kwargs):
        assert not sessions[0].in_transaction()
        calls.append(kwargs)
        return True, "offline-leaf-message", None

    def forbidden_compatibility_sender(**_kwargs):
        raise AssertionError("Delivery must not import the communications workflow")

    monkeypatch.setattr(sendgrid_transport, "_send_via_sendgrid", fake)
    monkeypatch.setattr(communications, "_send_via_sendgrid", forbidden_compatibility_sender)
    with get_session_factory()() as session:
        sessions.append(session)
        context = _context(session)
        intent = notification_delivery.enqueue_notification_delivery_intent(
            session, context=context, recipient_membership=context.membership,
            channel="email", event_type="hearing_upcoming", source_type="hearing_reminder",
            source_id="offline-leaf-dispatch", title="Private title", body="Private body",
        )
        assert intent is not None
        session.commit()
        result = notification_delivery.process_notification_delivery_intent(
            session, intent_id=intent.id, context=context,
        )
        session.commit()
        assert result.status == "sent" and intent.provider_event_id == "offline-leaf-message"
        assert intent.attempts == 1
        assert len(calls) == 1
        assert calls[0]["subject"] == "CaseOps notification"
        assert calls[0]["body_text"] == "Open CaseOps to review this notification securely."
        assert calls[0]["custom_args"] == {"notification_intent_id": intent.id}
