from __future__ import annotations

import importlib
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Event, RLock, current_thread, get_ident
from unittest.mock import Mock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

HARNESS = Path(__file__).resolve().parents[3] / "tests/e2e/support/oauth"
WEB = "http://127.0.0.1:3100"


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS))
    return importlib.import_module("platform_console_emulator")


@pytest.mark.parametrize(
    "change",
    [
        {"CASEOPS_ENV": "production"},
        {"CASEOPS_ENV": "local"},
        {"CASEOPS_E2E_OAUTH_EMULATOR": ""},
        {"K_SERVICE": "api"},
        {"K_REVISION": "revision"},
        {"K_CONFIGURATION": "config"},
        {"CLOUD_RUN_JOB": "job"},
        {"GOOGLE_CLOUD_PROJECT": "project"},
        {"CASEOPS_PUBLIC_APP_URL": "https://caseops.ai"},
        {"CASEOPS_DATABASE_URL": "postgresql+psycopg://u:p@production/caseops"},
    ],
)
def test_console_capture_rejects_remote_runtime_before_app_or_transport(
    harness, monkeypatch, change
):
    environment = {
        "CASEOPS_ENV": "e2e",
        "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
        "CASEOPS_PUBLIC_APP_URL": WEB,
        "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///isolated.db",
        **change,
    }
    for key in (
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "CLOUD_RUN_JOB",
        "GOOGLE_CLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    app = Mock()
    started = Mock(side_effect=AssertionError("Transport must not start."))
    monkeypatch.setattr(harness.ConsoleMailCapture, "start", started)
    with pytest.raises((RuntimeError, ValueError)):
        harness.install_platform_console_emulator(app)
    started.assert_not_called()
    app.post.assert_not_called()
    app.get.assert_not_called()


def message(run, *, origin=WEB):
    return {
        "to": f"pra-manager-{run}@example.com",
        "subject": "CaseOps reports console setup",
        "body": (
            f"Use this one-time link within 30 minutes:\n{origin}/platform/setup#token={'a' * 43}\n"
            "Ignore it if you did not expect this request."
        ),
    }


def test_console_capture_real_loopback_transport_and_inventory_fences(harness):
    capture = harness.ConsoleMailCapture(WEB)
    first, second = str(uuid4()), str(uuid4())
    capture.register(first, WEB)
    capture.register(second, WEB)
    target = capture.start()
    thread = capture.thread
    try:
        with httpx.Client(trust_env=False, timeout=3) as client:
            assert client.post(target, json=message(first)).status_code == 202
            assert client.post(target, json=message(second)).status_code == 202
            assert (
                client.post(target, json=message(first, origin="https://caseops.ai")).status_code
                == 400
            )
            assert (
                client.post(
                    target, json={**message(first), "to": "real@outside.example"}
                ).status_code
                == 400
            )
            assert client.post(target, content=b"x" * 16_385).status_code == 400
            assert client.post(target + "/other", json=message(first)).status_code == 400
        ledger = capture.ledger(first, harness.MARKER)
        assert len(ledger["items"]) == 1
        assert ledger["external_calls"] == 0
        assert ledger["items"][0]["run_id"] == first
        assert ledger["items"][0]["provider_call_performed"] is False
        assert len(capture.ledger(second, harness.MARKER)["items"]) == 1
        with pytest.raises(ValueError):
            capture.ledger(first, "not-the-marker")
        with pytest.raises(ValueError):
            capture.register(first, WEB)
        with pytest.raises(ValueError):
            capture.receive(message(str(uuid4())))
        for _ in range(31):
            capture.receive(message(first))
        with pytest.raises(ValueError):
            capture.receive(message(first))
        with pytest.raises(RuntimeError):
            capture.reject_external(to_email="must-not-send@example.com")
        assert capture.ledger(first, harness.MARKER)["external_calls"] == 1
    finally:
        capture.stop()
    assert not thread.is_alive()
    capture.stop()


@pytest.mark.parametrize(
    "origin",
    [
        "https://caseops.ai",
        "http://127.0.0.1:3100/path",
        "http://127.0.0.1:3100?x=1",
        "http://user@127.0.0.1:3100",
        "http://localhost",
        "http://127.0.0.1:3100#fragment",
    ],
)
def test_console_capture_requires_exact_origin(harness, origin):
    with pytest.raises(ValueError):
        harness.ConsoleMailCapture(origin)


def test_fixture_routes_register_before_seed_and_admit_only_one_exact_cleanup(harness, monkeypatch):
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
        "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///isolated.db",
    }.items():
        monkeypatch.setenv(key, value)
    fixtures = importlib.import_module("platform_report_fixtures")
    manager = str(uuid4())
    runs = []
    cleanups = []
    closers = []
    monkeypatch.setattr(harness, "register_shutdown", closers.append)

    def seed(**kwargs):
        runs.append(kwargs)
        capture.receive(message(kwargs["run_id"]))
        return {"manager": {"id": manager}}

    def cleanup(**kwargs):
        cleanups.append(kwargs)
        return {"status": "revoked", "manager_id": manager}

    monkeypatch.setattr(fixtures, "seed_console_fixture", seed)
    monkeypatch.setattr(fixtures, "cleanup_console_fixture", cleanup)
    app = FastAPI()
    from caseops_api.core.csrf import CSRFMiddleware
    from caseops_api.core.request_context import RequestContextMiddleware

    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestContextMiddleware)
    original = os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL")
    capture = harness.install_platform_console_emulator(app)
    run = str(uuid4())
    body = {"run_id": run, "web_origin": WEB}
    csrf = {
        "Cookie": "caseops_csrf=isolated-fixture-nonce",
        "X-CSRF-Token": "isolated-fixture-nonce",
    }
    headers = {**csrf, "X-CaseOps-Automated-Test": harness.MARKER}
    try:
        with TestClient(app) as client:
            assert client.post(harness.PREFIX + "/fixtures", json=body).status_code == 403
            assert not runs and not capture.runs
            assert (
                client.post(harness.PREFIX + "/fixtures", json=body, headers=csrf).status_code
                == 403
            )
            assert (
                client.post(
                    harness.PREFIX + "/fixtures",
                    json=body,
                    headers={"X-CaseOps-Automated-Test": harness.MARKER},
                ).status_code
                == 403
            )
            assert not runs and not capture.runs
            assert (
                client.post(harness.PREFIX + "/fixtures", json=body, headers=headers).status_code
                == 201
            )
            assert len(runs) == 1
            assert (
                client.post(harness.PREFIX + "/fixtures", json=body, headers=headers).status_code
                == 409
            )
            ledger = client.get(harness.PREFIX + "/mail", params={"run_id": run}, headers=headers)
            assert ledger.status_code == 200 and len(ledger.json()["items"]) == 1
            path = harness.PREFIX + f"/fixtures/{run}/cleanup"
            assert (
                client.post(
                    path, json={"web_origin": WEB, "manager_id": str(uuid4())}, headers=headers
                ).status_code
                == 409
            )
            assert not cleanups
            admitted = {"web_origin": WEB, "manager_id": manager}
            assert client.post(path, json=admitted, headers=headers).status_code == 200
            assert len(cleanups) == 1
            assert client.post(path, json=admitted, headers=headers).status_code == 409
            assert len(cleanups) == 1
            assert (
                client.get(
                    harness.PREFIX + "/mail", params={"run_id": str(uuid4())}, headers=headers
                ).status_code
                == 404
            )
    finally:
        closers[0]()
    assert os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL") == original


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_capture_stop_closes_partial_requests_and_joins_handlers(harness, monkeypatch, phase):
    capture = harness.ConsoleMailCapture(WEB)
    capture.start()
    server, serving_thread = capture.server, capture.thread
    entered, handlers = Event(), []
    method = "parse_request" if phase == "headers" else "do_POST"
    original = getattr(server.RequestHandlerClass, method)

    def pause_point(handler):
        handlers.append((handler.connection, current_thread()))
        entered.set()
        return original(handler)

    monkeypatch.setattr(server.RequestHandlerClass, method, pause_point)
    peer = socket.create_connection(server.server_address, timeout=3)
    prefix = f"POST {capture.capture_path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
    partial = "X-Partial:" if phase == "headers" else "Content-Length: 128\r\n\r\n{"
    try:
        peer.sendall((prefix + partial).encode("ascii"))
        assert entered.wait(3), "The actual partial-request parsing boundary was not reached."
        capture.stop()
        assert not serving_thread.is_alive()
        assert len(handlers) == 1
        connection, worker = handlers[0]
        assert not worker.is_alive(), "Capture stop returned with an owned handler still running."
        assert not worker.daemon
        assert connection.gettimeout() == 2
        assert not server.sockets and not server.handlers
        assert not capture.messages and capture.external_calls == 0
        try:
            assert peer.recv(1) == b""
        except (ConnectionAbortedError, ConnectionResetError):
            # Windows may report a reset instead of EOF after forced socket shutdown.
            pass
        capture.stop()
    finally:
        try:
            peer.shutdown(socket.SHUT_RDWR)
        except OSError:
            # The capture may already have closed this deliberately incomplete peer.
            pass
        peer.close()
        for _connection, worker in handlers:
            worker.join(timeout=3)
            assert not worker.is_alive(), "Partial-request regression leaked its handler."
        capture.stop()


