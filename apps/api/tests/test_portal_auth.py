"""Phase C-1 (2026-04-24) — PortalUser + magic-link auth.

Covers FT-070, FT-071, FT-072, FT-075 from the PRD addendum.
"""
from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from caseops_api.api.routes import portal as portal_routes
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Matter,
    MatterPortalGrant,
    PortalMagicLink,
    PortalUser,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import portal_auth, portal_mailer
from tests.test_auth_company import auth_headers, bootstrap_company

# ----- helpers ---------------------------------------------------


def _seed_matter(company_id: str, *, code: str = "M-PRT-1") -> str:
    """Insert a minimal Matter row for the test to grant against."""
    Session = get_session_factory()
    with Session() as session:
        matter = Matter(
            company_id=company_id,
            client_name="Sample Client",
            title="Portal scope test matter",
            matter_code=code,
            status="active",
            practice_area="litigation",
            forum_level="high_court",
        )
        session.add(matter)
        session.commit()
        return matter.id


def _bootstrap_workspace(client: TestClient, *, slug: str, email: str) -> dict:
    client.cookies.clear()
    resp = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.title() + " LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Owner",
            "owner_email": email,
            "owner_password": "FoundersPass123!",
        },
    )
    assert resp.status_code == 200, resp.text
    client.cookies.clear()
    return resp.json()


def _set_runtime_env(monkeypatch: pytest.MonkeyPatch, runtime_env: str) -> None:
    monkeypatch.setenv("CASEOPS_ENV", runtime_env)
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    monkeypatch.setenv(
        "CASEOPS_AUTH_SECRET",
        "test-secret-should-be-at-least-32-bytes",
    )
    get_settings.cache_clear()


# ----- invite + verify happy path -------------------------------


