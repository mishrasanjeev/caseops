"""Post-finalization ownership guard for the raw mail-emulator fixtures."""

import os
from collections.abc import Iterator

import pytest

from caseops_api.services import billing_demo as demo
from caseops_api.services import platform_console

_ENVIRONMENT_KEYS = (
    "CASEOPS_CONSOLE_TEST_MAIL_URL",
    "CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL",
    "CASEOPS_DEMO_NOTIFICATION_ENABLED",
    "CASEOPS_DEMO_RETENTION_ENABLED",
)


def guarded_emulator_monkeypatch() -> Iterator[pytest.MonkeyPatch]:
    """Keep builtin monkeypatch lifetime, then check every raw mail owner."""
    environment = {
        key: (key in os.environ, os.environ.get(key)) for key in _ENVIRONMENT_KEYS
    }
    demo_sender = demo._send_via_sendgrid
    console_sender = platform_console._send_via_sendgrid
    monkeypatch = pytest.MonkeyPatch()
    try:
        yield monkeypatch
    finally:
        monkeypatch.undo()
        assert {
            key: (key in os.environ, os.environ.get(key)) for key in _ENVIRONMENT_KEYS
        } == environment
        assert demo._send_via_sendgrid is demo_sender
        assert platform_console._send_via_sendgrid is console_sender
