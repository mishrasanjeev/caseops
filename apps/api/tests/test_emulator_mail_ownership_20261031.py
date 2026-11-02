"""Bound the complete raw-installer and monkeypatch ownership lifetime."""

import importlib
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest
from fastapi import FastAPI

from caseops_api.services import billing_demo as demo
from caseops_api.services import platform_console
from tests.emulator_mail_ownership import guarded_emulator_monkeypatch

HARNESS = Path(__file__).resolve().parents[3] / "tests/e2e/support/oauth"
WEB = "http://127.0.0.1:3100"
MAIL_BASELINE = {
    "CASEOPS_CONSOLE_TEST_MAIL_URL": "http://127.0.0.1:1/sentinel-console",
    "CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL": "http://127.0.0.1:1/sentinel-lead",
    "CASEOPS_DEMO_NOTIFICATION_ENABLED": "false",
    "CASEOPS_DEMO_RETENTION_ENABLED": "true",
}


def _environment_snapshot():
    return {key: (key in os.environ, os.environ.get(key)) for key in MAIL_BASELINE}


@pytest.mark.parametrize("owner", ["console", "lead"])
@pytest.mark.parametrize("preexisting", [False, True], ids=["absent", "sentinel"])
@pytest.mark.parametrize("interrupted", [False, True], ids=["normal", "exception"])
def test_raw_installer_restores_complete_monkeypatch_boundary(owner, preexisting, interrupted):
    original_environment = _environment_snapshot()
    original_demo_sender = demo._send_via_sendgrid
    original_console_sender = platform_console._send_via_sendgrid

    with pytest.MonkeyPatch.context() as parent_patch:
        parent_patch.syspath_prepend(str(HARNESS))
        for key in (
            "K_SERVICE",
            "K_REVISION",
            "K_CONFIGURATION",
            "CLOUD_RUN_JOB",
            "GOOGLE_CLOUD_PROJECT",
        ):
            parent_patch.delenv(key, raising=False)
        for key, value in {
            "CASEOPS_ENV": "e2e",
            "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
            "CASEOPS_PUBLIC_APP_URL": WEB,
            "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///isolated.db",
            "CASEOPS_SENDGRID_API_KEY": "",
        }.items():
            parent_patch.setenv(key, value)
        for key, value in MAIL_BASELINE.items():
            if preexisting:
                parent_patch.setenv(key, value)
            else:
                parent_patch.delenv(key, raising=False)

        console = importlib.import_module("platform_console_emulator")
        leads = importlib.import_module("public_lead_emulator")
        before_install = _environment_snapshot()
        before_demo_sender = demo._send_via_sendgrid
        before_console_sender = platform_console._send_via_sendgrid

        with contextmanager(guarded_emulator_monkeypatch)() as monkeypatch:
            closers = []
            monkeypatch.setattr(console, "register_shutdown", closers.append)
            monkeypatch.setattr(leads, "register_shutdown", closers.append)
            expected_exit = (
                pytest.raises(RuntimeError, match="^simulated malformed override failure$")
                if interrupted
                else nullcontext()
            )
            with expected_exit:
                try:
                    app = FastAPI()
                    capture = console.install_platform_console_emulator(app)
                    original_receive = capture.receive
                    console_url = os.environ["CASEOPS_CONSOLE_TEST_MAIL_URL"]
                    assert capture.server is not None
                    assert console_url == (
                        f"http://127.0.0.1:{capture.server.server_port}{capture.capture_path}"
                    )
                    assert capture.thread is not None
                    assert capture.thread.is_alive()
                    assert len(closers) == 1
                    assert closers[0].__module__ == console.__name__
                    assert closers[0].__qualname__ == (
                        "install_platform_console_emulator.<locals>.close"
                    )
                    console_sender = platform_console._send_via_sendgrid
                    assert console_sender.__self__ is capture
                    assert console_sender.__func__ is console.ConsoleMailCapture.reject_external

                    if owner == "lead":
                        lead_close = leads.install_public_lead_emulator(app, capture)
                        assert len(closers) == 2
                        assert closers[1] is lead_close
                        assert lead_close.__module__ == leads.__name__
                        assert lead_close.__qualname__ == (
                            "install_public_lead_emulator.<locals>.close"
                        )
                        demo_sender = demo._send_via_sendgrid
                        assert demo_sender.__self__ is capture
                        assert demo_sender.__func__ is console.ConsoleMailCapture.reject_external
                        assert os.environ["CASEOPS_DEMO_NOTIFICATION_ENABLED"] == "true"
                        assert os.environ["CASEOPS_DEMO_RETENTION_ENABLED"] == "false"
                        owned_key = "CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL"
                    else:
                        assert demo._send_via_sendgrid is before_demo_sender
                        owned_key = "CASEOPS_CONSOLE_TEST_MAIL_URL"

                    owned_url = os.environ[owned_key]
                    assert owned_url == console_url
                    try:
                        with monkeypatch.context() as malformed:
                            malformed.setenv(owned_key, "http://127.0.0.1:80/?x=1")
                            assert os.environ[owned_key] == "http://127.0.0.1:80/?x=1"
                            if interrupted:
                                raise RuntimeError("simulated malformed override failure")
                    finally:
                        # Release the override before raw closers, including on exceptions.
                        assert os.environ[owned_key] == owned_url
                        assert os.environ["CASEOPS_CONSOLE_TEST_MAIL_URL"] == console_url
                        assert capture.server is not None
                        assert capture.external_calls == 0
                finally:
                    for close in reversed(closers):
                        close()

            assert capture.server is None
            assert not capture.thread.is_alive()
            assert capture.external_calls == 0
            assert capture.receive.__self__ is original_receive.__self__
            assert capture.receive.__func__ is original_receive.__func__
            assert _environment_snapshot() == before_install
            assert demo._send_via_sendgrid is before_demo_sender
            assert platform_console._send_via_sendgrid is before_console_sender

        assert _environment_snapshot() == before_install
        assert demo._send_via_sendgrid is before_demo_sender
        assert platform_console._send_via_sendgrid is before_console_sender

    assert _environment_snapshot() == original_environment
    assert demo._send_via_sendgrid is original_demo_sender
    assert platform_console._send_via_sendgrid is original_console_sender
