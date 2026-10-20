"""PRA-04..08: no tenant authority, fresh MFA and one-use delivery fences."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError

from caseops_api.core import security as credentials
from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.console_auth import (
    CONSOLE_CSRF_COOKIE,
    CONSOLE_CSRF_HEADER,
    CONSOLE_SESSION_COOKIE,
    decode_console_token,
)
from caseops_api.core.security import (
    TokenValidationError,
    create_access_token,
    create_portal_session_token,
    decode_access_token,
    decode_portal_session_token,
    hash_password,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingPaymentOrder,
    BillingPaymentOrderStatus,
    BillingPlanPrice,
    BillingPlanVersion,
    BillingProfitRollup,
    BillingSubscription,
    BillingSubscriptionStatus,
    BillingUsageAttribution,
    Company,
    CompanyMembership,
    PlatformAdminMembership,
    PlatformConsoleDelivery,
    PlatformConsoleToken,
    PlatformReportAdmin,
    PlatformReportAuditEvent,
    ProviderCostProfile,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.platform_console import (
    ConsoleInviteCompleteRequest,
    ConsoleInviteRequest,
    ConsoleLoginRequest,
    ConsoleProfitRecord,
    ConsoleRevenueRecord,
    ConsoleRevokeRequest,
    ConsoleTokenCompleteRequest,
)
from caseops_api.services import platform_console as console
from caseops_api.services.platform_console_reports import overview, report_page
from caseops_api.services.provider_costs import case_refresh_guardrail_warnings
from caseops_api.services.saas_billing import (
    platform_overview,
    platform_profit_report,
    platform_usage_report,
)
from caseops_api.services.security import _decrypt_secret, _hotp
from tests.test_auth_company import auth_headers, bootstrap_company

BASE = "/api/platform-console"
PASSWORD = "ReportConsolePass123!"


def _csrf(client):
    return {CONSOLE_CSRF_HEADER: client.cookies.get(CONSOLE_CSRF_COOKIE)}


@pytest.fixture
def report_console(client, monkeypatch):
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    monkeypatch.setenv("CASEOPS_CONSOLE_TEST_MAIL_URL", "http://127.0.0.1:8129/messages")
    get_settings.cache_clear()
    tenant = bootstrap_company(client)
    messages = []

    def capture(url, *, json, **kwargs):
        assert url == "http://127.0.0.1:8129/messages"
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        # The real transport boundary owns no database transaction/identity lock.
        assert not sending_session[0].in_transaction()
        messages.append(json)
        return httpx.Response(202)

    sending_session = [None]
    monkeypatch.setattr(console.httpx, "post", capture)
    original_send = console._send_claim

    def observed_send(session, **kwargs):
        sending_session[0] = session
        return original_send(session, **kwargs)

    monkeypatch.setattr(console, "_send_claim", observed_send)
    with get_session_factory()() as session:
        root = session.scalar(select(PlatformAdminMembership))
        assert root is not None
        result = console.bootstrap_report_manager(
            session,
            root_platform_admin_id=root.id,
            email="manager@console.example",
            full_name="Report Manager",
        )
        manager_id = result.admin.id
    assert len(messages) == 1
    client.cookies.clear()
    return {
        "client": client,
        "messages": messages,
        "manager_id": manager_id,
        "tenant": tenant,
        "transport_session": sending_session,
    }


def _link(messages, index=-1):
    url = messages[index]["body"].splitlines()[1]
    assert urlsplit(url).query == ""
    return parse_qs(urlsplit(url).fragment)["token"][0]


def _accept(client, token, password=PASSWORD):
    response = client.post(
        BASE + "/auth/invitations/complete",
        json={
            "token": token,
            "password": password,
            "full_name": "Report User",
        },
    )
    assert response.status_code == 200
    assert response.json()["state"] == "mfa_enrollment_required"
    assert response.json()["admin"] is None
    assert "access_token" not in response.json()
    return response


def _enroll(client):
    response = client.post(BASE + "/auth/mfa/enroll", json={}, headers=_csrf(client))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert set(response.json()) == {"secret", "otpauth_url"}
    code = _hotp(response.json()["secret"], int(datetime.now(UTC).timestamp()) // 30)
    response = client.post(BASE + "/auth/mfa/verify", json={"code": code}, headers=_csrf(client))
    assert response.status_code == 200
    assert response.json()["state"] == "authenticated"
    return response


def _manager(data):
    client = data["client"]
    _accept(client, _link(data["messages"]))
    return _enroll(client)


def _invite(data, email="viewer@console.example"):
    response = data["client"].post(
        BASE + "/admins/invitations",
        json={
            "email": email,
            "full_name": "Viewer",
        },
        headers=_csrf(data["client"]),
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "accepted"
    return response.json()["admin"]


def test_separate_identity_no_fake_company_or_founder_change(report_console):
    data = report_console
    _manager(data)
    with get_session_factory()() as session:
        manager = session.get(PlatformReportAdmin, data["manager_id"])
        memberships = session.scalar(
            select(func.count(CompanyMembership.id)).where(
                CompanyMembership.user_id == manager.user_id,
            )
        )
        assert memberships == 0
        assert session.scalar(select(func.count(Company.id))) == 1
        roots = list(session.scalars(select(PlatformAdminMembership)))
        assert len(roots) == 1
        assert roots[0].user_id == data["tenant"]["user"]["id"]
        assert roots[0].status == "active"


def test_password_proof_alone_cannot_read_reports_or_invite(report_console):
    client = report_console["client"]
    _accept(client, _link(report_console["messages"]))
    assert client.get(BASE + "/reports/usage").status_code == 403
    assert client.get(BASE + "/admins").status_code == 403
    response = client.post(
        BASE + "/admins/invitations",
        headers=_csrf(client),
        json={
            "email": "viewer@console.example",
            "full_name": "Viewer",
        },
    )
    assert response.status_code == 403


def test_cookies_realm_and_logout_are_independent(report_console):
    client = report_console["client"]
    response = _accept(client, _link(report_console["messages"]))
    cookie_headers = response.headers.get_list("set-cookie")
    session_cookie = next(
        item for item in cookie_headers if item.startswith(CONSOLE_SESSION_COOKIE + "=")
    )
    assert "HttpOnly" in session_cookie
    assert "Path=/api/platform-console" in session_cookie
    assert "Domain=" not in session_cookie
    _enroll(client)
    token = client.cookies.get(CONSOLE_SESSION_COOKIE)
    assert decode_console_token(token)["purpose"] == "authenticated"
    for decoder in (decode_access_token, decode_portal_session_token):
        with pytest.raises(TokenValidationError):
            decoder(token)
    response = client.post(BASE + "/auth/logout", json={}, headers=_csrf(client))
    assert response.json() == {"status": "signed_out"}
    assert client.get(BASE + "/auth/session").status_code == 401


@pytest.mark.parametrize("realm", ["tenant", "portal"])
def test_other_realm_tokens_cannot_read_console(report_console, realm):
    client = report_console["client"]
    tenant = report_console["tenant"]
    if realm == "tenant":
        token = tenant["access_token"]
    else:
        token = create_portal_session_token(
            portal_user_id="portal-user", company_id="company", role="viewer"
        )
    client.cookies.set(CONSOLE_SESSION_COOKIE, token, path=BASE)
    assert client.get(BASE + "/auth/session").status_code == 401
    with pytest.raises(TokenValidationError):
        decode_console_token(token)


def test_console_token_replay_cannot_authenticate_tenant_or_founder(report_console):
    client = report_console["client"]
    _manager(report_console)
    token = client.cookies.get(CONSOLE_SESSION_COOKIE)
    assert client.get("/api/auth/me", headers=auth_headers(token)).status_code == 401
    assert (
        client.get("/api/platform-admin/overview", headers=auth_headers(token)).status_code == 401
    )


def test_csrf_is_session_bound_not_just_cookie_equality(report_console):
    client = report_console["client"]
    _manager(report_console)
    client.cookies.set(CONSOLE_CSRF_COOKIE, "planted-token", path="/")
    response = client.post(
        BASE + "/auth/logout", json={}, headers={CONSOLE_CSRF_HEADER: "planted-token"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "console_csrf_invalid"


def test_bearer_header_does_not_exempt_console_csrf(report_console):
    client = report_console["client"]
    response = client.post(
        BASE + "/auth/logout",
        json={},
        headers=auth_headers(report_console["tenant"]["access_token"]),
    )
    assert response.status_code == 403


def test_invite_is_hashed_single_use_and_initializes_no_tenant(report_console):
    data = report_console
    _manager(data)
    record = _invite(data)
    raw = _link(data["messages"])
    with get_session_factory()() as session:
        token = session.scalar(
            select(PlatformConsoleToken).where(PlatformConsoleToken.report_admin_id == record["id"])
        )
        assert token.token_hash == console._digest(raw)
        assert raw not in token.token_hash
    data["client"].cookies.clear()
    _accept(data["client"], raw)
    replay = data["client"].post(
        BASE + "/auth/invitations/complete",
        json={
            "token": raw,
            "password": PASSWORD,
            "full_name": "Viewer",
        },
    )
    assert replay.status_code == 401
    _enroll(data["client"])
    assert data["client"].get(BASE + "/admins").status_code == 403
    assert data["client"].get(BASE + "/reports/usage").status_code == 200


def _invitation_snapshot(admin_id):
    with get_session_factory()() as session:
        admin = dict(session.execute(
            select(PlatformReportAdmin.__table__).where(PlatformReportAdmin.id == admin_id)
        ).mappings().one())
        tokens = list(session.execute(
            select(PlatformConsoleToken.__table__)
            .where(PlatformConsoleToken.report_admin_id == admin_id)
            .order_by(PlatformConsoleToken.id)
        ).mappings())
        deliveries = list(session.execute(
            select(PlatformConsoleDelivery.__table__)
            .join(PlatformConsoleToken, PlatformConsoleToken.id == PlatformConsoleDelivery.token_id)
            .where(PlatformConsoleToken.report_admin_id == admin_id)
            .order_by(PlatformConsoleDelivery.id)
        ).mappings())
        return {"admin": admin, "tokens": [dict(row) for row in tokens],
                "deliveries": [dict(row) for row in deliveries]}


@pytest.mark.parametrize("delivery_status", ["accepted", "failed", "outcome_unknown", "pending"])
def test_pending_invitation_replay_preserves_link_and_delivery(
    report_console, monkeypatch, delivery_status,
):
    data = report_console
    _manager(data)
    attempts = []

    def transport(url, *, json, **kwargs):
        assert not data["transport_session"][0].in_transaction()
        attempts.append(json)
        if delivery_status == "outcome_unknown":
            raise httpx.ReadTimeout("synthetic ambiguous acceptance")
        return httpx.Response(202 if delivery_status == "accepted" else 503)

    monkeypatch.setattr(console.httpx, "post", transport)
    if delivery_status == "pending":
        # Retain the committed claim before any transport starts (e.g. caller crash).
        monkeypatch.setattr(console, "_send_claim", lambda *args, **kwargs: "pending")
    client = data["client"]
    payload = {"email": "viewer@console.example", "full_name": "Original Viewer"}
    first = client.post(BASE + "/admins/invitations", json=payload, headers=_csrf(client))
    assert first.status_code == 200
    assert first.json()["delivery_status"] == delivery_status
    admin_id = first.json()["admin"]["id"]
    before, sent = _invitation_snapshot(admin_id), list(attempts)

    replay = client.post(
        BASE + "/admins/invitations", json={**payload, "full_name": "Must Not Rename"},
        headers=_csrf(client),
    )
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert attempts == sent
    assert _invitation_snapshot(admin_id) == before
    assert len(attempts) == (0 if delivery_status == "pending" else 1)
    if delivery_status == "accepted":
        raw = _link(attempts)
        client.cookies.clear()
        _accept(client, raw)


@pytest.mark.parametrize("status", ["active", "revoked"])
def test_existing_nonpending_viewer_cannot_be_reinvited(report_console, status):
    data = report_console
    _manager(data)
    record = _invite(data)
    raw = _link(data["messages"])
    manager_session = data["client"].cookies.get(CONSOLE_SESSION_COOKIE)
    manager_csrf = data["client"].cookies.get(CONSOLE_CSRF_COOKIE)
    if status == "active":
        data["client"].cookies.clear()
        _accept(data["client"], raw)
        data["client"].cookies.clear()
        data["client"].cookies.set(CONSOLE_SESSION_COOKIE, manager_session, path=BASE)
        data["client"].cookies.set(CONSOLE_CSRF_COOKIE, manager_csrf, path="/")
    else:
        response = data["client"].post(
            BASE + f"/admins/{record['id']}/revoke", json={"reason": "Access ended"},
            headers=_csrf(data["client"]),
        )
        assert response.status_code == 200
    before, sent = _invitation_snapshot(record["id"]), list(data["messages"])

    replay = data["client"].post(
        BASE + "/admins/invitations",
        json={"email": "viewer@console.example", "full_name": "Must Not Regrant"},
        headers=_csrf(data["client"]),
    )
    assert replay.status_code == 409
    assert _invitation_snapshot(record["id"]) == before
    assert data["messages"] == sent
    assert before["admin"]["status"] == status
    if status == "revoked":
        response = data["client"].post(
            BASE + "/auth/invitations/complete",
            json={"token": raw, "password": PASSWORD, "full_name": "Viewer"},
        )
        assert response.status_code == 401


def test_expired_viewer_invitation_requires_explicit_cooldown_resend(report_console):
    data = report_console
    _manager(data)
    record = _invite(data)
    original = _link(data["messages"])
    client = data["client"]
    response = client.post(BASE + "/auth/invitations/resend", json={"email": record["email"]})
    assert response.json() == {"status": "accepted"}
    assert len(data["messages"]) == 2
    with get_session_factory()() as session:
        session.execute(update(PlatformConsoleToken).where(
            PlatformConsoleToken.report_admin_id == record["id"],
        ).values(created_at=datetime.now(UTC) - timedelta(minutes=31),
                 expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        session.commit()
    before = _invitation_snapshot(record["id"])
    replay = client.post(
        BASE + "/admins/invitations", json={"email": record["email"], "full_name": "Viewer"},
        headers=_csrf(client),
    )
    assert replay.status_code == 200
    assert replay.json()["delivery_status"] == "accepted"
    assert _invitation_snapshot(record["id"]) == before
    assert len(data["messages"]) == 2
    response = client.post(BASE + "/auth/invitations/resend", json={"email": record["email"]})
    assert response.json() == {"status": "accepted"}
    replacement = _link(data["messages"])
    assert replacement != original and len(data["messages"]) == 3
    after = _invitation_snapshot(record["id"])
    assert len(after["tokens"]) == len(after["deliveries"]) == 2
    assert after["admin"] == before["admin"]
    replay = client.post(
        BASE + "/admins/invitations", json={"email": record["email"], "full_name": "Viewer"},
        headers=_csrf(client),
    )
    assert replay.status_code == 200
    assert _invitation_snapshot(record["id"]) == after
    assert len(data["messages"]) == 3
    response = client.post(BASE + "/auth/invitations/complete", json={
        "token": original, "password": PASSWORD, "full_name": "Viewer",
    })
    assert response.status_code == 401
    _accept(client, replacement)


def test_existing_identity_invite_never_replaces_password(report_console):
    data = report_console
    _manager(data)
    _invite(data, "owner@asterlegal.in")
    token = _link(data["messages"])
    with get_session_factory()() as session:
        before = session.get(User, data["tenant"]["user"]["id"]).password_hash
    response = data["client"].post(
        BASE + "/auth/invitations/complete",
        json={
            "token": token,
            "password": PASSWORD,
            "full_name": "Do Not Rename",
        },
    )
    assert response.status_code == 401
    response = data["client"].post(
        BASE + "/auth/invitations/complete",
        json={
            "token": token,
            "password": "FoundersPass123!",
            "full_name": "Do Not Rename",
        },
    )
    assert response.status_code == 200
    with get_session_factory()() as session:
        user = session.get(User, data["tenant"]["user"]["id"])
        assert user.password_hash == before
        assert user.full_name != "Do Not Rename"


def test_revoke_invalidates_full_session_and_links(report_console):
    data = report_console
    client = data["client"]
    _manager(data)
    record = _invite(data)
    manager_cookie = client.cookies.get(CONSOLE_SESSION_COOKIE)
    manager_csrf = client.cookies.get(CONSOLE_CSRF_COOKIE)
    raw = _link(data["messages"])
    client.cookies.clear()
    _accept(client, raw)
    _enroll(client)
    viewer_cookie = client.cookies.get(CONSOLE_SESSION_COOKIE)
    client.cookies.clear()
    client.cookies.set(CONSOLE_SESSION_COOKIE, manager_cookie, path=BASE)
    client.cookies.set(CONSOLE_CSRF_COOKIE, manager_csrf, path="/")
    response = client.post(
        BASE + f"/admins/{record['id']}/revoke",
        json={"reason": "Access ended"},
        headers=_csrf(client),
    )
    assert response.status_code == 200
    client.cookies.clear()
    client.cookies.set(CONSOLE_SESSION_COOKIE, viewer_cookie, path=BASE)
    assert client.get(BASE + "/reports/usage").status_code == 401


def test_reset_generic_response_one_use_and_mfa_not_bypassed(report_console):
    data = report_console
    client = data["client"]
    _manager(data)
    old_cookie = client.cookies.get(CONSOLE_SESSION_COOKIE)
    for email in ("missing@console.example", "manager@console.example"):
        response = client.post(BASE + "/auth/password-reset/start", json={"email": email})
        assert response.json() == {"status": "accepted"}
    raw = _link(data["messages"])
    response = client.post(
        BASE + "/auth/password-reset/complete",
        json={"token": raw, "password": "NewReportPassword123!"},
    )
    assert response.json() == {"status": "complete"}
    replay = client.post(
        BASE + "/auth/password-reset/complete", json={"token": raw, "password": PASSWORD}
    )
    assert replay.status_code == 401
    client.cookies.set(CONSOLE_SESSION_COOKIE, old_cookie, path=BASE)
    assert client.get(BASE + "/auth/session").status_code == 401
    client.cookies.clear()
    response = client.post(
        BASE + "/auth/login",
        json={"email": "manager@console.example", "password": "NewReportPassword123!"},
    )
    assert response.json()["state"] == "mfa_challenge_required"
    assert client.get(BASE + "/reports/usage").status_code == 403


def test_shared_password_reset_revokes_old_tenant_jwt(report_console):
    data = report_console
    client = data["client"]
    _manager(data)
    _invite(data, "owner@asterlegal.in")
    response = client.post(
        BASE + "/auth/invitations/complete",
        json={
            "token": _link(data["messages"]),
            "password": "FoundersPass123!",
            "full_name": "Ignored",
        },
    )
    assert response.status_code == 200
    response = client.post(
        BASE + "/auth/password-reset/start", json={"email": "owner@asterlegal.in"}
    )
    assert response.json() == {"status": "accepted"}
    response = client.post(
        BASE + "/auth/password-reset/complete",
        json={"token": _link(data["messages"]), "password": PASSWORD},
    )
    assert response.status_code == 200
    assert (
        client.get("/api/auth/me", headers=auth_headers(data["tenant"]["access_token"])).status_code
        == 401
    )


def test_mfa_failures_and_replay_are_durable(report_console):
    data = report_console
    client = data["client"]
    _manager(data)
    response = client.post(
        BASE + "/auth/login", json={"email": "manager@console.example", "password": PASSWORD}
    )
    assert response.status_code == 200
    with get_session_factory()() as session:
        admin = session.get(PlatformReportAdmin, data["manager_id"])
        secret = _decrypt_secret(admin.encrypted_totp_secret)
        code = _hotp(secret, admin.last_totp_counter)
    for _ in range(5):
        response = client.post(
            BASE + "/auth/mfa/verify", json={"code": code}, headers=_csrf(client)
        )
        assert response.status_code == 401
    response = client.post(BASE + "/auth/mfa/verify", json={"code": code}, headers=_csrf(client))
    assert response.status_code == 429


def test_parent_revocation_and_password_change_fence_current_sessions(report_console):
    data = report_console
    _manager(data)
    with get_session_factory()() as session:
        admin = session.get(PlatformReportAdmin, data["manager_id"])
        user = session.get(User, admin.user_id)
        user.password_hash = hash_password("ExternallyChangedPassword123!")
        session.commit()
    assert data["client"].get(BASE + "/auth/session").status_code == 401
    response = data["client"].post(
        BASE + "/auth/login",
        json={"email": "manager@console.example", "password": "ExternallyChangedPassword123!"},
    )
    assert response.status_code == 200
    with get_session_factory()() as session:
        session.execute(update(PlatformAdminMembership).values(status="revoked"))
        session.commit()
    assert data["client"].get(BASE + "/auth/session").status_code == 401


def test_link_expiry_and_admin_step_up_fences(report_console, monkeypatch):
    data = report_console
    _manager(data)
    _invite(data)
    raw = _link(data["messages"])
    with get_session_factory()() as session:
        session.execute(
            update(PlatformConsoleToken)
            .where(PlatformConsoleToken.token_hash == console._digest(raw))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        session.commit()
    later = datetime.now(UTC) + timedelta(minutes=11)
    monkeypatch.setattr(console, "_now", lambda: later)
    response = data["client"].post(
        BASE + "/auth/invitations/complete",
        json={"token": raw, "password": PASSWORD, "full_name": "Viewer"},
    )
    assert response.status_code == 401
    response = data["client"].post(
        BASE + "/admins/invitations",
        json={"email": "another@console.example", "full_name": "Another"},
        headers=_csrf(data["client"]),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "console_step_up_required"


def test_unknown_reset_cannot_mint_a_principal_or_send(report_console):
    data = report_console
    before = len(data["messages"])
    response = data["client"].post(
        BASE + "/auth/password-reset/start", json={"email": "missing@console.example"}
    )
    assert response.json() == {"status": "accepted"}
    assert len(data["messages"]) == before
    with get_session_factory()() as session:
        assert (
            session.scalar(select(User.id).where(User.email == "missing@console.example")) is None
        )


def test_mail_lease_recovery_has_no_automatic_replay(report_console):
    data = report_console
    with get_session_factory()() as session:
        row = session.scalar(select(PlatformConsoleDelivery))
        row.status = "pending"
        row.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        assert console.recover_expired_delivery_claims(session) == 1
        assert console.recover_expired_delivery_claims(session) == 0
        assert session.scalar(select(PlatformConsoleDelivery.status)) == "outcome_unknown"
    assert len(data["messages"]) == 1


def test_reads_audited_and_directory_has_truthful_continuation(report_console):
    data = report_console
    _manager(data)
    _invite(data)
    first = data["client"].get(BASE + "/admins", params={"limit": 1})
    assert first.status_code == 200
    assert first.headers["Cache-Control"] == "private, no-store"
    assert first.headers["Referrer-Policy"] == "no-referrer"
    assert len(first.json()["items"]) == 1
    assert first.json()["next_cursor"]
    second = data["client"].get(
        BASE + "/admins", params={"limit": 1, "cursor": first.json()["next_cursor"]}
    )
    assert len(second.json()["items"]) == 1
    assert second.json()["next_cursor"] is None
    assert second.json()["items"][0]["id"] != first.json()["items"][0]["id"]
    assert data["client"].get(BASE + "/reports/usage").status_code == 200
    with get_session_factory()() as session:
        targets = list(
            session.scalars(
                select(PlatformReportAuditEvent.target_id).where(
                    PlatformReportAuditEvent.action == "console.report_read",
                )
            )
        )
        assert targets == ["admins", "admins", "usage"]


@pytest.mark.parametrize("realm", ["tenant", "portal"])
def test_authenticate_wrong_realm_even_with_valid_signature(realm, monkeypatch):
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "test-secret-should-be-at-least-32-bytes")
    get_settings.cache_clear()
    token = (
        create_access_token(
            user_id="user", company_id="company", membership_id="member", role="owner"
        )
        if realm == "tenant"
        else create_portal_session_token(
            portal_user_id="portal", company_id="company", role="viewer"
        )
    )
    with pytest.raises(TokenValidationError):
        decode_console_token(token)


@pytest.mark.parametrize(
    "case", ["unknown", "wrong_password", "disabled", "revoked", "root_invalid", "pending"]
)
def test_invalid_login_always_performs_one_password_verification(report_console, monkeypatch, case):
    data = report_console
    _manager(data)
    with get_session_factory()() as session:
        admin = session.get(PlatformReportAdmin, data["manager_id"])
        if case == "disabled":
            session.get(User, admin.user_id).is_active = False
        elif case in {"revoked", "pending"}:
            admin.status = case
        elif case == "root_invalid":
            session.get(PlatformAdminMembership, admin.root_platform_admin_id).status = "revoked"
        session.commit()
    calls = []
    real_scrypt = credentials.hashlib.scrypt

    def observed(*args, **kwargs):
        calls.append(1)
        return real_scrypt(*args, **kwargs)

    monkeypatch.setattr(credentials.hashlib, "scrypt", observed)
    response = data["client"].post(
        BASE + "/auth/login",
        json={
            "email": "unknown@console.example" if case == "unknown" else "manager@console.example",
            "password": "WrongPassword123!" if case == "wrong_password" else PASSWORD,
        },
    )
    assert calls == [1]
    assert response.status_code == 401
    assert response.json()["code"] == "console_session_invalid"


def test_known_principal_password_throttle_survives_requests(report_console):
    data = report_console
    _manager(data)
    for _ in range(5):
        response = data["client"].post(
            BASE + "/auth/login",
            json={
                "email": "manager@console.example",
                "password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401
    response = data["client"].post(
        BASE + "/auth/login",
        json={
            "email": "manager@console.example",
            "password": PASSWORD,
        },
    )
    assert response.status_code == 401
    with get_session_factory()() as session:
        assert session.get(PlatformReportAdmin, data["manager_id"]).login_locked_until is not None


@pytest.mark.parametrize(
    "method,path,payload,status",
    [
        (
            "POST",
            "/api/platform-console/auth/login",
            {"email": "missing@console.example", "password": PASSWORD},
            401,
        ),
        ("GET", "/api/platform-console/auth/session", None, 401),
        ("POST", "/api/platform-console/auth/mfa/enroll", {}, 403),
        ("POST", "/api/platform-console/auth/mfa/verify", {"code": "123456"}, 403),
        ("POST", "/api/platform-console/auth/logout", {}, 403),
        (
            "POST",
            "/api/platform-console/auth/invitations/complete",
            {"token": "x" * 43, "password": PASSWORD, "full_name": "Viewer"},
            401,
        ),
        (
            "POST",
            "/api/platform-console/auth/invitations/resend",
            {"email": "missing@console.example"},
            200,
        ),
        (
            "POST",
            "/api/platform-console/auth/password-reset/start",
            {"email": "missing@console.example"},
            200,
        ),
        (
            "POST",
            "/api/platform-console/auth/password-reset/complete",
            {"token": "x" * 43, "password": PASSWORD},
            401,
        ),
        ("GET", "/api/platform-console/admins", None, 401),
        (
            "POST",
            "/api/platform-console/admins/invitations",
            {"email": "viewer@console.example", "full_name": "Viewer"},
            403,
        ),
        ("POST", "/api/platform-console/admins/{admin_id}/revoke", {"reason": "Access ended"}, 403),
        ("GET", "/api/platform-console/reports/activity", None, 401),
        ("GET", "/api/platform-console/reports/overview", None, 401),
        ("GET", "/api/platform-console/reports/{kind}", None, 401),
    ],
)
def test_every_console_http_route_denies_unproven_authority(client, method, path, payload, status):
    actual = path.replace("{admin_id}", "unknown").replace("{kind}", "usage")
    response = client.request(method, actual, **({"json": payload} if payload is not None else {}))
    assert response.status_code == status
    assert "access_token" not in response.json()
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_sql_bounded_usage_and_profit_pages_match_canonical_records(report_console):
    data = report_console
    company_id = data["tenant"]["company"]["id"]
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        for index in range(3):
            session.add(
                BillingUsageAttribution(
                    company_id=company_id,
                    feature_key=f"feature-{index}",
                    provider_units=index + 1,
                    credits_debited=index + 2,
                )
            )
            session.add(
                BillingProfitRollup(
                    company_id=company_id,
                    period_start=now - timedelta(days=index + 1),
                    period_end=now - timedelta(days=index),
                    gross_revenue_minor=100 + index,
                    recognized_revenue_minor=80 + index,
                    total_variable_cost_minor=30,
                    gross_profit_minor=50 + index,
                )
            )
        session.commit()
        expected_usage = platform_usage_report(session)
        expected_profit = platform_profit_report(session)
        for record in expected_profit:
            for field in ("period_start", "period_end"):
                value = record[field]
                record[field] = (
                    value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
                )
        session.commit()
        statements = []

        def observed(_conn, _cursor, statement, parameters, _context, _many):
            statements.append((statement, parameters))

        event.listen(session.get_bind(), "before_cursor_execute", observed)
        try:
            captured = {}
            for kind in ("usage", "profit"):
                cursor = None
                records = []
                for _ in range(3):
                    page = report_page(session, kind=kind, cursor=cursor, limit=1)
                    assert len(page.items) == 1
                    assert page.has_more == (len(records) < 2)
                    records.extend(item.model_dump() for item in page.items)
                    cursor = page.next_cursor
                assert cursor is None
                captured[kind] = records
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", observed)
        assert len(statements) == 6
        assert all("LIMIT" in statement.upper() for statement, _ in statements)
        assert captured["usage"] == expected_usage
        assert sorted(captured["profit"], key=lambda row: row["period_start"]) == sorted(
            expected_profit, key=lambda row: row["period_start"]
        )


def _assert_utc_json_timestamp(value, expected):
    assert isinstance(value, str)
    actual = datetime.fromisoformat(value)
    assert actual.tzinfo is not None
    assert actual.utcoffset() == timedelta(0)
    assert actual == expected


def _assert_persisted_report_date_contract(data, *, paid_at_present, offset_minutes=0):
    company_id = data["tenant"]["company"]["id"]
    period_start = datetime(2026, 9, 1, 0, 0, 0, 123456, tzinfo=UTC)
    period_end = datetime(2026, 10, 1, 0, 0, 0, 654321, tzinfo=UTC)
    paid_at = datetime(2026, 10, 2, 7, 8, 9, 345678, tzinfo=UTC)
    source_zone = timezone(timedelta(minutes=offset_minutes))
    with get_session_factory()() as session:
        rollup = BillingProfitRollup(
            company_id=company_id,
            period_start=period_start.astimezone(source_zone),
            period_end=period_end.astimezone(source_zone),
            gross_revenue_minor=123456,
            recognized_revenue_minor=120001,
            total_variable_cost_minor=2345,
            gross_profit_minor=117656,
        )
        payment = BillingPaymentOrder(
            company_id=company_id,
            merchant_reference="console-date-contract",
            status=BillingPaymentOrderStatus.PAID,
            amount_minor=123456,
            amount_paid_minor=123456,
            tax_amount_minor=3455,
            paid_at=paid_at.astimezone(source_zone) if paid_at_present else None,
        )
        session.add_all([
            rollup,
            payment,
            BillingUsageAttribution(
                company_id=company_id,
                feature_key="console-date-contract",
                provider_units=7,
                credits_debited=11,
            ),
        ])
        session.commit()
        rollup_id, payment_id = rollup.id, payment.id
    # A fresh session must consume persisted values, not the aware insert objects.
    with get_session_factory()() as session:
        stored_rollup = session.get(BillingProfitRollup, rollup_id)
        stored_payment = session.get(BillingPaymentOrder, payment_id)
        assert stored_rollup is not None and stored_payment is not None
        persisted_dates = [
            (stored_rollup.period_start, period_start),
            (stored_rollup.period_end, period_end),
        ]
        if paid_at_present:
            persisted_dates.append((stored_payment.paid_at, paid_at))
        for actual, expected in persisted_dates:
            if session.get_bind().dialect.name == "sqlite":
                assert actual.tzinfo is None
                assert actual == expected.replace(tzinfo=None)
            else:
                assert session.get_bind().dialect.name == "postgresql"
                assert actual.tzinfo is not None
                assert actual.astimezone(UTC) == expected
        if not paid_at_present:
            assert stored_payment.paid_at is None

    _manager(data)
    responses = {}
    for kind in ("activity", "overview", "usage", "profit", "company-profitability", "revenue"):
        response = data["client"].get(f"{BASE}/reports/{kind}")
        assert response.status_code == 200, (kind, response.text)
        assert response.headers["Cache-Control"] == "private, no-store"
        responses[kind] = response.json()
    profit = next(row for row in responses["profit"]["items"] if row["company_id"] == company_id)
    _assert_utc_json_timestamp(profit["period_start"], period_start)
    _assert_utc_json_timestamp(profit["period_end"], period_end)
    assert profit["gross_revenue_minor"] == 123456
    assert profit["recognized_revenue_minor"] == 120001
    assert profit["total_variable_cost_minor"] == 2345
    assert profit["gross_profit_minor"] == 117656
    payment = next(
        row for row in responses["revenue"]["items"]
        if row["merchant_reference"] == "console-date-contract"
    )
    if paid_at_present:
        _assert_utc_json_timestamp(payment["paid_at"], paid_at)
    else:
        assert payment["paid_at"] is None
    assert payment["amount_paid_minor"] == 123456
    assert payment["tax_amount_minor"] == 3455
    usage = next(
        row for row in responses["usage"]["items"]
        if row["company_id"] == company_id and row["feature_key"] == "console-date-contract"
    )
    assert (usage["quantity"], usage["credits"]) == (7, 11)
    company_profit = next(
        row for row in responses["company-profitability"]["items"]
        if row["company_id"] == company_id
    )
    assert company_profit["gross_profit_minor"] == profit["gross_profit_minor"]
    assert responses["overview"]["gross_profit_minor"] == profit["gross_profit_minor"]


@pytest.mark.parametrize("paid_at_present", [True, False], ids=["dated", "null-payment-date"])
def test_persisted_sqlite_report_dates_are_utc_in_http_json(report_console, paid_at_present):
    _assert_persisted_report_date_contract(report_console, paid_at_present=paid_at_present)


@pytest.mark.parametrize("offset_minutes", [0, 330, -240], ids=["utc", "east", "west"])
def test_console_billing_date_dtos_preserve_non_utc_instants(report_console, offset_minutes):
    company_id = report_console["tenant"]["company"]["id"]
    expected = datetime(2026, 10, 2, 7, 8, 9, 123456, tzinfo=UTC)
    source = expected.astimezone(timezone(timedelta(minutes=offset_minutes)))
    with get_session_factory()() as session:
        session.add(BillingProfitRollup(
            company_id=company_id, period_start=expected, period_end=expected + timedelta(days=1),
        ))
        session.commit()
        record = platform_profit_report(session)[0]
    record.update(period_start=source, period_end=source + timedelta(days=1))
    profit = ConsoleProfitRecord.model_validate(record).model_dump(mode="json")
    _assert_utc_json_timestamp(profit["period_start"], expected)
    _assert_utc_json_timestamp(profit["period_end"], expected + timedelta(days=1))
    revenue = ConsoleRevenueRecord(
        paid_at=source, company_id=company_id, merchant_reference="offset-date-contract",
        amount_paid_minor=123456, tax_amount_minor=3455,
    ).model_dump(mode="json")
    _assert_utc_json_timestamp(revenue["paid_at"], expected)
    assert (revenue["amount_paid_minor"], revenue["tax_amount_minor"]) == (123456, 3455)


def test_unknown_rollups_are_not_zero_and_company_candidates_are_bounded(report_console):
    with get_session_factory()() as session:
        session.add(
            Company(name="No Rollup", slug="no-rollup", company_type="solo", tenant_key="no-rollup")
        )
        session.commit()
        page = report_page(session, kind="company-profitability", cursor=None, limit=1)
        assert len(page.items) == 1
        assert page.has_more
        assert page.coverage == "recorded_rollups"
        for cursor in (None, page.next_cursor):
            item = report_page(session, kind="company-profitability", cursor=cursor, limit=1).items[
                0
            ]
            assert item.rollup_count == 0
            assert item.recognized_revenue_minor is None
            assert item.gross_profit_minor is None
            assert item.loss_risk is None
        result = overview(session)
        assert result.rollup_count == 0
        assert result.gross_revenue_minor is None
        assert result.gross_margin_bps is None


def test_report_cursor_cannot_cross_kinds_or_be_tampered(report_console):
    data = report_console
    _manager(data)
    with get_session_factory()() as session:
        for feature in ("one", "two"):
            session.add(
                BillingUsageAttribution(
                    company_id=data["tenant"]["company"]["id"], feature_key=feature
                )
            )
        session.commit()
    response = data["client"].get(BASE + "/reports/usage", params={"limit": 1})
    assert response.status_code == 200
    cursor = response.json()["next_cursor"]
    for kind, value in (("profit", cursor), ("usage", "tampered")):
        response = data["client"].get(
            BASE + "/reports/" + kind, params={"limit": 1, "cursor": value}
        )
        assert response.status_code == 400


def test_disabled_issuer_user_immediately_denies_viewer(report_console):
    data = report_console
    _manager(data)
    _invite(data)
    token = _link(data["messages"])
    data["client"].cookies.clear()
    _accept(data["client"], token)
    _enroll(data["client"])
    assert data["client"].get(BASE + "/reports/usage").status_code == 200
    with get_session_factory()() as session:
        manager = session.get(PlatformReportAdmin, data["manager_id"])
        session.get(User, manager.user_id).is_active = False
        session.commit()
    assert data["client"].get(BASE + "/reports/usage").status_code == 401


def test_one_unrevoked_manager_constraint_is_native(report_console):
    with get_session_factory()() as session:
        manager = session.get(PlatformReportAdmin, report_console["manager_id"])
        root_id = manager.root_platform_admin_id
        user = User(
            email="second-manager@console.example",
            full_name="Second",
            password_hash=hash_password(PASSWORD),
        )
        session.add(user)
        session.flush()
        user_id = user.id
        session.add(
            PlatformReportAdmin(
                user_id=user_id, role="manager", status="pending", root_platform_admin_id=root_id
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        assert session.scalar(select(func.count(PlatformReportAdmin.id))) == 1


def test_expired_initial_manager_setup_has_explicit_throttled_resend(report_console):
    data = report_console
    original = _link(data["messages"])
    with get_session_factory()() as session:
        session.execute(
            update(PlatformConsoleToken).values(
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
                created_at=datetime.now(UTC) - timedelta(minutes=31),
            )
        )
        session.commit()
        manager = session.get(PlatformReportAdmin, data["manager_id"])
        record = console.bootstrap_report_manager(
            session,
            root_platform_admin_id=manager.root_platform_admin_id,
            email="manager@console.example",
            full_name="Manager",
        )
        assert record.id == data["manager_id"]
    assert len(data["messages"]) == 1
    for address in (
        "unknown@console.example",
        "manager@console.example",
        "manager@console.example",
    ):
        response = data["client"].post(
            "/api/platform-console/auth/invitations/resend", json={"email": address}
        )
        assert response.json() == {"status": "accepted"}
    assert len(data["messages"]) == 2
    replacement = _link(data["messages"])
    assert replacement != original
    response = data["client"].post(
        BASE + "/auth/invitations/complete",
        json={
            "token": original,
            "password": PASSWORD,
            "full_name": "Manager",
        },
    )
    assert response.status_code == 401
    _accept(data["client"], replacement)
    _enroll(data["client"])


@pytest.mark.parametrize("policy", ["unconfigured", "automated", "production_adapter"])
def test_real_mail_never_runs_without_admission(report_console, monkeypatch, policy):
    data = report_console
    _manager(data)
    calls = []
    monkeypatch.setattr(console, "_send_via_sendgrid", lambda **kwargs: calls.append(1))
    if policy != "production_adapter":
        monkeypatch.delenv("CASEOPS_CONSOLE_TEST_MAIL_URL")
    else:
        settings = get_settings().model_copy(update={"env": "production"})
        monkeypatch.setattr(console, "get_settings", lambda: settings)
    response = data["client"].post(
        BASE + "/admins/invitations",
        json={
            "email": "viewer@console.example",
            "full_name": "Viewer",
        },
        headers={
            **_csrf(data["client"]),
            **({"X-CaseOps-Automated-Test": "no-paid-providers"} if policy == "automated" else {}),
        },
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "failed"
    assert calls == []
    assert len(data["messages"]) == 1


def test_ambiguous_mail_retains_sanitized_unknown_outcome(report_console, monkeypatch):
    data = report_console
    _manager(data)

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("synthetic private transport detail")

    monkeypatch.setattr(console.httpx, "post", timeout)
    response = data["client"].post(
        BASE + "/admins/invitations",
        json={
            "email": "viewer@console.example",
            "full_name": "Viewer",
        },
        headers=_csrf(data["client"]),
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "outcome_unknown"
    assert "synthetic private" not in response.text
    with get_session_factory()() as session:
        errors = list(session.scalars(select(PlatformConsoleDelivery.error_code)))
        assert errors.count("transport_outcome_unknown") == 1


def test_validation_does_not_echo_credentials_or_link_tokens(client):
    password, token = "synthetic-private-password", "synthetic-private-token"
    response = client.post(
        BASE + "/auth/invitations/complete",
        json={
            "token": token,
            "password": password,
            "full_name": "Viewer",
        },
    )
    assert response.status_code == 422
    assert password not in response.text
    assert token not in response.text


def test_authorized_activity_returns_typed_all_registered_accounts(report_console):
    data = report_console
    _manager(data)
    with get_session_factory()() as session:
        company = Company(
            name="Test Internal Solo",
            slug="internal-solo",
            company_type="solo",
            tenant_key="internal-solo",
        )
        session.add(company)
        session.commit()
        expected_id = company.id
    response = data["client"].get("/api/platform-console/reports/activity")
    assert response.status_code == 200
    report = response.json()
    assert report["account_scope"] == "all_registered_accounts"
    assert report["excluded_account_count"] == 0
    accounts = [
        account for segment in report["segments"].values() for account in segment["accounts"]
    ]
    assert len(accounts) == 2
    assert sum(account["company_id"] == expected_id for account in accounts) == 1
    assert report["segments"]["solo_lawyers"]["accounts"][0]["company_id"] == expected_id
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_overview_preserves_canonical_cost_warning_with_sql_bound(report_console):
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        for provider, amount in (("default", 100), ("case_tracking", 20), ("other", 200)):
            session.add(
                ProviderCostProfile(
                    category="case_refresh",
                    provider=provider,
                    unit_amount_minor=amount,
                    effective_from=now - timedelta(days=1),
                )
            )
        session.commit()
        expected = case_refresh_guardrail_warnings(session)
        assert len(expected) == 1
        assert expected[0]["unit_amount_minor"] == 20
        session.commit()
        statements = []

        def observed(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(session.get_bind(), "before_cursor_execute", observed)
        try:
            assert case_refresh_guardrail_warnings(session, bounded=True) == expected
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", observed)
        assert len(statements) == 1
        assert "LIMIT" in statements[0].upper()
        assert overview(session).margin_alerts[0].model_dump() == expected[0]


def test_console_auth_and_directory_timestamps_have_utc_offsets_after_reload(report_console):
    data = report_console
    _manager(data)
    state = data["client"].get("/api/platform-console/auth/session")
    assert state.status_code == 200
    assert datetime.fromisoformat(state.json()["expires_at"]).tzinfo is not None
    directory = data["client"].get("/api/platform-console/admins")
    assert directory.status_code == 200
    for admin in directory.json()["items"]:
        assert datetime.fromisoformat(admin["created_at"]).tzinfo is not None


@pytest.mark.parametrize(
    "env,automated,accepted",
    [
        ("production", False, True),
        ("production", True, False),
        ("local", False, False),
        ("dev", False, False),
        ("test", False, False),
        ("ci", False, False),
        ("e2e", False, False),
    ],
)
def test_auth_mail_admission_respects_all_local_modes_and_automated_marker(
    report_console,
    monkeypatch,
    env,
    automated,
    accepted,
):
    data = report_console
    _manager(data)
    monkeypatch.delenv("CASEOPS_CONSOLE_TEST_MAIL_URL")
    settings = get_settings().model_copy(
        update={
            "env": env,
            "sendgrid_api_key": "offline-synthetic-credential",
            "sendgrid_sender_email": "sender@caseops.example",
            "public_app_url": "https://caseops.example",
            "notification_external_delivery_enabled": False,
        }
    )
    monkeypatch.setattr(console, "get_settings", lambda: settings)
    calls = []

    def provider(**kwargs):
        assert not data["transport_session"][0].in_transaction()
        calls.append(1)
        return True, "offline-synthetic-message-id", None

    monkeypatch.setattr(console, "_send_via_sendgrid", provider)
    headers = _csrf(data["client"])
    if automated:
        headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    response = data["client"].post(
        "/api/platform-console/admins/invitations",
        json={
            "email": "viewer@console.example",
            "full_name": "Viewer",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == ("accepted" if accepted else "failed")
    assert calls == ([1] if accepted else [])


@pytest.mark.parametrize(
    "override",
    [
        {"sendgrid_api_key": None},
        {"sendgrid_api_key": " "},
        {"sendgrid_sender_email": "not-an-address"},
        {"public_app_url": "http://caseops.example"},
        {"public_app_url": "https://user:password@caseops.example"},
    ],
)
def test_auth_mail_readiness_rejects_invalid_sender_key_and_link_origin(override):
    settings = get_settings().model_copy(
        update={
            "env": "production",
            "sendgrid_api_key": "offline-synthetic-credential",
            "sendgrid_sender_email": "sender@caseops.example",
            "public_app_url": "https://caseops.example",
            **override,
        }
    )
    assert not console._auth_mail_ready(settings, automated=False)


@pytest.mark.parametrize("denial", ["mfa", "viewer", "expired_step_up"])
def test_known_admin_change_denials_commit_minimized_actor_audit(
    report_console, monkeypatch, denial
):
    data = report_console
    client = data["client"]
    actor_id = data["manager_id"]
    if denial == "mfa":
        _accept(client, _link(data["messages"]))
        code = "console_mfa_required"
    else:
        _manager(data)
        if denial == "viewer":
            actor_id = _invite(data)["id"]
            client.cookies.clear()
            _accept(client, _link(data["messages"]))
            _enroll(client)
            code = "console_manager_required"
        else:
            later = datetime.now(UTC) + timedelta(minutes=11)
            monkeypatch.setattr(console, "_now", lambda: later)
            code = "console_step_up_required"
    with get_session_factory()() as session:
        prior_audits = set(session.scalars(select(PlatformReportAuditEvent.id)))
        prior_grants = set(session.scalars(select(PlatformReportAdmin.id)))
        prior_tokens = set(session.scalars(select(PlatformConsoleToken.id)))
        actor_user_id = session.get(PlatformReportAdmin, actor_id).user_id
    before_messages = len(data["messages"])
    response = client.post(
        "/api/platform-console/admins/invitations",
        json={"email": "never-created@console.example", "full_name": "https://secret.example"},
        headers=_csrf(client),
    )
    assert response.status_code == 403
    assert response.json()["code"] == code
    assert len(data["messages"]) == before_messages
    # A new Session proves the denial was committed before the HTTP response.
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(PlatformReportAuditEvent).where(
                    PlatformReportAuditEvent.id.not_in(prior_audits)
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].report_admin_id == actor_id
        assert rows[0].actor_user_id == actor_user_id
        assert rows[0].action == "console.access_denied"
        assert rows[0].target_id == "admin_change"
        assert rows[0].result == "denied"
        assert rows[0].reason == code
        assert set(session.scalars(select(PlatformReportAdmin.id))) == prior_grants
        assert set(session.scalars(select(PlatformConsoleToken.id))) == prior_tokens


@pytest.mark.parametrize("token", [None, "untrusted.payload.signature"])
def test_untrusted_console_denial_never_attributes_victim_actor(report_console, token):
    data = report_console
    client = data["client"]
    client.cookies.clear()
    if token:
        client.cookies.set(CONSOLE_SESSION_COOKIE, token, path=BASE)
    with get_session_factory()() as session:
        prior_audits = set(session.scalars(select(PlatformReportAuditEvent.id)))
    assert client.get("/api/platform-console/reports/usage").status_code == 401
    with get_session_factory()() as session:
        rows = list(
            session.scalars(
                select(PlatformReportAuditEvent).where(
                    PlatformReportAuditEvent.id.not_in(prior_audits)
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].report_admin_id is None
        assert rows[0].actor_user_id is None


@pytest.mark.parametrize("blank", ["", " ", "\t\r\n"])
@pytest.mark.parametrize("kind", ["invite", "complete", "revoke"])
def test_console_names_and_revocation_reason_reject_blank_fields(blank, kind):
    from pydantic import ValidationError

    model, payload = {
        "invite": (ConsoleInviteRequest, {"email": "viewer@console.example", "full_name": blank}),
        "complete": (
            ConsoleInviteCompleteRequest,
            {"token": "t" * 43, "password": PASSWORD, "full_name": blank},
        ),
        "revoke": (ConsoleRevokeRequest, {"reason": blank}),
    }[kind]
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_console_normalizes_only_names_and_reason_not_credentials():
    password = "  PasswordWithSpaces123!  "
    token = " " + "t" * 43 + " "
    invite = ConsoleInviteRequest(email="viewer@console.example", full_name=" \tViewer \r\n")
    complete = ConsoleInviteCompleteRequest(
        token=token, password=password, full_name=" \tViewer \r\n"
    )
    assert invite.full_name == complete.full_name == "Viewer"
    assert ConsoleRevokeRequest(reason=" \tAccess ended \r\n").reason == "Access ended"
    assert complete.password == password
    assert complete.token == token
    login = ConsoleLoginRequest(email="viewer@console.example", password=password)
    assert login.password == password
    reset = ConsoleTokenCompleteRequest(token=token, password=password)
    assert reset.password == password
    assert reset.token == token


def test_console_preserves_credential_spaces_without_bypassing_password_policy(report_console):
    data = report_console
    client = data["client"]
    password = "  PasswordWithSpaces123!  "
    raw = _link(data["messages"])
    response = client.post(
        "/api/platform-console/auth/invitations/complete",
        json={"token": raw, "password": password, "full_name": "Viewer"},
    )
    assert response.status_code == 400
    assert "Password must not contain whitespace." == response.json()["detail"]
    with get_session_factory()() as session:
        token = session.scalar(
            select(PlatformConsoleToken).where(
                PlatformConsoleToken.token_hash == console._digest(raw)
            )
        )
        assert token.consumed_at is None
        assert session.get(PlatformReportAdmin, data["manager_id"]).status == "pending"
    _accept(client, raw)
    _enroll(client)
    # A retained credential can predate today's password-setting policy.
    with get_session_factory()() as session:
        manager = session.get(PlatformReportAdmin, data["manager_id"])
        session.get(User, manager.user_id).password_hash = hash_password(password)
        session.commit()
    client.cookies.clear()
    assert client.post(
        "/api/platform-console/auth/login",
        json={"email": "manager@console.example", "password": password.strip()},
    ).status_code == 401
    response = client.post(
        "/api/platform-console/auth/login",
        json={"email": "manager@console.example", "password": password},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "mfa_challenge_required"


def _e2e_mail_settings(monkeypatch):
    monkeypatch.setenv("CASEOPS_E2E_OAUTH_EMULATOR", "calendar-20261008")
    for key in (
        "K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB", "GOOGLE_CLOUD_PROJECT"
    ):
        monkeypatch.delenv(key, raising=False)
    settings = get_settings().model_copy(
        update={"env": "e2e", "public_app_url": "http://127.0.0.1:3000", "sendgrid_api_key": None}
    )
    monkeypatch.setattr(console, "get_settings", lambda: settings)
    return settings


def test_e2e_mail_adapter_requires_guard_and_canonical_marker(report_console, monkeypatch):
    data = report_console
    _manager(data)
    _e2e_mail_settings(monkeypatch)
    provider_calls = []
    monkeypatch.setattr(console, "_send_via_sendgrid", lambda **kwargs: provider_calls.append(1))
    headers = {**_csrf(data["client"]), "X-CaseOps-Automated-Test": "no-paid-providers"}
    response = data["client"].post(
        "/api/platform-console/admins/invitations",
        headers=headers,
        json={"email": "viewer@console.example", "full_name": "Viewer"},
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "accepted"
    reset = data["client"].post(
        "/api/platform-console/auth/password-reset/start",
        headers=headers,
        json={"email": "manager@console.example"},
    )
    assert reset.json() == {"status": "accepted"}
    assert len(data["messages"]) == 3
    assert provider_calls == []


@pytest.mark.parametrize(
    "blocked",
    [
        "K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB", "GOOGLE_CLOUD_PROJECT",
        "missing_mode", "missing_marker", "wrong_marker", "sendgrid_key", "remote_sink",
        "public_origin",
    ],
)
def test_e2e_mail_adapter_rejects_cloud_or_incomplete_admission(
    report_console, monkeypatch, blocked
):
    data = report_console
    _manager(data)
    settings = _e2e_mail_settings(monkeypatch)
    headers = {**_csrf(data["client"]), "X-CaseOps-Automated-Test": "no-paid-providers"}
    if blocked.startswith(("K_", "CLOUD_", "GOOGLE_")):
        monkeypatch.setenv(blocked, "simulated-cloud-runtime")
    elif blocked == "missing_mode":
        monkeypatch.delenv("CASEOPS_E2E_OAUTH_EMULATOR")
    elif blocked == "missing_marker":
        headers.pop("X-CaseOps-Automated-Test")
    elif blocked == "wrong_marker":
        headers["X-CaseOps-Automated-Test"] = "not-the-canonical-marker"
    elif blocked == "sendgrid_key":
        settings.sendgrid_api_key = "offline-must-not-be-used"
    elif blocked == "remote_sink":
        monkeypatch.setenv("CASEOPS_CONSOLE_TEST_MAIL_URL", "http://mail.example:8129/messages")
    else:
        settings.public_app_url = "https://caseops.example"
    provider_calls = []
    monkeypatch.setattr(console, "_send_via_sendgrid", lambda **kwargs: provider_calls.append(1))
    response = data["client"].post(
        "/api/platform-console/admins/invitations",
        headers=headers,
        json={"email": "viewer@console.example", "full_name": "Viewer"},
    )
    assert response.status_code == 200
    assert response.json()["delivery_status"] == "failed"
    assert len(data["messages"]) == 1
    assert provider_calls == []


def test_e2e_mail_context_supports_guarded_non_http_bootstrap(report_console, monkeypatch):
    _e2e_mail_settings(monkeypatch)
    marker = set_automated_test_request("no-paid-providers")
    try:
        assert console._test_mail_ready(
            console.get_settings(), "http://127.0.0.1:8129/messages"
        )
    finally:
        reset_automated_test_request(marker)
    assert not console._test_mail_ready(
        console.get_settings(), "http://127.0.0.1:8129/messages"
    )


@pytest.mark.parametrize("reader", ["legacy", "console"])
def test_report_mrr_matches_each_subscription_interval_and_excludes_cancelled(
    report_console, reader
):
    data = report_console
    _manager(data)
    read = platform_overview if reader == "legacy" else overview
    with get_session_factory()() as session:
        before = read(session)
        plan = BillingPlanVersion(
            plan_code="mrr-interval-fixture", version="test-only", segment="law_firm",
            display_name="MRR interval fixture",
        )
        session.add(plan)
        session.flush()
        session.add_all([
            BillingPlanPrice(plan_version_id=plan.id, interval="month", amount_minor=12000),
            BillingPlanPrice(plan_version_id=plan.id, interval="year", amount_minor=120007),
        ])
        for interval, state in (
            ("month", BillingSubscriptionStatus.ACTIVE),
            ("year", BillingSubscriptionStatus.ACTIVE),
            ("year", BillingSubscriptionStatus.CANCELLED),
        ):
            company = Company(
                name=f"MRR {interval} {state}", slug=f"mrr-{interval}-{state}",
                tenant_key=f"mrr-{interval}-{state}", company_type="law_firm",
            )
            session.add(company)
            session.flush()
            session.add(BillingSubscription(
                company_id=company.id, plan_version_id=plan.id, segment="law_firm",
                billing_interval=interval, status=state,
            ))
        session.commit()
        actual = read(session)
        # Annual amounts normalize once to the nearest minor monthly unit.
        assert actual.mrr_minor == before.mrr_minor + 12000 + 10001
        assert actual.arr_minor == actual.mrr_minor * 12
        assert actual.active_subscriptions == before.active_subscriptions + 2
        expected_mrr = actual.mrr_minor
    if reader == "console":
        response = data["client"].get("/api/platform-console/reports/overview")
        assert response.status_code == 200
        assert response.json()["mrr_minor"] == expected_mrr
        assert response.json()["arr_minor"] == expected_mrr * 12