def test_invite_then_request_then_verify_returns_session(
    client: TestClient,
) -> None:
    boot = _bootstrap_workspace(
        client, slug="portal-firm-a", email="firm@a.example",
    )
    token = str(boot["access_token"])
    company_id = boot["company"]["id"]
    matter_id = _seed_matter(company_id, code="M-A-1")

    # Owner invites a client portal user, scoping them to one matter.
    resp = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@example.com",
            "full_name": "Test Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    )
    assert resp.status_code == 201, resp.text
    invite = resp.json()
    assert invite["portal_user"]["role"] == "client"
    assert len(invite["grants"]) == 1
    assert invite["grants"][0]["matter_id"] == matter_id
    invite_token = invite["debug_token"]
    assert invite_token, "non-prod must surface debug_token"

    # The client requests another sign-in link to demonstrate that
    # the public request-link endpoint also works after invite.
    client.cookies.clear()
    resp = client.post(
        "/api/portal/auth/request-link",
        json={"company_slug": "portal-firm-a", "email": "client@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivered"] is True
    request_token = body["debug_token"]
    assert request_token, "non-prod request-link must surface debug_token"

    # Verify the request-link token (we could verify the invite_token
    # too — both are valid until expiry / consumption).
    resp = client.post(
        "/api/portal/auth/verify-link", json={"token": request_token},
    )
    assert resp.status_code == 200, resp.text
    session_body = resp.json()
    assert session_body["portal_user"]["email"] == "client@example.com"
    assert session_body["portal_user"]["role"] == "client"
    assert [g["matter_id"] for g in session_body["grants"]] == [matter_id]
    assert "caseops_portal_session" in resp.cookies

    # GET /me returns the same portal user + grants when called with
    # the cookie that verify-link just set.
    resp = client.get("/api/portal/me")
    assert resp.status_code == 200
    me = resp.json()
    assert me["portal_user"]["id"] == session_body["portal_user"]["id"]


# ----- enumeration defence + replay protection -------------------


def test_request_link_for_unknown_email_still_returns_200(
    client: TestClient,
) -> None:
    """FT-070 enumeration defence — outward shape MUST NOT change
    based on whether the email matches a real portal user."""
    boot = _bootstrap_workspace(
        client, slug="enum-firm", email="enum@example.com",
    )
    assert boot["company"]["slug"] == "enum-firm"
    client.cookies.clear()

    resp = client.post(
        "/api/portal/auth/request-link",
        json={"company_slug": "enum-firm", "email": "ghost@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivered"] is True
    assert body.get("debug_token") is None


def test_verify_link_is_single_use(client: TestClient) -> None:
    """FT-070 single-use guarantee — same token cannot verify twice."""
    boot = _bootstrap_workspace(
        client, slug="replay-firm", email="firm@replay.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-RP-1")

    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@replay.example",
            "full_name": "Replay Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    ).json()
    invite_token = invite["debug_token"]

    client.cookies.clear()
    first = client.post(
        "/api/portal/auth/verify-link", json={"token": invite_token},
    )
    assert first.status_code == 200

    # Second use of the same token must fail.
    client.cookies.clear()
    second = client.post(
        "/api/portal/auth/verify-link", json={"token": invite_token},
    )
    assert second.status_code == 400


def test_verify_link_rejects_expired_token(client: TestClient) -> None:
    boot = _bootstrap_workspace(
        client, slug="expiry-firm", email="firm@expiry.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-EX-1")

    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@expiry.example",
            "full_name": "Expiring Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    ).json()
    invite_token = invite["debug_token"]

    # Force the magic-link row's expiry into the past.
    Session = get_session_factory()
    with Session() as session:
        link = (
            session.query(PortalMagicLink)
            .filter(
                PortalMagicLink.portal_user_id
                == invite["portal_user"]["id"],
            )
            .first()
        )
        link.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()

    client.cookies.clear()
    resp = client.post(
        "/api/portal/auth/verify-link", json={"token": invite_token},
    )
    assert resp.status_code == 400


# ----- tenant isolation + cross-surface rejection ---------------


def test_portal_session_token_is_rejected_by_internal_app(
    client: TestClient,
) -> None:
    """FT-071 cross-surface rejection — a portal session JWT placed
    in the internal session cookie name must not satisfy /api/auth
    or any internal endpoint."""
    boot = _bootstrap_workspace(
        client, slug="cross-firm", email="firm@cross.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-XS-1")

    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@cross.example",
            "full_name": "Cross-surface Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    ).json()
    invite_token = invite["debug_token"]

    client.cookies.clear()
    verify = client.post(
        "/api/portal/auth/verify-link", json={"token": invite_token},
    )
    assert verify.status_code == 200
    portal_session = verify.cookies["caseops_portal_session"]

    # Try to use the portal JWT to authenticate against the internal
    # app surface by injecting it as the ``caseops_session`` cookie.
    client.cookies.clear()
    client.cookies.set("caseops_session", portal_session)
    resp = client.get("/api/companies/me")
    # Anything other than 200 is acceptable; the assertion is that
    # the portal JWT did NOT satisfy internal auth.
    assert resp.status_code in (401, 403, 404)


def test_grants_are_tenant_isolated(client: TestClient) -> None:
    """FT-072 tenant isolation — Tenant A's portal user must never
    see a matter that belongs to Tenant B's workspace."""
    boot_a = _bootstrap_workspace(
        client, slug="iso-a", email="firm@iso-a.example",
    )
    token_a = str(boot_a["access_token"])
    matter_a = _seed_matter(boot_a["company"]["id"], code="M-ISO-A")

    boot_b = _bootstrap_workspace(
        client, slug="iso-b", email="firm@iso-b.example",
    )
    token_b = str(boot_b["access_token"])
    matter_b = _seed_matter(boot_b["company"]["id"], code="M-ISO-B")

    # Tenant A invites a portal user scoped to matter_a only.
    invite_a = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token_a),
        json={
            "email": "iso-client@example.com",
            "full_name": "Iso Client",
            "role": "client",
            "matter_ids": [matter_a],
        },
    ).json()

    # Tenant B inviting under the same email lands a SEPARATE portal
    # user (uniqueness is per-company, not global).
    invite_b = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token_b),
        json={
            "email": "iso-client@example.com",
            "full_name": "Iso Client B",
            "role": "client",
            "matter_ids": [matter_b],
        },
    ).json()
    assert invite_a["portal_user"]["id"] != invite_b["portal_user"]["id"]

    # Verify Tenant A's portal user — they MUST see only matter_a.
    client.cookies.clear()
    verify_a = client.post(
        "/api/portal/auth/verify-link",
        json={"token": invite_a["debug_token"]},
    )
    assert verify_a.status_code == 200
    grants_a = [g["matter_id"] for g in verify_a.json()["grants"]]
    assert matter_a in grants_a
    assert matter_b not in grants_a


