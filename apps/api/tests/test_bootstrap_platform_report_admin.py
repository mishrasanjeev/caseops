from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from email_validator import deliverability
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.db.base import Base
from caseops_api.db.models import (
    PlatformAdminMembership,
    PlatformConsoleDelivery,
    PlatformConsoleToken,
    PlatformReportAdmin,
    PlatformReportAuditEvent,
    User,
)
from caseops_api.db.session import CaseOpsSession
from caseops_api.schemas.platform_console import ConsoleAdminRecord, ConsoleInvitationResponse
from caseops_api.scripts import bootstrap_platform_report_admin as cli
from tests.sql_observation import is_read_only_select

SHA = "a" * 40
ROOT_ID = "00000000-0000-4000-8000-000000000001"
EMAIL = "sanjeev@orchestrum.in"
NAME = "Report Manager"
PRIVATE = "private-token-password-mfa-provider-body"


def _args(*extra):
    return [
        "--expected-release-sha",
        SHA,
        "--root-platform-admin-id",
        ROOT_ID,
        "--email",
        EMAIL,
        *extra,
    ]


def _record():
    return ConsoleAdminRecord(
        id=str(uuid4()),
        email=EMAIL,
        full_name=NAME,
        role="manager",
        status="pending",
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        User,
        PlatformAdminMembership,
        PlatformReportAdmin,
        PlatformConsoleToken,
        PlatformConsoleDelivery,
        PlatformReportAuditEvent,
    ]
    Base.metadata.create_all(engine, tables=[model.__table__ for model in tables])
    factory = sessionmaker(
        bind=engine, class_=CaseOpsSession, autoflush=False, expire_on_commit=False
    )
    with factory() as session:
        root_user = User(email="root@example.com", full_name="Root", password_hash=PRIVATE)
        target = User(email=EMAIL, full_name=NAME, password_hash="existing-password-must-survive")
        session.add_all([root_user, target])
        session.flush()
        session.add(PlatformAdminMembership(id=ROOT_ID, user_id=root_user.id))
        session.commit()
    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(release_sha=SHA))
    monkeypatch.setattr(cli, "get_session_factory", lambda: factory)
    yield factory, engine
    engine.dispose()


def _forbidden(*_args, **_kwargs):
    pytest.fail("Operation was not admitted")