def test_cleanup_admission_is_atomic_for_two_actual_contenders(harness, monkeypatch):
    for key in ("K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB",
                "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        "CASEOPS_ENV": "e2e", "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
        "CASEOPS_PUBLIC_APP_URL": WEB, "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///isolated.db",
    }.items():
        monkeypatch.setenv(key, value)
    fixtures = importlib.import_module("platform_report_fixtures")
    manager, run, closers, calls = str(uuid4()), str(uuid4()), [], []
    monkeypatch.setattr(harness, "register_shutdown", closers.append)
    monkeypatch.setattr(
        fixtures, "cleanup_console_fixture",
        lambda **kwargs: calls.append(kwargs) or {"status": "revoked", "manager_id": manager},
    )
    app = FastAPI()
    capture = harness.install_platform_console_emulator(app)
    capture.register(run, WEB)
    capture.runs[run].update(state="ready", manager_id=manager)
    endpoint = next(route.endpoint for route in app.routes
                    if route.path == harness.PREFIX + "/fixtures/{run_id}/cleanup")
    first_read, release_first, second_attempt, second_read = (Event() for _ in range(4))
    identities, first_owns_lock = {}, []
    raw_lock, depths = RLock(), {}

    class ObservedLock:
        def __enter__(self):
            identity = get_ident()
            if identity == identities.get("second"):
                second_attempt.set()
            raw_lock.acquire()
            depths[identity] = depths.get(identity, 0) + 1

        def __exit__(self, *_args):
            identity = get_ident()
            depths[identity] -= 1
            raw_lock.release()

    capture.lock = ObservedLock()
    original_admit = capture.admit

    def observed_admit(*args):
        state = original_admit(*args)
        if get_ident() == identities["first"]:
            first_owns_lock.append(bool(depths.get(get_ident(), 0)))
            first_read.set()
            assert release_first.wait(3), "Cleanup admission boundary was not released."
        else:
            second_read.set()
        return state

    monkeypatch.setattr(capture, "admit", observed_admit)

    def invoke(role):
        identities[role] = get_ident()
        request = Request({"type": "http", "headers": [
            (b"x-caseops-automated-test", harness.MARKER.encode("ascii")),
        ]})
        try:
            endpoint(run, harness.Cleanup(web_origin=WEB, manager_id=manager), request)
            return 200
        except HTTPException as error:
            return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                first = pool.submit(invoke, "first")
                assert first_read.wait(3)
                second = pool.submit(invoke, "second")
                assert second_attempt.wait(3)
                # The old unlocked snapshot must be duplicated before release;
                # an atomic claim instead holds the second contender at its lock.
                if not first_owns_lock[0]:
                    assert second_read.wait(3)
                else:
                    assert not second_read.is_set()
                release_first.set()
                assert sorted([first.result(timeout=3), second.result(timeout=3)]) == [200, 409]
                assert first_owns_lock == [True]
                assert len(calls) == 1
                assert calls[0] == {"run_id": run, "web_origin": WEB,
                                    "automated_marker": harness.MARKER, "manager_id": manager}
                assert capture.runs[run]["state"] == "cleaned"
            finally:
                release_first.set()
    finally:
        closers[0]()