# ----- grant revocation -----------------------------------------


def test_revoking_grant_removes_it_from_me(client: TestClient) -> None:
    """FT-075 revoke-on-grant — flipping ``revoked_at`` removes the
    grant from /me on the next request."""
    boot = _bootstrap_workspace(
        client, slug="revoke-firm", email="firm@revoke.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-RV-1")
    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@revoke.example",
            "full_name": "Revoke Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    ).json()

    client.cookies.clear()
    verify = client.post(
        "/api/portal/auth/verify-link",
        json={"token": invite["debug_token"]},
    )
    assert verify.status_code == 200
    assert len(verify.json()["grants"]) == 1

    # Revoke the grant directly in the DB (admin revoke route lands
    # in C-2; for now the unit test exercises the read path).
    Session = get_session_factory()
    with Session() as session:
        grant = (
            session.query(MatterPortalGrant)
            .filter(
                MatterPortalGrant.portal_user_id
                == invite["portal_user"]["id"],
            )
            .first()
        )
        grant.revoked_at = datetime.now(UTC)
        session.commit()

    me = client.get("/api/portal/me")
    assert me.status_code == 200
    assert me.json()["grants"] == []


# ----- duplicate invite under different role rejected -----------


def test_invite_same_email_different_role_returns_409(
    client: TestClient,
) -> None:
    boot = _bootstrap_workspace(
        client, slug="role-firm", email="firm@role.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-RL-1")

    first = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "dual@example.com",
            "full_name": "Dual Role",
            "role": "client",
            "matter_ids": [matter_id],
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "dual@example.com",
            "full_name": "Dual Role",
            "role": "outside_counsel",
            "matter_ids": [matter_id],
        },
    )
    assert second.status_code == 409


# ----- /me without cookie -> 401 ---------------------------------


def test_me_without_portal_cookie_returns_401(client: TestClient) -> None:
    client.cookies.clear()
    resp = client.get("/api/portal/me")
    assert resp.status_code == 401


# ----- C-1 hardening (2026-04-24): the gates the user wants ---------


