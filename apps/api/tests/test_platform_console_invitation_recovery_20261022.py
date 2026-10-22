"""PRA-10..12: explicit, identity-preserving, versioned report-grant recovery."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import paid_providers_blocked_for_request
from caseops_api.core.console_auth import CONSOLE_CSRF_COOKIE, CONSOLE_SESSION_COOKIE
from caseops_api.core.security import hash_password
from caseops_api.db.models import (
    CompanyMembership,
    PlatformAdminMembership,
    PlatformConsoleSession,
    PlatformConsoleToken,
    PlatformReportAdmin,
    PlatformReportAuditEvent,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services import platform_console as console
from tests import test_platform_console as old


@pytest.fixture(params=[
    "client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres),
])
def recovery_console(request, monkeypatch):
    client = request.getfixturevalue(request.param)
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    data = old.report_console.__wrapped__(client, monkeypatch)
    old._manager(data)
    return data


def _version(admin_id):
    with get_session_factory()() as session:
        return session.get(PlatformReportAdmin, admin_id).auth_epoch


def _command(data, record, action, *, version=None, headers=None):
    payload = {"expected_version": _version(record["id"]) if version is None else version}
    if action in {"revoke", "remove"}:
        payload["reason"] = "Explicit synthetic report access change"
    return data["client"].post(old.BASE + f"/admins/{record['id']}/{action}", json=payload,
        headers=old._csrf(data["client"]) if headers is None else headers)


def _invite(data, record, explicit=True):
    return data["client"].post(old.BASE + "/admins/invitations", headers=old._csrf(data["client"]),
        json={"email": record["email"], "full_name": record["full_name"],
              "reinvite_revoked": explicit})


def _identity(admin_id):
    with get_session_factory()() as session:
        admin = session.get(PlatformReportAdmin, admin_id)
        user = session.get(User, admin.user_id)
        return {"user": dict(session.execute(select(User.__table__).where(User.id == user.id))
                             .mappings().one()),
                "memberships": [dict(r) for r in session.execute(select(CompanyMembership.__table__)
                    .where(CompanyMembership.user_id == user.id)).mappings()],
                "initializes_password": admin.initializes_password}


def test_never_opened_revoke_then_same_email(recovery_console):
    data = recovery_console
    record = old._invite(data)
    original = old._link(data["messages"])
    before = _identity(record["id"])
    assert before["initializes_password"] is True
    first = _version(record["id"])
    assert _command(data, record, "revoke").status_code == 200
    withdrawn = _version(record["id"])
    assert withdrawn > first
    managed = data["client"].get(old.BASE + "/admins/manage").json()["items"]
    assert next(row for row in managed if row["id"] == record["id"])["can_manage"] is True
    assert _invite(data, record, explicit=False).status_code == 409
    response = _invite(data, record)
    assert response.status_code == 200
    assert response.json()["admin"]["id"] == record["id"]
    assert response.json()["admin"]["status"] == "pending"
    assert _identity(record["id"]) == before
    assert _version(record["id"]) > withdrawn
    current = old._link(data["messages"])
    assert current != original
    snapshot, count = old._invitation_snapshot(record["id"]), len(data["messages"])
    assert _invite(data, record).json() == response.json()
    assert old._invitation_snapshot(record["id"]) == snapshot
    assert len(data["messages"]) == count
    data["client"].cookies.clear()
    assert data["client"].post(old.BASE + "/auth/invitations/complete", json={
        "token": original, "password": old.PASSWORD, "full_name": "Viewer"}).status_code == 401
    old._accept(data["client"], current)
    assert data["client"].get(old.BASE + "/reports/usage").status_code == 403
    old._enroll(data["client"])
    assert data["client"].get(old.BASE + "/reports/usage").status_code == 200


def test_remove_preserves_shared_user_memberships_and_audit(recovery_console):
    data = recovery_console
    with get_session_factory()() as session:
        user = User(email="existing@recovery.example", full_name="Existing Member",
                    password_hash=hash_password(old.PASSWORD))
        session.add(user)
        session.flush()
        session.add(CompanyMembership(user_id=user.id, company_id=data["tenant"]["company"]["id"],
                                      role="member"))
        session.commit()
    record = old._invite(data, "existing@recovery.example")
    before = _identity(record["id"])
    assert before["initializes_password"] is False
    with get_session_factory()() as session:
        prior = {r.id for r in session.scalars(select(PlatformReportAuditEvent))}
    assert _command(data, record, "remove").status_code == 200
    for path in ("/admins", "/admins/manage"):
        response = data["client"].get(old.BASE + path)
        assert response.status_code == 200
        assert record["id"] not in {r["id"] for r in response.json()["items"]}
    assert _identity(record["id"]) == before
    with get_session_factory()() as session:
        assert session.get(PlatformReportAdmin, record["id"]).removed_at is not None
        assert prior <= {r.id for r in session.scalars(select(PlatformReportAuditEvent))}
    assert _invite(data, record).status_code == 200
    assert _identity(record["id"]) == before
    with get_session_factory()() as session:
        assert session.get(PlatformReportAdmin, record["id"]).removed_at is None
    data["client"].cookies.clear()
    token = old._link(data["messages"])
    assert data["client"].post(old.BASE + "/auth/invitations/complete", json={
        "token": token, "password": "DifferentStrongPass123!", "full_name": "No Rename"}
    ).status_code == 401
    old._accept(data["client"], token)
    assert _identity(record["id"]) == before


def test_managed_version_does_not_change_legacy_responses(recovery_console):
    data = recovery_console
    record = old._invite(data)
    keys = {"id", "email", "full_name", "role", "status", "created_at"}
    assert set(record) == keys
    legacy = data["client"].get(old.BASE + "/admins").json()
    assert all(set(row) == keys for row in legacy["items"])
    current = data["client"].get(old.BASE + "/admins/manage")
    assert current.status_code == 200
    row = next(r for r in current.json()["items"] if r["id"] == record["id"])
    assert set(row) == keys | {"version", "removed_at", "can_manage"}
    assert row["can_manage"] is True
    assert row["version"] == _version(record["id"]) and row["removed_at"] is None
    response = data["client"].post(old.BASE + f"/admins/{record['id']}/revoke",
        json={"reason": "Old client lacks target version"}, headers=old._csrf(data["client"]))
    assert response.status_code == 409 and response.json()["code"] == "console_reload_required"
    assert _version(record["id"]) == row["version"]


@pytest.mark.parametrize("action", ["remove", "revoke", "invitations/resend"])
def test_stale_command_cannot_change_later_admission(recovery_console, action):
    data = recovery_console
    record = old._invite(data)
    stale = _version(record["id"])
    assert _command(data, record, "revoke").status_code == 200
    assert _invite(data, record).status_code == 200
    before, count = old._invitation_snapshot(record["id"]), len(data["messages"])
    assert _command(data, record, action, version=stale).status_code == 409
    assert old._invitation_snapshot(record["id"]) == before
    assert len(data["messages"]) == count


@pytest.mark.parametrize("outcome", ["accepted", "failed", "outcome_unknown"])
def test_resend_cooldown_and_no_paid_transaction_free_transport(
    recovery_console, monkeypatch, outcome
):
    data = recovery_console
    record = old._invite(data)
    original = old._link(data["messages"])
    before = old._invitation_snapshot(record["id"])
    cooling = _command(data, record, "invitations/resend")
    assert cooling.json()["code"] == "console_invitation_cooldown"
    assert old._invitation_snapshot(record["id"]) == before
    with get_session_factory()() as session:
        session.execute(update(PlatformConsoleToken).where(
            PlatformConsoleToken.report_admin_id == record["id"]
        ).values(created_at=datetime.now(UTC) - timedelta(minutes=6)))
        session.commit()
    calls = []

    def transport(url, **kwargs):
        assert url == "http://127.0.0.1:8129/messages"
        assert paid_providers_blocked_for_request()
        assert not data["transport_session"][0].in_transaction()
        assert not kwargs["follow_redirects"] and not kwargs["trust_env"]
        calls.append(kwargs["json"])
        if outcome == "outcome_unknown":
            raise httpx.ReadTimeout("Synthetic unknown transport")
        return httpx.Response(202 if outcome == "accepted" else 503)

    monkeypatch.setattr(console.httpx, "post", transport)
    response = _command(data, record, "invitations/resend")
    assert response.status_code == 200 and response.json()["delivery_status"] == outcome
    assert len(calls) == 1 and old._link(calls) != original
    assert _invite(data, record).json() == response.json()
    assert len(calls) == 1


@pytest.mark.parametrize("blocked", ["inactive_user", "other_issuer", "root", "csrf", "step_up"])
def test_recovery_authority_fails_closed(recovery_console, blocked):
    data = recovery_console
    record = old._invite(data)
    with get_session_factory()() as session:
        admin = session.get(PlatformReportAdmin, record["id"])
        if blocked == "inactive_user":
            session.get(User, admin.user_id).is_active = False
        elif blocked == "other_issuer":
            admin.created_by_report_admin_id = admin.id
        elif blocked == "root":
            session.get(PlatformAdminMembership, admin.root_platform_admin_id).status = "revoked"
        elif blocked == "step_up":
            session.execute(update(PlatformConsoleSession).where(
                PlatformConsoleSession.report_admin_id == data["manager_id"]
            ).values(issued_at=datetime.now(UTC) - timedelta(minutes=11)))
        session.commit()
    if blocked in {"inactive_user", "other_issuer"}:
        managed = data["client"].get(old.BASE + "/admins/manage").json()["items"]
        assert next(row for row in managed if row["id"] == record["id"])["can_manage"] is False
    before, count = old._invitation_snapshot(record["id"]), len(data["messages"])
    response = _command(data, record, "remove", headers={} if blocked == "csrf" else None)
    assert response.status_code in {401, 403, 409}
    assert old._invitation_snapshot(record["id"]) == before
    assert len(data["messages"]) == count


def test_manager_and_founder_are_not_removable(recovery_console):
    data = recovery_console
    assert _command(data, {"id": data["manager_id"]}, "remove").status_code == 409
    record = old._invite(data, "owner@asterlegal.in")
    page = data["client"].get(old.BASE + "/admins/manage").json()["items"]
    for row in page:
        if row["id"] in {record["id"], data["manager_id"]}:
            assert row["can_manage"] is False
    assert _command(data, record, "remove").status_code == 409


def test_marked_reinvite_never_calls_real_transport(recovery_console, monkeypatch):
    data = recovery_console
    record = old._invite(data)
    assert _command(data, record, "revoke").status_code == 200
    monkeypatch.delenv("CASEOPS_CONSOLE_TEST_MAIL_URL")

    def forbidden(**kwargs):
        pytest.fail("No-paid recovery reached real transport")

    monkeypatch.setattr(console, "_send_via_sendgrid", forbidden)
    response = _invite(data, record)
    assert response.status_code == 200 and response.json()["delivery_status"] == "failed"


def test_reinvite_preserves_established_factor_and_revokes_old_session(recovery_console):
    data = recovery_console
    record = old._invite(data)
    client = data["client"]
    manager_token = client.cookies.get(CONSOLE_SESSION_COOKIE)
    manager_csrf = client.cookies.get(CONSOLE_CSRF_COOKIE)
    original = old._link(data["messages"])
    client.cookies.clear()
    old._accept(client, original)
    old._enroll(client)
    viewer_token = client.cookies.get(CONSOLE_SESSION_COOKIE)
    before = _identity(record["id"])
    with get_session_factory()() as session:
        target = session.get(PlatformReportAdmin, record["id"])
        factor = (
            target.encrypted_totp_secret, target.recovery_code_hashes, target.last_totp_counter
        )
    client.cookies.clear()
    client.cookies.set(CONSOLE_SESSION_COOKIE, manager_token, path=old.BASE)
    client.cookies.set(CONSOLE_CSRF_COOKIE, manager_csrf, path="/")
    assert _command(data, record, "remove").status_code == 200
    assert _invite(data, record).status_code == 200
    assert _identity(record["id"]) == before
    with get_session_factory()() as session:
        target = session.get(PlatformReportAdmin, record["id"])
        assert (target.encrypted_totp_secret, target.recovery_code_hashes,
                target.last_totp_counter) == factor
    client.cookies.clear()
    client.cookies.set(CONSOLE_SESSION_COOKIE, viewer_token, path=old.BASE)
    assert client.get(old.BASE + "/reports/usage").status_code == 401
    response = client.post(old.BASE + "/auth/invitations/complete", json={
        "token": old._link(data["messages"]), "password": old.PASSWORD, "full_name": "No Rename"
    })
    assert response.status_code == 200
    assert response.json()["state"] == "mfa_challenge_required"
    assert response.json()["admin"] is None
    assert client.get(old.BASE + "/reports/usage").status_code == 403


def test_reinvite_cannot_reenable_globally_disabled_user(recovery_console):
    data = recovery_console
    record = old._invite(data)
    assert _command(data, record, "remove").status_code == 200
    with get_session_factory()() as session:
        target = session.get(PlatformReportAdmin, record["id"])
        session.get(User, target.user_id).is_active = False
        session.commit()
    before, count = old._invitation_snapshot(record["id"]), len(data["messages"])
    assert _invite(data, record).status_code == 409
    assert old._invitation_snapshot(record["id"]) == before
    assert len(data["messages"]) == count


def test_grant_insert_conflict_is_409_before_transport(recovery_console):
    data = recovery_console
    count = len(data["messages"])

    def conflict(session, flush_context, instances):
        if any(isinstance(row, PlatformReportAdmin) for row in session.new):
            raise IntegrityError("synthetic grant uniqueness loss", None, ValueError("conflict"))

    event.listen(Session, "before_flush", conflict)
    try:
        response = data["client"].post(old.BASE + "/admins/invitations", json={
            "email": "conflicting@recovery.example", "full_name": "Conflict"
        }, headers=old._csrf(data["client"]))
    finally:
        event.remove(Session, "before_flush", conflict)
    assert response.status_code == 409 and response.json()["code"] == "console_conflict"
    assert len(data["messages"]) == count
    with get_session_factory()() as session:
        assert session.scalar(select(User.id).where(
            User.email == "conflicting@recovery.example"
        )) is None


def test_managed_eligibility_does_not_query_per_row(recovery_console):
    data = recovery_console
    for index in range(3):
        old._invite(data, f"bounded-{index}@recovery.example")
    count = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            count.append(1)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", observe)
    try:
        small = data["client"].get(old.BASE + "/admins/manage?limit=1")
        first_count = len(count)
        count.clear()
        large = data["client"].get(old.BASE + "/admins/manage?limit=100")
        large_count = len(count)
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert small.status_code == large.status_code == 200
    assert len(small.json()["items"]) == 1 and len(large.json()["items"]) == 4
    assert first_count == large_count
    assert sum(row["can_manage"] for row in large.json()["items"]) == 3