@pytest.fixture
def invitation_age_fixture(harness, monkeypatch, tmp_path):
    """Own SQLite only: no app server, shared DB, mail socket or provider transport."""
    from caseops_api.core.settings import get_settings
    from caseops_api.db import session as database
    from caseops_api.db.models import (
        Company,
        CompanyMembership,
        CustomRole,
        PlatformAdminMembership,
        PlatformConsoleDelivery,
        PlatformConsoleSession,
        PlatformConsoleToken,
        PlatformReportAdmin,
        PlatformReportAuditEvent,
        User,
    )
    from caseops_api.services import platform_console as console

    for key in (
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "CLOUD_RUN_JOB",
        "GOOGLE_CLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)
    url = "sqlite+pysqlite:///" + (tmp_path / "invitation-age.db").as_posix()
    for key, value in {
        "CASEOPS_ENV": "e2e",
        "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
        "CASEOPS_PUBLIC_APP_URL": WEB,
        "CASEOPS_DATABASE_URL": url,
        "CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL": "fixture-founder@example.com",
        "CASEOPS_AUTH_SECRET": "isolated-invitation-age-secret-at-least-32-bytes",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    models = (
        Company,
        User,
        CustomRole,
        CompanyMembership,
        PlatformAdminMembership,
        PlatformReportAdmin,
        PlatformConsoleSession,
        PlatformConsoleToken,
        PlatformConsoleDelivery,
        PlatformReportAuditEvent,
    )
    Company.metadata.create_all(engine, tables=[model.__table__ for model in models])
    factory = sessionmaker(engine, class_=database.CaseOpsSession, expire_on_commit=False)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    run = str(uuid4())
    now = datetime.now(UTC)
    with factory() as session:
        company = Company(
            name="Synthetic preserved tenant", slug=run, tenant_key=run, company_type="law_firm"
        )
        session.add(company)
        users = [
            User(
                email=email,
                full_name=email.split("@")[0],
                password_hash="synthetic-credential",
                is_active=True,
            )
            for email in (
                "fixture-founder@example.com",
                f"pra-manager-{run}@example.com",
                f"viewer-{run}@example.com",
            )
        ]
        session.add_all(users)
        session.flush()
        session.add_all(
            [
                CompanyMembership(
                    company_id=company.id, user_id=users[index].id, role="owner", is_active=True
                )
                for index in (0, 2)
            ]
        )
        root = PlatformAdminMembership(user_id=users[0].id, role="super_admin", status="active")
        session.add(root)
        session.flush()
        manager = PlatformReportAdmin(
            user_id=users[1].id,
            root_platform_admin_id=root.id,
            role="manager",
            status="active",
            mfa_status="enrolled",
            encrypted_totp_secret="synthetic-encrypted-factor",
        )
        session.add(manager)
        session.flush()
        viewer = PlatformReportAdmin(
            user_id=users[2].id,
            root_platform_admin_id=root.id,
            created_by_report_admin_id=manager.id,
            role="viewer",
            status="pending",
        )
        session.add(viewer)
        session.flush()
        token = PlatformConsoleToken(
            report_admin_id=viewer.id,
            purpose="invite",
            token_hash="1" * 64,
            credential_hash=sha256(users[2].password_hash.encode()).hexdigest(),
            auth_epoch=viewer.auth_epoch,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        session.add(token)
        issued = console._issue(session, manager, users[1], purpose="authenticated")
        session.add(
            PlatformReportAuditEvent(
                report_admin_id=manager.id,
                actor_user_id=users[1].id,
                action="console.invited",
                target_id=viewer.id,
            )
        )
        session.commit()
        ids = {
            "root": root.id,
            "manager": manager.id,
            "viewer": viewer.id,
            "token": token.id,
            "founder_user": users[0].id,
            "manager_user": users[1].id,
            "viewer_user": users[2].id,
            "console_session": session.scalar(select(PlatformConsoleSession.id)),
        }
    fixture = {
        "fixtures": importlib.import_module("platform_report_fixtures"),
        "factory": factory,
        "run": run,
        "ids": ids,
        "models": models,
        "token": issued.token,
        "csrf": issued.csrf,
        "arguments": {
            "run_id": run,
            "web_origin": WEB,
            "automated_marker": harness.MARKER,
            "manager_id": ids["manager"],
            "viewer_id": ids["viewer"],
            "manager_session": issued.token,
            "manager_csrf": issued.csrf,
        },
    }
    try:
        yield fixture
    finally:
        engine.dispose()


def _age_database_snapshot(fixture):
    with fixture["factory"]() as session:
        return {
            model.__tablename__: [
                tuple(row)
                for row in session.execute(
                    select(*model.__table__.columns).order_by(model.id),
                )
            ]
            for model in fixture["models"]
        }


def test_long_account_name_fixture_roundtrips_in_owned_sqlite(invitation_age_fixture):
    from caseops_api.db.models import Company

    f = invitation_age_fixture
    name = f"PRA {UUID(f['run']).int} {f['fixtures'].LONG_FIRM_LABEL}"
    assert 180 < len(name) <= 255
    assert max(map(len, name.split())) >= 80
    with f["factory"]() as session:
        company = Company(
            name=name, slug=str(uuid4()), tenant_key=str(uuid4()), company_type="law_firm",
        )
        session.add(company)
        session.commit()
        assert session.scalar(select(Company.name).where(Company.id == company.id)) == name


def test_invitation_age_changes_only_current_created_at_and_preserves_all_other_rows(
    invitation_age_fixture,
):
    f = invitation_age_fixture
    from caseops_api.db.models import PlatformConsoleToken

    with f["factory"]() as session:
        current = session.get(PlatformConsoleToken, f["ids"]["token"])
        session.add_all(
            [
                PlatformConsoleToken(
                    report_admin_id=f["ids"]["viewer"],
                    purpose=purpose,
                    token_hash=digest * 64,
                    credential_hash=current.credential_hash,
                    auth_epoch=current.auth_epoch,
                    created_at=datetime.now(UTC) - timedelta(days=1),
                    expires_at=current.expires_at,
                )
                for purpose, digest in (("invite", "3"), ("password_reset", "4"))
            ]
        )
        session.commit()
    before = _age_database_snapshot(f)
    call_started = datetime.now(UTC)
    result = f["fixtures"].age_pending_viewer_invitation(**f["arguments"])
    call_finished = datetime.now(UTC)
    after = _age_database_snapshot(f)
    tokens = "platform_console_tokens"
    before_tokens, after_tokens = before.pop(tokens), after.pop(tokens)
    before_token = next(row for row in before_tokens if row[0] == f["ids"]["token"])
    after_token = next(row for row in after_tokens if row[0] == f["ids"]["token"])
    assert [row for row in before_tokens if row[0] != f["ids"]["token"]] == [
        row for row in after_tokens if row[0] != f["ids"]["token"]
    ]
    assert before == after
    columns = list(
        next(
            model for model in f["models"] if model.__tablename__ == tokens
        ).__table__.columns.keys()
    )
    changed = [
        name
        for name, old, new in zip(columns, before_token, after_token, strict=True)
        if old != new
    ]
    assert changed == ["created_at"]
    aged = after_token[columns.index("created_at")].replace(tzinfo=UTC)
    assert call_started - timedelta(minutes=6) <= aged <= call_finished - timedelta(minutes=6)
    assert result["viewer_baseline"]["user_id"] == f["ids"]["viewer_user"]
    assert (
        len(result["viewer_baseline"]["membership_ids"])
        == len(result["viewer_baseline"]["audit_ids"])
        == 1
    )
    assert result["only_created_at_changed"] and result["expiry_hash_credential_epoch_preserved"]
    assert result["no_provider_calls"] and "token" not in result and "token_hash" not in result
    with pytest.raises(ValueError, match="fresh current"):
        f["fixtures"].age_pending_viewer_invitation(**f["arguments"])
    assert _age_database_snapshot(f)[tokens] == after_tokens


@pytest.mark.parametrize(
    "change",
    [
        "wrong_run",
        "wrong_manager",
        "self_target",
        "foreign_email",
        "foreign_issuer",
        "inactive_viewer",
        "active_viewer",
        "revoked_viewer",
        "removed_viewer",
        "consumed",
        "revoked_token",
        "expired",
        "stale_epoch",
        "stale_credential",
        "not_invite",
        "old_created",
        "future_created",
        "inactive_manager",
        "revoked_manager",
        "revoked_root",
        "inactive_founder",
        "wrong_csrf",
        "stale_step_up",
    ],
)
def test_invitation_age_rejects_wrong_identity_or_stale_authority_without_clock_mutation(
    invitation_age_fixture, change
):
    f = invitation_age_fixture
    from caseops_api.db.models import (
        PlatformAdminMembership,
        PlatformConsoleSession,
        PlatformConsoleToken,
        PlatformReportAdmin,
        User,
    )

    args = dict(f["arguments"])
    if change in {"wrong_run", "wrong_manager", "self_target", "wrong_csrf"}:
        field, value = {
            "wrong_run": ("run_id", str(uuid4())),
            "wrong_manager": ("manager_id", str(uuid4())),
            "self_target": ("viewer_id", f["ids"]["manager"]),
            "wrong_csrf": ("manager_csrf", "not-the-session-csrf"),
        }[change]
        args[field] = value
    else:
        now = datetime.now(UTC)
        modifications = {
            "foreign_email": (User, "viewer_user", "email", f"viewer-{uuid4()}@example.com"),
            "foreign_issuer": (
                PlatformReportAdmin,
                "viewer",
                "created_by_report_admin_id",
                f["ids"]["viewer"],
            ),
            "inactive_viewer": (User, "viewer_user", "is_active", False),
            "active_viewer": (PlatformReportAdmin, "viewer", "status", "active"),
            "revoked_viewer": (PlatformReportAdmin, "viewer", "status", "revoked"),
            "removed_viewer": (PlatformReportAdmin, "viewer", "removed_at", now),
            "consumed": (PlatformConsoleToken, "token", "consumed_at", now),
            "revoked_token": (PlatformConsoleToken, "token", "revoked_at", now),
            "expired": (PlatformConsoleToken, "token", "expires_at", now - timedelta(seconds=1)),
            "stale_epoch": (PlatformConsoleToken, "token", "auth_epoch", 9),
            "stale_credential": (PlatformConsoleToken, "token", "credential_hash", "2" * 64),
            "not_invite": (PlatformConsoleToken, "token", "purpose", "password_reset"),
            "old_created": (
                PlatformConsoleToken,
                "token",
                "created_at",
                now - timedelta(minutes=6),
            ),
            "future_created": (
                PlatformConsoleToken,
                "token",
                "created_at",
                now + timedelta(minutes=1),
            ),
            "inactive_manager": (User, "manager_user", "is_active", False),
            "revoked_manager": (PlatformReportAdmin, "manager", "status", "revoked"),
            "revoked_root": (PlatformAdminMembership, "root", "status", "revoked"),
            "inactive_founder": (User, "founder_user", "is_active", False),
            "stale_step_up": (
                PlatformConsoleSession,
                "console_session",
                "issued_at",
                now - timedelta(minutes=11),
            ),
        }
        model, key, field, value = modifications[change]
        with f["factory"]() as session:
            setattr(session.get(model, f["ids"][key]), field, value)
            session.commit()
    before = _age_database_snapshot(f)
    with pytest.raises((ValueError, HTTPException)):
        f["fixtures"].age_pending_viewer_invitation(**args)
    after = _age_database_snapshot(f)
    # Known authenticated denials retain their real minimized audit, never a clock change.
    before.pop("platform_report_audit_events")
    after.pop("platform_report_audit_events")
    assert after == before


def test_invitation_age_http_requires_all_guards_and_is_one_use_without_transport(
    harness, invitation_age_fixture, monkeypatch
):
    f = invitation_age_fixture
    closers = []
    monkeypatch.setattr(harness, "register_shutdown", closers.append)
    monkeypatch.setattr(
        harness.ConsoleMailCapture, "start", lambda _self: "http://127.0.0.1:8129/capture/fixture"
    )
    monkeypatch.setattr(harness.ConsoleMailCapture, "stop", lambda _self: None)
    app = FastAPI()
    from caseops_api.core.csrf import CSRFMiddleware
    from caseops_api.core.request_context import RequestContextMiddleware

    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestContextMiddleware)
    capture = harness.install_platform_console_emulator(app)
    capture.register(f["run"], WEB)
    capture.runs[f["run"]].update(state="ready", manager_id=f["ids"]["manager"])
    capture.receive({**message(f["run"]), "to": f"viewer-{f['run']}@example.com"})
    path = harness.PREFIX + f"/fixtures/{f['run']}/age-viewer-invitation"
    body = {"web_origin": WEB, "manager_id": f["ids"]["manager"], "viewer_id": f["ids"]["viewer"]}
    headers = {
        "Cookie": (
            f"caseops_csrf=fixture-nonce; caseops_console_csrf={f['csrf']}; "
            f"caseops_console_session={f['token']}"
        ),
        "X-CSRF-Token": "fixture-nonce",
        "X-Console-CSRF-Token": f["csrf"],
        "X-CaseOps-Automated-Test": harness.MARKER,
    }
    before = _age_database_snapshot(f)
    try:
        with TestClient(app, base_url=WEB) as client:
            for missing in (
                "X-CSRF-Token",
                "X-Console-CSRF-Token",
                "X-CaseOps-Automated-Test",
                "Cookie",
            ):
                assert (
                    client.post(
                        path,
                        json=body,
                        headers={key: value for key, value in headers.items() if key != missing},
                    ).status_code
                    == 403
                )
            assert (
                client.post(
                    path, json={**body, "created_at": "2000-01-01"}, headers=headers
                ).status_code
                == 422
            )
            assert (
                client.post(
                    path, json={**body, "manager_id": str(uuid4())}, headers=headers
                ).status_code
                == 409
            )
            assert (
                client.post(
                    path, json={**body, "web_origin": "https://caseops.ai"}, headers=headers
                ).status_code
                == 409
            )
            assert (
                client.post(
                    path.replace(f["run"], str(uuid4())), json=body, headers=headers
                ).status_code
                == 409
            )
            monkeypatch.setenv("K_SERVICE", "cloud-api")
            with pytest.raises(RuntimeError, match="cloud"):
                client.post(path, json=body, headers=headers)
            monkeypatch.delenv("K_SERVICE")
            assert _age_database_snapshot(f) == before
            with TestClient(app, base_url="http://not-loopback.example:3100") as remote:
                assert remote.post(path, json=body, headers=headers).status_code == 409
            admitted = client.post(path, json=body, headers=headers)
            assert admitted.status_code == 200
            assert admitted.json()["only_created_at_changed"] is True
            assert admitted.json()["aged_minutes"] == 6
            assert admitted.json()["viewer_baseline"] == capture.runs[f["run"]]["viewer_baseline"]
            assert client.post(path, json=body, headers=headers).status_code == 409
            assert capture.external_calls == 0 and len(capture.messages) == 1
            assert capture.server is capture.thread is None
    finally:
        closers[0]()