def test_request_link_for_unknown_company_slug_still_returns_200(
    client: TestClient,
) -> None:
    """Enumeration defence MUST cover company_slug too — not just
    email. Otherwise an attacker probes for valid workspace handles."""
    client.cookies.clear()
    resp = client.post(
        "/api/portal/auth/request-link",
        json={
            "company_slug": "ghost-firm-9999",
            "email": "anyone@example.com",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["delivered"] is True
    assert body.get("debug_token") is None


def test_invite_requires_admin_capability(client: TestClient) -> None:
    """portal:invite is owner/admin only. A partner / member call
    must 403."""
    boot = _bootstrap_workspace(
        client, slug="cap-firm", email="firm@cap.example",
    )
    owner_token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-CAP-1")

    # Add a non-admin membership directly (no UI for this in C-1).
    Session = get_session_factory()
    from caseops_api.db.models import (
        CompanyMembership,
        MembershipRole,
        User,
    )
    with Session() as session:
        user = User(
            email="partner@cap.example",
            full_name="Partner User",
            password_hash="dummy",
            is_active=True,
        )
        session.add(user)
        session.flush()
        partner = CompanyMembership(
            company_id=boot["company"]["id"],
            user_id=user.id,
            role=MembershipRole.PARTNER.value,
            is_active=True,
        )
        session.add(partner)
        session.commit()
        partner_membership_id = partner.id

    # Sign in the partner and try to invite — must 403.
    from caseops_api.core.security import create_access_token
    partner_jwt = create_access_token(
        user_id=user.id,
        company_id=boot["company"]["id"],
        membership_id=partner_membership_id,
        role=MembershipRole.PARTNER.value,
    )
    resp = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(partner_jwt),
        json={
            "email": "denied@example.com",
            "full_name": "Denied",
            "role": "client",
            "matter_ids": [matter_id],
        },
    )
    assert resp.status_code == 403, resp.text
    # The owner can still invite — sanity that the gate isn't broken.
    ok = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(owner_token),
        json={
            "email": "ok@example.com",
            "full_name": "OK Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    )
    assert ok.status_code == 201


def test_invite_with_empty_matter_ids_returns_400(client: TestClient) -> None:
    boot = _bootstrap_workspace(
        client, slug="empty-matter", email="firm@empty.example",
    )
    token = str(boot["access_token"])
    resp = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@empty.example",
            "full_name": "Empty Scope",
            "role": "client",
            "matter_ids": [],
        },
    )
    assert resp.status_code == 400


def test_invite_with_unknown_role_returns_422(client: TestClient) -> None:
    boot = _bootstrap_workspace(
        client, slug="bad-role", email="firm@bad.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-BR-1")
    resp = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@bad.example",
            "full_name": "Bad Role",
            "role": "admin",  # not in {client, outside_counsel}
            "matter_ids": [matter_id],
        },
    )
    assert resp.status_code == 422


def test_logout_clears_portal_cookie_and_is_idempotent(
    client: TestClient,
) -> None:
    boot = _bootstrap_workspace(
        client, slug="logout-firm", email="firm@logout.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-LO-1")
    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@logout.example",
            "full_name": "Logout Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    ).json()
    client.cookies.clear()
    verify = client.post(
        "/api/portal/auth/verify-link",
        json={"token": invite["debug_token"]},
    )
    assert verify.status_code == 200
    assert client.cookies.get("caseops_portal_session")

    # First logout returns 204 and clears the cookie.
    out = client.post("/api/portal/auth/logout")
    assert out.status_code == 204
    # Second logout (no cookie) is still 204 — idempotent.
    client.cookies.clear()
    out2 = client.post("/api/portal/auth/logout")
    assert out2.status_code == 204


def test_forged_portal_cookie_is_rejected(client: TestClient) -> None:
    """A garbage cookie value must not satisfy /api/portal/me."""
    client.cookies.clear()
    client.cookies.set("caseops_portal_session", "not-a-real-jwt")
    resp = client.get("/api/portal/me")
    assert resp.status_code == 401


def test_internal_session_cookie_is_rejected_by_portal(
    client: TestClient,
) -> None:
    """FT-071 inverse: an internal /app session JWT placed in the
    PORTAL cookie must NOT satisfy /api/portal/me."""
    boot = _bootstrap_workspace(
        client, slug="inv-firm", email="firm@inv.example",
    )
    internal_jwt = str(boot["access_token"])
    client.cookies.clear()
    client.cookies.set("caseops_portal_session", internal_jwt)
    resp = client.get("/api/portal/me")
    assert resp.status_code == 401


