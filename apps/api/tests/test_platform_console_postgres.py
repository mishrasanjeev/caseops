"""Real PostgreSQL lock, one-winner and provider-I/O boundaries for PRA-04..08."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, local
from time import monotonic, sleep

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text, update

from caseops_api.core.console_auth import CONSOLE_SESSION_COOKIE
from caseops_api.core.cookies import SESSION_COOKIE
from caseops_api.core.problem_details import ProblemHTTPException
from caseops_api.core.security import create_access_token, decode_access_token, verify_password
from caseops_api.db.models import (
    AccountSetupToken,
    Company,
    CompanyMembership,
    PlatformAdminMembership,
    PlatformConsoleDelivery,
    PlatformConsoleToken,
    PlatformReportAdmin,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import platform_console as console
from caseops_api.services.identity import get_session_context
from caseops_api.services.security import _decrypt_secret, _hotp
from tests import test_platform_console as cases
from tests.test_platform_console import report_console as report_console

__all__ = ["pytestmark", "report_console"]
pytestmark = pytest.mark.postgres


@pytest.fixture
def client(isolated_postgres_client):
    return isolated_postgres_client


def _wait_for_edge(engine, holder, waiter, future):
    deadline = monotonic() + 1
    blockers = []
    with engine.connect() as observer:
        while True:
            if future.done():
                future.result()
                pytest.fail("Revocation completed without the required lock boundary.")
            blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": waiter})
            if holder in blockers or monotonic() >= deadline:
                break
            sleep(0.01)
    assert holder in blockers


def _viewer(data):
    cases._manager(data)
    record = cases._invite(data)
    raw = cases._link(data["messages"])
    data["client"].cookies.clear()
    cases._accept(data["client"], raw)
    cases._enroll(data["client"])
    return record


@pytest.mark.parametrize("target", ["root", "manager", "issuer_user"])
def test_console_revocation_fences_are_native_and_fresh(report_console, monkeypatch, target):
    data = report_console
    _viewer(data)
    token = data["client"].cookies.get(CONSOLE_SESSION_COOKIE)
    reached, release, writer_started = Event(), Event(), Event()
    holder_pids, waiter_pids = [], []
    engine = get_engine()
    with get_session_factory()() as session:
        manager = session.get(PlatformReportAdmin, data["manager_id"])
        target_model, target_id = {
            "root": (PlatformAdminMembership, manager.root_platform_admin_id),
            "manager": (PlatformReportAdmin, manager.id),
            "issuer_user": (User, manager.user_id),
        }[target]
    original = console._root_valid if target == "root" else console._locked_admin

    def pause_root(session, root_id, *, fence=False):
        result = original(session, root_id, fence=fence)
        if fence and result and not reached.is_set():
            reached.set()
            assert release.wait(5)
        return result

    def pause_admin(session, admin_id):
        result = original(session, admin_id)
        if not reached.is_set():
            reached.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(
        console,
        "_root_valid" if target == "root" else "_locked_admin",
        pause_root if target == "root" else pause_admin,
    )

    def read():
        with get_session_factory()() as session:
            holder_pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            context = console.resolve_console_context(session, token=token)
            console.audit_report_read(session, context, "serialized-control")
            return True

    def revoke():
        with get_session_factory()() as session:
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            waiter_pids.append(session.scalar(text("SELECT pg_backend_pid()")))
            writer_started.set()
            values = {"is_active": False} if target == "issuer_user" else {"status": "revoked"}
            session.execute(
                update(target_model).where(target_model.id == target_id).values(**values)
            )
            session.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(read)
        writer = None
        try:
            if not reached.wait(2):
                if reader.done():
                    reader.result()
                pytest.fail("Console authorization never reached its exact fence.")
            writer = pool.submit(revoke)
            assert writer_started.wait(1)
            _wait_for_edge(engine, holder_pids[0], waiter_pids[0], writer)
        finally:
            release.set()
        assert reader.result(timeout=3)
        writer.result(timeout=3)
    # The in-flight read serialized before revocation, not after it. The same
    # retained cookie must now fail without changing the viewer's own identity.
    assert data["client"].get(cases.BASE + "/reports/usage").status_code == 401


@pytest.mark.parametrize("factor", ["totp", "recovery"])
def test_same_console_factor_has_exactly_one_native_winner(report_console, factor):
    data = report_console
    enrollment = cases._manager(data)
    with get_session_factory()() as session:
        admin, user = console._locked_admin(session, data["manager_id"])
        now_counter = int(datetime.now(UTC).timestamp()) // 30
        admin.last_totp_counter = now_counter - 1
        code = _hotp(_decrypt_secret(admin.encrypted_totp_secret), now_counter)
        issued = [console._issue(session, admin, user) for _ in range(2)]
        session.commit()
    recovery = enrollment.json()["recovery_codes"][0]

    def verify(item):
        with get_session_factory()() as session:
            try:
                context = console.resolve_console_context(
                    session, token=item.token, csrf=item.csrf, authenticated=False
                )
                console.verify_mfa(
                    session,
                    context,
                    code=code if factor == "totp" else None,
                    recovery_code=recovery if factor == "recovery" else None,
                )
                return 200
            except ProblemHTTPException as exc:
                session.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(verify, item) for item in issued]
        outcomes = [future.result(timeout=5) for future in futures]
    assert sorted(outcomes) == [200, 401]


def test_duplicate_mail_claim_one_send_and_revoke_during_transport(report_console, monkeypatch):
    data = report_console
    cases._manager(data)
    with get_session_factory()() as session:
        admin, user = console._locked_admin(session, data["manager_id"])
        _, raw, claim, delivery = console._new_token(session, admin, user, purpose="password_reset")
        args = dict(
            delivery_id=delivery.id,
            claim=claim,
            email=user.email,
            full_name=user.full_name,
            raw_token=raw,
            purpose="password_reset",
        )
        admin_id = admin.id
        session.commit()
    entered, release = Event(), Event()
    current = local()
    calls = []

    def provider(*args, **kwargs):
        assert not current.session.in_transaction()
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return httpx.Response(202)

    monkeypatch.setattr(console.httpx, "post", provider)

    def send():
        with get_session_factory()() as session:
            current.session = session
            return console._send_claim(session, **args)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send)
        try:
            if not entered.wait(2):
                if first.done():
                    first.result()
                pytest.fail("Mail never reached its admitted deterministic transport.")
            second = pool.submit(send)
            assert second.result(timeout=2) == "outcome_unknown"
            with get_session_factory()() as session:
                session.execute(text("SET LOCAL lock_timeout = '500ms'"))
                session.execute(
                    update(PlatformReportAdmin)
                    .where(PlatformReportAdmin.id == admin_id)
                    .values(status="revoked")
                )
                session.commit()
        finally:
            release.set()
        assert first.result(timeout=3) == "accepted"
    assert calls == [1]
    with get_session_factory()() as session:
        with pytest.raises(ProblemHTTPException):
            console.complete_password_reset(session, token=raw, password=cases.PASSWORD)


def test_one_manager_constraint_on_postgres(report_console):
    cases.test_one_unrevoked_manager_constraint_is_native(report_console)


@pytest.mark.parametrize("first", ["accept", "revoke"])
def test_invitation_accept_and_revoke_serialize_on_postgres(report_console, monkeypatch, first):
    data = report_console
    cases._manager(data)
    record = cases._invite(data)
    raw = cases._link(data["messages"])
    manager_token = data["client"].cookies.get(CONSOLE_SESSION_COOKIE)
    reached, release, second_started = Event(), Event(), Event()
    pids = {}
    real_locked, real_audit = console._locked_admin, console._audit

    def pause_accept(session, admin_id):
        result = real_locked(session, admin_id)
        if first == "accept" and admin_id == record["id"] and not reached.is_set():
            reached.set()
            assert release.wait(5)
        return result

    def pause_revoke(session, admin, action, **kwargs):
        real_audit(session, admin, action, **kwargs)
        if first == "revoke" and action == "console.revoked" and not reached.is_set():
            reached.set()
            assert release.wait(5)

    monkeypatch.setattr(console, "_locked_admin", pause_accept)
    monkeypatch.setattr(console, "_audit", pause_revoke)

    def operation(kind):
        with get_session_factory()() as session:
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            pids[kind] = session.scalar(text("SELECT pg_backend_pid()"))
            if kind != first:
                second_started.set()
            try:
                if kind == "accept":
                    issued = console.complete_invitation(
                        session, token=raw, password=cases.PASSWORD, full_name="Viewer"
                    )
                    return 200, issued.token
                context = console.resolve_console_context(
                    session, token=manager_token, manager=True, step_up=True
                )
                result = console.revoke(
                    session, context, admin_id=record["id"], reason="Access ended"
                )
                assert result.status == "revoked"
                return 200, None
            except ProblemHTTPException as exc:
                session.rollback()
                return exc.status_code, None

    second = "revoke" if first == "accept" else "accept"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(operation, first)
        try:
            if not reached.wait(2):
                if first_future.done():
                    first_future.result()
                pytest.fail("Invitation operation did not reach its exact native fence.")
            second_future = pool.submit(operation, second)
            assert second_started.wait(1)
            _wait_for_edge(get_engine(), pids[first], pids[second], second_future)
        finally:
            release.set()
        outcomes = {first: first_future.result(timeout=3), second: second_future.result(timeout=3)}
    assert outcomes["revoke"][0] == 200
    assert outcomes["accept"][0] == (200 if first == "accept" else 401)
    with get_session_factory()() as session:
        assert session.get(PlatformReportAdmin, record["id"]).status == "revoked"
        if outcomes["accept"][1]:
            with pytest.raises(ProblemHTTPException):
                console.resolve_console_context(
                    session, token=outcomes["accept"][1], authenticated=False
                )


@pytest.mark.parametrize("realm", ["console", "employee"])
def test_shared_credential_reset_revokes_two_tenants_and_console_on_postgres(report_console, realm):
    data = report_console
    client = data["client"]
    cases._manager(data)
    cases._invite(data, "owner@asterlegal.in")
    client.cookies.clear()
    response = client.post(
        cases.BASE + "/auth/invitations/complete",
        json={
            "token": cases._link(data["messages"]),
            "password": "FoundersPass123!",
            "full_name": "Ignored",
        },
    )
    assert response.status_code == 200
    cases._enroll(client)
    old_console_token = client.cookies.get(CONSOLE_SESSION_COOKIE)
    user_id = data["tenant"]["user"]["id"]
    with get_session_factory()() as session:
        company = Company(
            name="Second Real Tenant Fixture",
            slug="second-real-tenant",
            company_type="law_firm",
            tenant_key="second-real-tenant",
        )
        session.add(company)
        session.flush()
        membership = CompanyMembership(company_id=company.id, user_id=user_id, role="owner")
        session.add(membership)
        session.flush()
        second_token = create_access_token(
            user_id=user_id, company_id=company.id, membership_id=membership.id, role="owner"
        )
        session.commit()
    old_tenant_tokens = [data["tenant"]["access_token"], second_token]
    for token in old_tenant_tokens:
        assert client.get("/api/auth/me", headers=cases.auth_headers(token)).status_code == 200
    if realm == "console":
        response = client.post(
            cases.BASE + "/auth/password-reset/start", json={"email": "owner@asterlegal.in"}
        )
        assert response.json() == {"status": "accepted"}
        response = client.post(
            cases.BASE + "/auth/password-reset/complete",
            json={
                "token": cases._link(data["messages"]),
                "password": "NewSharedPassword123!",
            },
        )
    else:
        raw = "isolated-native-employee-reset-token-20261020"
        with get_session_factory()() as session:
            session.add(
                AccountSetupToken(
                    company_id=data["tenant"]["company"]["id"],
                    membership_id=data["tenant"]["membership"]["id"],
                    user_id=user_id,
                    purpose="password_reset",
                    token_hash=console._digest(raw),
                    expires_at=datetime.now(UTC) + timedelta(minutes=10),
                )
            )
            session.commit()
        response = client.post(
            "/api/auth/password-reset/complete",
            json={"token": raw, "password": "NewSharedPassword123!"},
        )
    assert response.status_code == 200
    with get_session_factory()() as session:
        user = session.get(User, user_id)
        assert user.sessions_valid_after is not None
        assert verify_password("NewSharedPassword123!", user.password_hash)
        for token in old_tenant_tokens:
            claims = decode_access_token(token)
            issued_at = float(claims["issued_at_precise"])
            assert issued_at < user.sessions_valid_after.timestamp()
            with pytest.raises(HTTPException) as denied:
                get_session_context(session, claims["membership_id"], token_issued_at=issued_at)
            assert denied.value.status_code == 401
    if realm == "employee":
        # Production intentionally prefers its fresh cookie over a Bearer
        # header. Prove that control, then isolate the stale SDK credential.
        fresh_token = response.json()["access_token"]
        assert client.cookies.get(SESSION_COOKIE) == fresh_token
        control = client.get("/api/auth/me", headers=cases.auth_headers(old_tenant_tokens[1]))
        assert control.status_code == 200
        assert control.json()["company"]["id"] == data["tenant"]["company"]["id"]
        assert (
            decode_access_token(old_tenant_tokens[1])["company_id"]
            != control.json()["company"]["id"]
        )
    client.cookies.clear()
    if realm == "employee":
        fresh = client.get("/api/auth/me", headers=cases.auth_headers(fresh_token))
        assert fresh.status_code == 200
        assert fresh.json()["membership"]["id"] == data["tenant"]["membership"]["id"]
    for token in old_tenant_tokens:
        assert client.get("/api/auth/me", headers=cases.auth_headers(token)).status_code == 401
        assert (
            client.post("/api/auth/refresh", headers=cases.auth_headers(token)).status_code == 401
        )
    client.cookies.clear()
    client.cookies.set(CONSOLE_SESSION_COOKIE, old_console_token, path=cases.BASE)
    assert client.get(cases.BASE + "/auth/session").status_code == 401


@pytest.mark.parametrize("reader", ["legacy", "console"])
def test_report_mrr_interval_reconciliation_on_postgres(report_console, reader):
    cases.test_report_mrr_matches_each_subscription_interval_and_excludes_cancelled(
        report_console, reader
    )


@pytest.mark.parametrize(
    ("paid_at_present", "offset_minutes"),
    [(True, 0), (True, 330), (False, 0)],
    ids=["utc", "non-utc-aware", "null-payment-date"],
)
def test_persisted_report_dates_are_utc_in_postgres_http_json(
    report_console, paid_at_present, offset_minutes,
):
    cases._assert_persisted_report_date_contract(
        report_console, paid_at_present=paid_at_present, offset_minutes=offset_minutes,
    )


@pytest.mark.parametrize("overlap", ["before_commit", "during_transport"])
def test_concurrent_invites_keep_one_grant_token_and_send(report_console, monkeypatch, overlap):
    data = report_console
    cases._manager(data)
    manager_token = data["client"].cookies.get(CONSOLE_SESSION_COOKIE)
    entered, release, second_started = Event(), Event(), Event()
    current = local()
    pids, calls = {}, []
    real_audit = console._audit

    def paused_audit(session, admin, action, **kwargs):
        real_audit(session, admin, action, **kwargs)
        if overlap == "before_commit" and action == "console.invited":
            entered.set()
            assert release.wait(5)

    def provider(url, *, json, **kwargs):
        assert not current.session.in_transaction()
        calls.append(json)
        if overlap == "during_transport":
            entered.set()
            assert release.wait(5)
        return httpx.Response(202)

    monkeypatch.setattr(console, "_audit", paused_audit)
    monkeypatch.setattr(console.httpx, "post", provider)

    def invite(index):
        with get_session_factory()() as session:
            current.session = session
            session.execute(text("SET LOCAL lock_timeout = '2s'"))
            pids[index] = session.scalar(text("SELECT pg_backend_pid()"))
            if index == 2:
                second_started.set()
            context = console.resolve_console_context(
                session, token=manager_token, manager=True, step_up=True,
            )
            return console.invite(
                session, context, email="concurrent@console.example", full_name="Concurrent Viewer",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invite, 1)
        try:
            if not entered.wait(2):
                if first.done():
                    first.result()
                pytest.fail("First invite did not reach its exact native overlap boundary.")
            second = pool.submit(invite, 2)
            assert second_started.wait(1)
            if overlap == "before_commit":
                _wait_for_edge(get_engine(), pids[1], pids[2], second)
            else:
                replay = second.result(timeout=2)
                assert replay.delivery_status == "pending"
        finally:
            release.set()
        initial, replay = first.result(timeout=3), second.result(timeout=3)
    assert initial.admin.id == replay.admin.id
    assert initial.delivery_status == "accepted"
    assert replay.delivery_status in {"pending", "accepted"}
    assert len(calls) == 1
    with get_session_factory()() as session:
        admin_id = initial.admin.id
        assert session.scalar(select(func.count(PlatformReportAdmin.id)).where(
            PlatformReportAdmin.id == admin_id,
        )) == 1
        assert session.get(PlatformReportAdmin, admin_id).auth_epoch == 1
        assert session.scalar(select(func.count(PlatformConsoleToken.id)).where(
            PlatformConsoleToken.report_admin_id == admin_id,
        )) == 1
        assert session.scalar(select(func.count(PlatformConsoleDelivery.id)).join(
            PlatformConsoleToken, PlatformConsoleToken.id == PlatformConsoleDelivery.token_id,
        ).where(PlatformConsoleToken.report_admin_id == admin_id)) == 1
    data["client"].cookies.clear()
    cases._accept(data["client"], cases._link(calls))
