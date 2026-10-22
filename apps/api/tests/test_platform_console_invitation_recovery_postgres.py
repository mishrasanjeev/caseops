"""PRA-10..12 native lock/transport races on independent PostgreSQL fixtures."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from caseops_api.core.automated_test_context import (
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.console_auth import CONSOLE_CSRF_COOKIE, CONSOLE_SESSION_COOKIE
from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.core.security import hash_password
from caseops_api.db.models import (
    PlatformAdminMembership,
    PlatformConsoleToken,
    PlatformReportAdmin,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import platform_console as console
from tests import test_platform_console as old
from tests.test_platform_console import report_console as report_console
from tests.test_platform_console_postgres import _wait_for_edge

pytestmark = pytest.mark.postgres
__all__ = ["report_console", "pytestmark"]


@pytest.fixture
def client(isolated_postgres_client):
    isolated_postgres_client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    return isolated_postgres_client


def test_independent_live_invitation_issuer_is_not_admissible(
    report_console, record_property
):
    data = report_console
    old._manager(data)
    message_count = len(data["messages"])
    with get_session_factory()() as session:
        root_ids = list(session.scalars(select(PlatformAdminMembership.id)))
        grant_ids = list(session.scalars(select(PlatformReportAdmin.id)))
        other = User(
            email="other-root@recovery.example", full_name="Unprivileged identity",
            password_hash=hash_password(old.PASSWORD),
        )
        session.add(other)
        session.commit()
        other_id = other.id
        session.add(PlatformAdminMembership(user_id=other_id, status="active"))
        with pytest.raises(IntegrityError) as rejected:
            session.flush()
        assert rejected.value.orig.diag.constraint_name == (
            "uq_platform_admin_memberships_one_active"
        )
        session.rollback()
        assert list(session.scalars(select(PlatformAdminMembership.id))) == root_ids

        retired = PlatformAdminMembership(user_id=other_id, status="revoked")
        session.add(retired)
        session.commit()
        assert console._root_valid(session, retired.id) is False
        with pytest.raises(ProblemHTTPException) as denied:
            console.bootstrap_report_manager(
                session, root_platform_admin_id=retired.id,
                email="unadmitted-manager@recovery.example", full_name="Not admitted",
            )
        assert denied.value.status_code == 403
        session.rollback()
        assert list(session.scalars(select(PlatformReportAdmin.id))) == grant_ids
        assert session.scalar(select(User.id).where(
            User.email == "unadmitted-manager@recovery.example"
        )) is None
    assert len(data["messages"]) == message_count
    record_property("second_live_root_rejected_by_native_unique_index", True)
    record_property("retired_root_cannot_admit_another_issuer", True)


@pytest.mark.parametrize("first", ["accept", "remove"])
def test_old_invitation_accept_and_remove_have_one_serial_order(
    report_console, monkeypatch, record_property, first
):
    data = report_console
    old._manager(data)
    record = old._invite(data)
    raw = old._link(data["messages"])
    token = data["client"].cookies.get(CONSOLE_SESSION_COOKIE)
    csrf = data["client"].cookies.get(CONSOLE_CSRF_COOKIE)
    reached, release = Event(), Event()
    pids = {}
    audit = console._audit

    def barrier(session, admin, action, **kwargs):
        audit(session, admin, action, **kwargs)
        expected = "console.removed" if first == "remove" else "console.invitation_completed"
        if action == expected:
            reached.set()
            assert release.wait(5)

    monkeypatch.setattr(console, "_audit", barrier)

    def operation(kind):
        with get_session_factory()() as session:
            pids[kind] = session.scalar(text("SELECT pg_backend_pid()"))
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            try:
                if kind == "accept":
                    console.complete_invitation(session, token=raw, password=old.PASSWORD,
                                                full_name="Viewer")
                else:
                    context = console.resolve_console_context(
                        session, token=token, csrf=csrf, manager=True, step_up=True
                    )
                    console.remove(session, context, admin_id=record["id"],
                                   reason="Synthetic native removal", expected_version=1)
                return 200
            except ProblemHTTPException as exc:
                session.rollback()
                return exc.status_code

    second = "remove" if first == "accept" else "accept"
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(operation, first)
        try:
            assert reached.wait(3)
            b = pool.submit(operation, second)
            deadline = Event()
            # The helper observes the actual PostgreSQL blocker, not elapsed time.
            for _ in range(100):
                if second in pids:
                    break
                deadline.wait(0.01)
            _wait_for_edge(get_engine(), pids[first], pids[second], b)
            record_property("actual_lock_edge", f"{pids[first]}->{pids[second]}")
        finally:
            release.set()
        assert a.result(timeout=5) == 200
        assert b.result(timeout=5) == (200 if first == "accept" else 401)
    with get_session_factory()() as session:
        target = session.get(PlatformReportAdmin, record["id"])
        assert target.status == "revoked" and target.removed_at is not None
        assert target.auth_epoch == 2


@pytest.mark.parametrize("second", ["remove", "old_accept"])
def test_reinvite_fences_old_admission_after_actual_lock_wait(report_console, monkeypatch, second):
    data = report_console
    old._manager(data)
    record = old._invite(data)
    old_token = old._link(data["messages"])
    token = data["client"].cookies.get(CONSOLE_SESSION_COOKIE)
    csrf = data["client"].cookies.get(CONSOLE_CSRF_COOKIE)
    response = data["client"].post(old.BASE + f"/admins/{record['id']}/revoke",
        json={"reason": "Never opened", "expected_version": 1}, headers=old._csrf(data["client"]))
    assert response.status_code == 200
    reached, release, waiting = Event(), Event(), Event()
    pids = {}
    audit = console._audit

    def barrier(session, admin, action, **kwargs):
        audit(session, admin, action, **kwargs)
        if action == "console.reinvited":
            reached.set()
            assert release.wait(5)

    monkeypatch.setattr(console, "_audit", barrier)

    def operation(kind):
        marker = set_automated_test_request("no-paid-providers")
        try:
            with get_session_factory()() as session:
                pids[kind] = session.scalar(text("SELECT pg_backend_pid()"))
                if kind != "reinvite":
                    waiting.set()
                try:
                    if kind == "old_accept":
                        console.complete_invitation(session, token=old_token,
                            password=old.PASSWORD, full_name="Viewer")
                        return 200
                    context = console.resolve_console_context(
                        session, token=token, csrf=csrf, manager=True, step_up=True
                    )
                    if kind == "reinvite":
                        console.invite(session, context, email=record["email"], full_name="Viewer",
                                       reinvite_revoked=True, automated=True)
                    else:
                        console.remove(session, context, admin_id=record["id"],
                                       reason="Stale old admission", expected_version=2)
                    return 200
                except ProblemHTTPException as exc:
                    session.rollback()
                    return exc.status_code
        finally:
            reset_automated_test_request(marker)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(operation, "reinvite")
        try:
            assert reached.wait(3)
            b = pool.submit(operation, second)
            assert waiting.wait(1)
            _wait_for_edge(get_engine(), pids["reinvite"], pids[second], b)
        finally:
            release.set()
        assert a.result(timeout=5) == 200
        assert b.result(timeout=5) == (409 if second == "remove" else 401)
    with get_session_factory()() as session:
        target = session.get(PlatformReportAdmin, record["id"])
        assert target.status == "pending" and target.auth_epoch == 3
        assert target.removed_at is None


@pytest.mark.parametrize("outcome", ["accepted", "outcome_unknown"])
def test_actor_revocation_during_transport_cannot_authorize_reinvite(
    report_console, monkeypatch, outcome
):
    data = report_console
    old._manager(data)
    record = old._invite(data)
    assert data["client"].post(old.BASE + f"/admins/{record['id']}/revoke", json={
        "reason": "Never opened", "expected_version": 1}, headers=old._csrf(data["client"])
    ).status_code == 200
    calls = []

    def transport(url, **kwargs):
        assert url == "http://127.0.0.1:8129/messages"
        assert paid_providers_blocked_for_request()
        assert not data["transport_session"][0].in_transaction()
        with get_session_factory()() as writer:
            writer.execute(text("SET LOCAL lock_timeout = '1s'"))
            writer.execute(update(PlatformReportAdmin).where(
                PlatformReportAdmin.id == data["manager_id"]
            ).values(status="revoked", auth_epoch=PlatformReportAdmin.auth_epoch + 1))
            writer.commit()
        calls.append(kwargs["json"])
        if outcome == "outcome_unknown":
            raise httpx.ReadTimeout("Synthetic ambiguous send")
        return httpx.Response(202)

    monkeypatch.setattr(console.httpx, "post", transport)
    response = data["client"].post(old.BASE + "/admins/invitations", json={
        "email": record["email"], "full_name": "Viewer", "reinvite_revoked": True
    }, headers=old._csrf(data["client"]))
    assert response.status_code == 200 and response.json()["delivery_status"] == outcome
    assert len(calls) == 1
    new_token = old._link(calls)
    data["client"].cookies.clear()
    assert data["client"].post(old.BASE + "/auth/invitations/complete", json={
        "token": new_token, "password": old.PASSWORD, "full_name": "Viewer"
    }).status_code == 401
    with get_session_factory()() as session:
        assert session.scalar(select(PlatformConsoleToken).where(
            PlatformConsoleToken.token_hash == console._digest(new_token)
        )).consumed_at is None


@pytest.mark.parametrize("existing_user", [False, True])
def test_first_invites_serialize_on_authorized_issuer_without_duplicate_user_or_grant(
    report_console, monkeypatch, existing_user
):
    data = report_console
    old._manager(data)
    email = "concurrent-first@recovery.example"
    if existing_user:
        with get_session_factory()() as session:
            session.add(User(
                email=email, full_name="Existing", password_hash=hash_password(old.PASSWORD)
            ))
            session.commit()
    token = data["client"].cookies.get(CONSOLE_SESSION_COOKIE)
    csrf = data["client"].cookies.get(CONSOLE_CSRF_COOKIE)
    reached, release, waiting = Event(), Event(), Event()
    pids = {}
    audit = console._audit
    count = len(data["messages"])

    def barrier(session, admin, action, **kwargs):
        audit(session, admin, action, **kwargs)
        if action == "console.invited":
            reached.set()
            assert release.wait(5)

    monkeypatch.setattr(console, "_audit", barrier)

    def invite(number):
        marker = set_automated_test_request("no-paid-providers")
        try:
            with get_session_factory()() as session:
                pids[number] = session.scalar(text("SELECT pg_backend_pid()"))
                if number == 2:
                    waiting.set()
                context = console.resolve_console_context(
                    session, token=token, csrf=csrf, manager=True, step_up=True
                )
                return console.invite(session, context, email=email, full_name="First Invite",
                                      automated=True)
        finally:
            reset_automated_test_request(marker)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(invite, 1)
        try:
            assert reached.wait(3)
            b = pool.submit(invite, 2)
            assert waiting.wait(1)
            _wait_for_edge(get_engine(), pids[1], pids[2], b)
        finally:
            release.set()
        first, second = a.result(timeout=5), b.result(timeout=5)
    assert first.admin.id == second.admin.id
    assert first.delivery_status == "accepted"
    assert second.delivery_status in {"pending", "accepted"}
    assert len(data["messages"]) == count + 1
    with get_session_factory()() as session:
        users = list(session.scalars(select(User).where(User.email == email)))
        assert len(users) == 1
        grants = list(session.scalars(select(PlatformReportAdmin).where(
            PlatformReportAdmin.user_id == users[0].id
        )))
        assert len(grants) == 1 and grants[0].auth_epoch == 1
        assert grants[0].initializes_password is not existing_user