def test_sessions_valid_after_invalidates_existing_session(
    client: TestClient,
) -> None:
    """Setting PortalUser.sessions_valid_after to now must reject
    any session JWT issued before that timestamp on the next request."""
    boot = _bootstrap_workspace(
        client, slug="rev-firm", email="firm@rev.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-SV-1")
    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@rev.example",
            "full_name": "Revocation Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    ).json()
    client.cookies.clear()
    verify = client.post(
        "/api/portal/auth/verify-link",
        json={"token": invite["debug_token"]},
    )
    assert verify.status_code == 200
    assert client.get("/api/portal/me").status_code == 200

    # Bump sessions_valid_after by a comfortable margin (10s) to
    # account for clock granularity between the JWT iat and now().
    from datetime import timedelta

    Session = get_session_factory()
    with Session() as session:
        portal_user = session.get(PortalUser, invite["portal_user"]["id"])
        portal_user.sessions_valid_after = datetime.now(UTC) + timedelta(
            seconds=10
        )
        session.commit()

    resp = client.get("/api/portal/me")
    assert resp.status_code == 401


def test_invite_writes_audit_event(client: TestClient) -> None:
    """portal.invited audit row must land for every successful invite."""
    boot = _bootstrap_workspace(
        client, slug="audit-firm", email="firm@audit.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-AUD-1")
    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@audit.example",
            "full_name": "Audit Client",
            "role": "client",
            "matter_ids": [matter_id],
        },
    )
    assert invite.status_code == 201
    portal_user_id = invite.json()["portal_user"]["id"]

    Session = get_session_factory()
    from caseops_api.db.models import AuditEvent
    with Session() as session:
        rows = (
            session.query(AuditEvent)
            .filter(
                AuditEvent.action == "portal.invited",
                AuditEvent.target_id == portal_user_id,
            )
            .all()
        )
        assert len(rows) == 1
        assert rows[0].company_id == boot["company"]["id"]


def test_verify_writes_audit_event(client: TestClient) -> None:
    """portal.signed_in audit row must land on each successful verify."""
    boot = _bootstrap_workspace(
        client, slug="audit-v-firm", email="firm@audit-v.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-AUDV-1")
    invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json={
            "email": "client@audit-v.example",
            "full_name": "Audit V",
            "role": "client",
            "matter_ids": [matter_id],
        },
    ).json()

    client.cookies.clear()
    verify = client.post(
        "/api/portal/auth/verify-link",
        json={"token": invite["debug_token"]},
    )
    assert verify.status_code == 200

    Session = get_session_factory()
    from caseops_api.db.models import AuditEvent
    with Session() as session:
        rows = (
            session.query(AuditEvent)
            .filter(
                AuditEvent.action == "portal.signed_in",
                AuditEvent.target_id == invite["portal_user"]["id"],
            )
            .all()
        )
        assert len(rows) == 1


@pytest.mark.parametrize(
    "runtime_env",
    ["cloud", "staging", "custom-managed-runtime"],
)
def test_portal_mailer_sends_in_every_non_local_environment(
    monkeypatch: pytest.MonkeyPatch,
    runtime_env: str,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(status_code=202, text="")

    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "sendgrid-test-key")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "security@example.com")
    _set_runtime_env(monkeypatch, runtime_env)
    monkeypatch.setattr(portal_mailer.httpx, "post", fake_post)

    delivered, error = portal_mailer.send_portal_magic_link(
        to_email="portal@example.com",
        full_name="Portal User",
        company_display_name="Example LLP",
        token="one-time-secret",
    )

    assert delivered is True
    assert error is None
    assert len(calls) == 1