def test_invalid_arguments_are_private_and_precede_settings_and_database(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", _forbidden)
    monkeypatch.setattr(cli, "get_session_factory", _forbidden)
    monkeypatch.setattr(deliverability, "validate_email_deliverability", _forbidden)
    invalid = [[], _args("--bootstrap"), _args("--unexpected", PRIVATE)]
    for flag, value in (
        ("--expected-release-sha", PRIVATE),
        ("--expected-release-sha", SHA + "\n"),
        ("--root-platform-admin-id", PRIVATE),
        ("--root-platform-admin-id", "{" + ROOT_ID + "}"),
        ("--email", PRIVATE),
        ("--email", "Manager <" + EMAIL + ">"),
        ("--email", EMAIL + "\r\nBcc:" + PRIVATE),
        ("--email", "x" * 321),
    ):
        args = _args()
        args[args.index(flag) + 1] = value
        invalid.append(args)
    invalid.extend(
        _args("--bootstrap", "--full-name", name) for name in (" ", "x" * 256, PRIVATE + "\x00")
    )
    for args in invalid:
        assert cli.main(args) == 2
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {
            "status": "invalid_arguments",
            "mutation_attempted": False,
        }
        assert captured.err == "" and PRIVATE not in captured.out


def test_wrong_or_unset_release_never_opens_factory(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_session_factory", _forbidden)
    for release in (None, "b" * 40, SHA.upper(), PRIVATE):
        monkeypatch.setattr(
            cli, "get_settings", lambda release=release: SimpleNamespace(release_sha=release)
        )
        assert cli.main(_args("--bootstrap", "--full-name", NAME)) == 2
        assert json.loads(capsys.readouterr().out)["status"] == "release_mismatch"


def test_configuration_error_is_sanitized_before_factory(monkeypatch, capsys):
    def broken():
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(cli, "get_settings", broken)
    monkeypatch.setattr(cli, "get_session_factory", _forbidden)
    assert cli.main(_args()) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "invalid_configuration"
    assert PRIVATE not in output.out and output.err == ""


def test_default_inspect_is_four_bounded_selects_without_mutations(database, monkeypatch, capsys):
    factory, engine = database
    now = datetime.now(UTC)
    with factory() as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        grant = PlatformReportAdmin(user_id=user.id, root_platform_admin_id=ROOT_ID, role="manager")
        session.add(grant)
        session.flush()
        token = PlatformConsoleToken(
            report_admin_id=grant.id,
            token_hash=PRIVATE,
            purpose="invite",
            auth_epoch=1,
            credential_hash=PRIVATE,
            expires_at=now + timedelta(minutes=30),
        )
        session.add(token)
        session.flush()
        session.add(
            PlatformConsoleDelivery(
                token_id=token.id,
                status="accepted",
                claim_hash=PRIVATE,
                claim_expires_at=now + timedelta(minutes=2),
                provider_message_id=PRIVATE,
                error_code=PRIVATE,
            )
        )
        session.commit()
    statements = []
    cursor_statements = []

    def observe(_connection, clause, _multiparams, _params, _options):
        statements.append(clause)

    def observe_cursor(_connection, _cursor, statement, _parameters, _context, _many):
        cursor_statements.append(statement)

    monkeypatch.setattr(cli, "_bootstrap", _forbidden)
    event.listen(engine, "before_execute", observe)
    event.listen(engine, "before_cursor_execute", observe_cursor)
    try:
        assert cli.main(_args()) == 0
    finally:
        event.remove(engine, "before_execute", observe)
        event.remove(engine, "before_cursor_execute", observe_cursor)
    assert len(statements) == 4 and all(is_read_only_select(query) for query in statements)
    assert len(cursor_statements) == len(statements)
    assert all(query._limit_clause.value == 1 for query in statements)
    projected = " ".join(str(query) for query in statements)
    assert "password_hash" not in projected and "token_hash" not in projected
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result["mutation_attempted"] is False and result["delivery_status"] == "accepted"
    assert result["report_grant"]["root_matches"] is True
    assert result["inbox_delivery_confirmed"] is False
    assert PRIVATE not in output.out and EMAIL not in output.out and output.err == ""


def test_inspect_missing_user_has_no_bootstrap_and_only_two_selects(database, monkeypatch, capsys):
    _factory, engine = database
    statements = []
    cursor_statements = []

    def observe(_connection, clause, _multiparams, _params, _options):
        statements.append(clause)

    def observe_cursor(_connection, _cursor, statement, _parameters, _context, _many):
        cursor_statements.append(statement)

    monkeypatch.setattr(cli, "_bootstrap", _forbidden)
    args = _args("--inspect")
    args[args.index("--email") + 1] = "absent@example.com"
    event.listen(engine, "before_execute", observe)
    event.listen(engine, "before_cursor_execute", observe_cursor)
    try:
        assert cli.main(args) == 0
    finally:
        event.remove(engine, "before_execute", observe)
        event.remove(engine, "before_cursor_execute", observe_cursor)
    assert len(statements) == 2 and all(is_read_only_select(query) for query in statements)
    assert len(cursor_statements) == len(statements)
    result = json.loads(capsys.readouterr().out)
    assert result["user"]["found"] is False and result["report_grant"]["found"] is False
    assert result["delivery_status"] == "not_found"


def test_explicit_bootstrap_delegates_exact_values_once(database, monkeypatch, capsys):
    calls = []

    def bootstrap(session, **kwargs):
        calls.append((session, kwargs))
        return ConsoleInvitationResponse(admin=_record(), delivery_status="accepted")

    monkeypatch.setattr(cli, "_bootstrap", bootstrap)
    assert cli.main(_args("--bootstrap", "--full-name", NAME)) == 0
    assert len(calls) == 1 and isinstance(calls[0][0], CaseOpsSession)
    assert calls[0][1] == {"root_platform_admin_id": ROOT_ID, "email": EMAIL, "full_name": NAME}
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "accepted" and result["inbox_delivery_confirmed"] is False
    assert result["automatic_retry"] is False


def test_real_service_replay_preserves_existing_password_and_sends_once(
    database, monkeypatch, capsys
):
    from caseops_api.services import platform_console as service

    factory, _engine = database
    calls = []
    monkeypatch.setattr(
        service, "_root_valid", lambda _session, root_id, **_kwargs: root_id == ROOT_ID
    )

    def send(session, **kwargs):
        assert not session.in_transaction()
        calls.append(kwargs)
        return "accepted"

    monkeypatch.setattr(service, "_send_claim", send)
    for expected in ("accepted", "existing_grant"):
        assert cli.main(_args("--bootstrap", "--full-name", NAME)) == 0
        output = capsys.readouterr()
        assert json.loads(output.out)["status"] == expected and PRIVATE not in output.out
    assert len(calls) == 1 and calls[0]["email"] == EMAIL
    with factory() as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        assert user.password_hash == "existing-password-must-survive"
        assert len(list(session.scalars(select(PlatformReportAdmin)))) == 1
        assert len(list(session.scalars(select(PlatformConsoleDelivery)))) == 1


def test_service_known_and_unknown_exceptions_have_unknown_private_outcomes(
    database,
    monkeypatch,
    capsys,
):
    for error in (
        ProblemHTTPException(403, problem_type=PRIVATE, detail=PRIVATE),
        ProblemHTTPException(409, problem_type=PRIVATE, detail=PRIVATE),
        OSError(PRIVATE),
        RuntimeError(PRIVATE),
    ):
        calls = []

        def fail(_session, _calls=calls, _error=error, **_kwargs):
            _calls.append(True)
            raise _error

        monkeypatch.setattr(cli, "_bootstrap", fail)
        assert cli.main(_args("--bootstrap", "--full-name", NAME)) == 1
        output = capsys.readouterr()
        assert json.loads(output.out) == {
            "status": "outcome_unknown",
            "mutation_attempted": True,
            "automatic_retry": False,
            "next_action": "inspect",
        }
        assert len(calls) == 1 and PRIVATE not in output.out and output.err == ""

    class ClosingFailure:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            raise RuntimeError(PRIVATE)

    monkeypatch.setattr(cli, "get_session_factory", lambda: ClosingFailure)
    monkeypatch.setattr(
        cli,
        "_bootstrap",
        lambda _session, **_kwargs: ConsoleInvitationResponse(
            admin=_record(),
            delivery_status="accepted",
        ),
    )
    assert cli.main(_args("--bootstrap", "--full-name", NAME)) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "outcome_unknown"
    assert '"status": "accepted"' not in output.out
    assert PRIVATE not in output.out and output.err == ""


def test_failed_or_uncertain_delivery_is_nonzero_without_resend(database, monkeypatch, capsys):
    for status in ("failed", "pending", "outcome_unknown"):
        calls = []

        def bootstrap(_session, _calls=calls, _status=status, **_kwargs):
            _calls.append(True)
            return ConsoleInvitationResponse(admin=_record(), delivery_status=_status)

        monkeypatch.setattr(cli, "_bootstrap", bootstrap)
        assert cli.main(_args("--bootstrap", "--full-name", NAME)) == 1
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == status and result["automatic_retry"] is False
        assert result["next_action"] == "inspect" and len(calls) == 1


def test_python_module_wrong_release_is_private_and_nonmutating():
    env = {key: value for key, value in os.environ.items() if not key.startswith("CASEOPS_")}
    env.update(
        {
            "CASEOPS_ENV": "local",
            "CASEOPS_RELEASE_SHA": "b" * 40,
            "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "CASEOPS_AUTO_MIGRATE": "false",
            "CASEOPS_AUTH_SECRET": "offline-bootstrap-secret-at-least-32-bytes",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "caseops_api.scripts.bootstrap_platform_report_admin",
            *_args(),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"status": "release_mismatch", "mutation_attempted": False}
    assert result.stderr == "" and PRIVATE not in result.stdout