def test_managed_environments_hide_request_and_invitation_tokens(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = _bootstrap_workspace(
        client,
        slug="managed-portal-firm",
        email="owner@managed-portal.example",
    )
    owner_token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-MANAGED-1")
    local_invite = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(owner_token),
        json={
            "email": "existing@managed-portal.example",
            "full_name": "Existing Portal User",
            "role": "client",
            "matter_ids": [matter_id],
        },
    )
    assert local_invite.status_code == 201, local_invite.text
    assert local_invite.json()["debug_token"]

    delivery_calls: list[str] = []

    def fake_send(**kwargs):  # type: ignore[no-untyped-def]
        delivery_calls.append(str(kwargs["to_email"]))
        return True, None

    monkeypatch.setattr(portal_routes, "send_portal_magic_link", fake_send)

    for index, runtime_env in enumerate(
        ("cloud", "staging", "custom-managed-runtime"),
    ):
        _set_runtime_env(monkeypatch, runtime_env)
        client.cookies.clear()
        request_link = client.post(
            "/api/portal/auth/request-link",
            json={
                "company_slug": "managed-portal-firm",
                "email": "existing@managed-portal.example",
            },
        )
        assert request_link.status_code == 200, request_link.text
        assert request_link.json()["debug_token"] is None

        invitation = client.post(
            "/api/admin/portal/invitations",
            headers=auth_headers(owner_token),
            json={
                "email": f"managed-{index}@example.com",
                "full_name": "Managed Portal User",
                "role": "client",
                "matter_ids": [matter_id],
            },
        )
        assert invitation.status_code == 201, invitation.text
        assert invitation.json()["debug_token"] is None

    assert len(delivery_calls) == 6


def test_invitation_rejects_foreign_tenant_matter_before_mutation(
    client: TestClient,
) -> None:
    tenant_a = _bootstrap_workspace(
        client,
        slug="invite-scope-a",
        email="owner@invite-scope-a.example",
    )
    tenant_b = _bootstrap_workspace(
        client,
        slug="invite-scope-b",
        email="owner@invite-scope-b.example",
    )
    matter_a = _seed_matter(tenant_a["company"]["id"], code="M-SCOPE-A")
    matter_b = _seed_matter(tenant_b["company"]["id"], code="M-SCOPE-B")
    invite_email = "foreign-scope@example.com"

    response = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(str(tenant_a["access_token"])),
        json={
            "email": invite_email,
            "full_name": "Foreign Scope",
            "role": "client",
            "matter_ids": [matter_a, matter_b],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Matter not found."
    Session = get_session_factory()
    with Session() as session:
        assert session.query(PortalUser).filter(PortalUser.email == invite_email).first() is None


def test_reinvite_deduplicates_matters_and_tightens_grant_scope(
    client: TestClient,
) -> None:
    boot = _bootstrap_workspace(
        client,
        slug="reinvite-scope",
        email="owner@reinvite-scope.example",
    )
    token = str(boot["access_token"])
    matter_id = _seed_matter(boot["company"]["id"], code="M-REINVITE-1")
    payload = {
        "email": "outside-counsel@reinvite.example",
        "full_name": "Outside Counsel",
        "role": "outside_counsel",
        "matter_ids": [matter_id],
        "can_upload": True,
        "can_invoice": True,
        "can_reply": True,
    }
    first = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json=payload,
    )
    assert first.status_code == 201, first.text

    payload.update(
        matter_ids=[matter_id, matter_id],
        can_upload=False,
        can_invoice=False,
        can_reply=False,
    )
    second = client.post(
        "/api/admin/portal/invitations",
        headers=auth_headers(token),
        json=payload,
    )
    assert second.status_code == 201, second.text
    grants = second.json()["grants"]
    assert len(grants) == 1
    assert grants[0]["scope_json"] == {
        "can_upload": False,
        "can_invoice": False,
        "can_reply": False,
    }

    Session = get_session_factory()
    with Session() as session:
        rows = session.query(MatterPortalGrant).filter(
            MatterPortalGrant.portal_user_id == second.json()["portal_user"]["id"],
            MatterPortalGrant.matter_id == matter_id,
        ).all()
        assert len(rows) == 1
        assert rows[0].scope_json == grants[0]["scope_json"]


def test_magic_link_consumption_uses_an_atomic_conditional_claim() -> None:
    source = inspect.getsource(portal_auth.verify_magic_link)
    assert "update(PortalMagicLink)" in source
    assert "PortalMagicLink.consumed_at.is_(None)" in source
    assert "PortalMagicLink.expires_at > now" in source
    assert "claim_result.rowcount != 1" in source


# ----- silence pyflakes for the imported PortalUser symbol ------
_ = PortalUser
_ = bootstrap_company
