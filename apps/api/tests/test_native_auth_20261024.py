"""J20/M22 MOB-01..06: native authority does not inherit cookie privileges."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import func, inspect, select

from caseops_api.core.native_auth import (
    LOCAL_REDIRECT,
    NATIVE_ACCESS_PREFIX,
    decode_native_access_token,
    signing_key,
)
from caseops_api.core.security import TokenValidationError, decode_access_token
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    NativeAuthorizationCode,
    NativeDeviceSession,
    NativeRefreshToken,
    TenantSecurityPolicy,
    User,
    UserMFASetting,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import native_auth
from tests.test_auth_company import bootstrap_company

BASE = "/api/auth/native"
VERIFIER = "v" * 64
STATE = "s" * 32


def _browser(client):
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    client.headers["X-CaseOps-Client"] = "native"
    auth = bootstrap_company(client)
    csrf = client.cookies.get("caseops_csrf")
    client.cookies.clear()
    headers = {
        "Cookie": f"caseops_session={auth['access_token']}; caseops_csrf={csrf}",
        "X-CSRF-Token": csrf,
        "X-CaseOps-Automated-Test": "no-paid-providers",
    }
    return auth, headers


def _authorize(client, browser_headers, **changes):
    payload = {
        "code_challenge": native_auth.pkce_challenge(VERIFIER),
        "state": STATE,
        "platform": "android",
        "redirect_uri": LOCAL_REDIRECT,
    }
    payload.update(changes)
    return client.post("/api/auth/native/authorize", headers=browser_headers, json=payload)


def _exchange(client, code, **changes):
    payload = {
        "code": code,
        "code_verifier": VERIFIER,
        "platform": "android",
        "redirect_uri": LOCAL_REDIRECT,
    }
    payload.update(changes)
    return client.post("/api/auth/native/token", json=payload)


def _device(client, browser_headers):
    grant = _authorize(client, browser_headers)
    assert grant.status_code == 200, grant.text
    response = _exchange(client, grant.json()["code"])
    assert response.status_code == 200, response.text
    return response.json()


def _headers(device):
    return {"Authorization": "Bearer " + device["access_token"]}


def _assert_no_native_issuance():
    with get_session_factory()() as session:
        for model in (NativeAuthorizationCode, NativeDeviceSession, NativeRefreshToken):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_native_authorize_response_expiry_schema_bounds():
    from pydantic import ValidationError

    from caseops_api.schemas.native_auth import NativeAuthorizeResponse

    base = {"code": "c" * 43, "state": STATE, "redirect_uri": LOCAL_REDIRECT}
    for ttl in (15, 60, 120):
        assert NativeAuthorizeResponse(**base, expires_in=ttl).model_dump() == {
            **base, "expires_in": ttl,
        }
    for ttl in (14, 121, None, 15.5, "15", 15.0, True, False):
        with pytest.raises(ValidationError):
            NativeAuthorizeResponse(**base, expires_in=ttl)
    with pytest.raises(ValidationError):
        NativeAuthorizeResponse(**base)
    schema = NativeAuthorizeResponse.model_json_schema()
    assert "expires_in" in schema["required"]
    assert schema["properties"]["expires_in"] == {
        "type": "integer", "title": "Expires In", "minimum": 15, "maximum": 120,
    }


@pytest.mark.parametrize("ttl", [15, 60, 120])
def test_native_authorize_expiry_matches_configured_deadline_and_retains_pkce(
    client, monkeypatch, ttl,
):
    auth, browser = _browser(client)
    monkeypatch.setenv("CASEOPS_NATIVE_CODE_TTL_SECONDS", str(ttl))
    get_settings.cache_clear()
    assert get_settings().native_code_ttl_seconds == ttl
    clock = [datetime.now(UTC)]
    monkeypatch.setattr(native_auth, "_now", lambda: clock[0])
    captured_at = clock[0]
    reads = []

    def settings_snapshot():
        reads.append(True)
        return get_settings()

    with monkeypatch.context() as capture:
        capture.setattr(native_auth, "get_settings", settings_snapshot)
        grant = _authorize(client, browser)
    assert grant.status_code == 200, grant.text
    assert reads == [True]
    payload = grant.json()
    assert set(payload) == {"code", "state", "redirect_uri", "expires_in"}
    assert payload["expires_in"] == ttl
    assert payload["state"] == STATE
    assert payload["redirect_uri"] == LOCAL_REDIRECT
    deadline = captured_at + timedelta(seconds=payload["expires_in"])
    with get_session_factory()() as session:
        stored = session.scalar(select(NativeAuthorizationCode))
        assert native_auth._aware(stored.expires_at) == deadline
        assert stored.consumed_at is None
        assert stored.code_hash == native_auth._hash(payload["code"])
        assert session.scalar(select(func.count()).select_from(NativeDeviceSession)) == 0
    clock[0] = deadline - timedelta(microseconds=1)
    wrong = _exchange(client, payload["code"], code_verifier="x" * 64)
    assert wrong.status_code == 401, wrong.text
    with get_session_factory()() as session:
        assert session.scalar(select(NativeAuthorizationCode)).consumed_at is None
    exchanged = _exchange(client, payload["code"])
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["membership"]["id"] == auth["membership"]["id"]
    assert _exchange(client, payload["code"]).status_code == 401
    # A separate, never-consumed code expires at the exact advertised boundary.
    clock[0] = captured_at
    second = _authorize(client, browser)
    assert second.status_code == 200, second.text
    assert second.json()["expires_in"] == ttl
    for now in (deadline, deadline + timedelta(microseconds=1)):
        clock[0] = now
        assert _exchange(client, second.json()["code"]).status_code == 401
        assert _exchange(client, payload["code"]).status_code == 401
    with get_session_factory()() as session:
        expired = session.scalar(select(NativeAuthorizationCode).where(
            NativeAuthorizationCode.code_hash == native_auth._hash(second.json()["code"]),
        ))
        assert native_auth._aware(expired.expires_at) == deadline
        assert expired.consumed_at is None
        assert session.scalar(select(func.count()).select_from(NativeDeviceSession)) == 1
        assert session.scalar(select(func.count()).select_from(NativeRefreshToken)) == 1


def test_optional_policy_native_mfa_requires_same_browser_proof_and_explicit_recovery(client):
    import time

    from caseops_api.services.security import TOTP_PERIOD_SECONDS, _hotp

    auth, original_browser = _browser(client)
    with get_session_factory()() as session:
        session.add(TenantSecurityPolicy(
            company_id=auth["company"]["id"], all_users_mfa_required=False,
            tenant_admin_mfa_required=False,
        ))
        session.commit()
    enrollment = client.post("/api/auth/mfa/enroll", headers=original_browser)
    assert enrollment.status_code == 200, enrollment.text
    secret = enrollment.json()["secret"]
    verified = client.post(
        "/api/auth/mfa/enroll/verify", headers=original_browser,
        json={"code": _hotp(secret, int(time.time()) // TOTP_PERIOD_SECONDS)},
    )
    assert verified.status_code == 200, verified.text
    _assert_no_native_issuance()
    login = client.post("/api/auth/login", json={
        "email": "owner@asterlegal.in", "password": "FoundersPass123!",
        "company_slug": "aster-legal",
    })
    assert login.status_code == 200, login.text
    assert login.json()["mfa_challenge_required"] is False
    token = login.json()["access_token"]
    issued = float(decode_access_token(token)["issued_at_precise"])
    assert issued != float(decode_access_token(auth["access_token"])["issued_at_precise"])
    csrf = client.cookies.get("caseops_csrf")
    browser = {
        "Cookie": f"caseops_session={token}; caseops_csrf={csrf}",
        "X-CSRF-Token": csrf,
    }
    client.cookies.clear()

    def refused():
        response = _authorize(client, browser)
        assert response.status_code == 403, response.text
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["type"] == "native_mfa_required", response.text
        assert response.json()["detail"] == (
            "Complete MFA in this browser session before native sign-in."
        )
        _assert_no_native_issuance()

    # Enrollment proved the older browser, never this newly logged-in token.
    refused()
    wrong = client.post(
        "/api/auth/mfa/step-up", headers=browser,
        json={"code": "not-a-real-recovery-code", "method": "recovery_code", "purpose": "step_up"},
    )
    assert wrong.status_code == 403, wrong.text
    assert wrong.json()["type"] != "native_mfa_required"
    refused()
    for stale in ("before-token", "expired"):
        with get_session_factory()() as session:
            proof = session.scalar(select(UserMFAStepUp))
            proof.source_token_issued_at = issued
            proof.completed_at = (
                datetime.fromtimestamp(issued, UTC) - timedelta(seconds=1)
                if stale == "before-token" else datetime.now(UTC)
            )
            proof.expires_at = datetime.now(UTC) + timedelta(
                seconds=300 if stale == "before-token" else -1
            )
            session.commit()
        refused()
    ordinary = _authorize(client, {"Cookie": browser["Cookie"]})
    assert ordinary.status_code == 403, ordinary.text
    assert ordinary.json()["type"] != "native_mfa_required"
    stepped = client.post(
        "/api/auth/mfa/step-up", headers=browser,
        json={"code": _hotp(secret, int(time.time()) // TOTP_PERIOD_SECONDS), "purpose": "step_up"},
    )
    assert stepped.status_code == 200, stepped.text
    _assert_no_native_issuance()
    grant = _authorize(client, browser)
    assert grant.status_code == 200, grant.text
    with get_session_factory()() as session:
        code = session.scalar(select(NativeAuthorizationCode))
        assert code.source_issued_at == issued
        assert code.consumed_at is None
        assert session.scalar(select(func.count()).select_from(NativeDeviceSession)) == 0
    exchanged = _exchange(client, grant.json()["code"])
    assert exchanged.status_code == 200, exchanged.text
    assert client.get("/api/auth/me", headers=_headers(exchanged.json())).status_code == 200
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(NativeDeviceSession)) == 1
        assert session.scalar(select(NativeAuthorizationCode)).consumed_at is not None


@pytest.mark.parametrize("enrolled", [False, True])
def test_required_policy_native_mfa_proof_refusal_is_typed_without_grants(client, enrolled):
    from caseops_api.core.problem_details import ProblemHTTPException
    from caseops_api.schemas.native_auth import NativeAuthorizeRequest
    from caseops_api.services.identity import get_session_context

    auth, _ = _browser(client)
    with get_session_factory()() as session:
        session.add(TenantSecurityPolicy(
            company_id=auth["company"]["id"], all_users_mfa_required=True,
            mfa_enforced_at=datetime.now(UTC) - timedelta(minutes=1),
        ))
        if enrolled:
            session.add(UserMFASetting(user_id=auth["user"]["id"], status="enrolled"))
        session.commit()
        context = get_session_context(
            session, auth["membership"]["id"],
            token_issued_at=float(decode_access_token(auth["access_token"])["issued_at_precise"]),
        )
        with pytest.raises(ProblemHTTPException) as error:
            native_auth.authorize(session, context, NativeAuthorizeRequest(
                code_challenge=native_auth.pkce_challenge(VERIFIER), state=STATE,
                platform="android", redirect_uri=LOCAL_REDIRECT,
            ))
        assert error.value.status_code == 403
        assert error.value.problem_type == "native_mfa_required"
        assert error.value.detail == "Complete MFA in the browser before native sign-in."
        session.rollback()
    _assert_no_native_issuance()


def test_pkce_handoff_has_canonical_context_and_only_hashed_secrets(client):
    auth, browser = _browser(client)
    grant = _authorize(client, browser)
    assert grant.status_code == 200, grant.text
    assert grant.headers["Cache-Control"] == "no-store"
    assert grant.json()["state"] == STATE
    assert grant.json()["redirect_uri"] == LOCAL_REDIRECT
    response = _exchange(client, grant.json()["code"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] == 300
    assert body["token_type"] == "bearer"
    for key in ("company", "user", "membership", "capabilities"):
        assert body[key] == auth[key]
    assert not response.headers.get("set-cookie")
    with get_session_factory()() as session:
        code = session.scalar(select(NativeAuthorizationCode))
        refresh = session.scalar(select(NativeRefreshToken))
        assert code.code_hash == native_auth._hash(grant.json()["code"])
        assert code.code_hash != grant.json()["code"]
        assert code.consumed_at is not None
        assert refresh.token_hash == native_auth._hash(body["refresh_token"])
        assert refresh.token_hash != body["refresh_token"]
        columns = inspect(session.bind).get_columns("native_refresh_tokens")
        assert "refresh_token" not in {column["name"] for column in columns}
    profile = client.get("/api/companies/current/profile", headers=_headers(body))
    assert profile.status_code == 200, profile.text
    assert profile.json()["id"] == auth["company"]["id"]
    assert _exchange(client, grant.json()["code"]).status_code == 401
    with pytest.raises(TokenValidationError):
        decode_access_token(body["access_token"])


@pytest.mark.parametrize(
    "changes",
    [
        {"code_verifier": "wrong" * 13},
        {"platform": "ios"},
        {"redirect_uri": "caseops://oauth/callback?return=https://attacker.invalid"},
    ],
)
def test_handoff_binds_verifier_platform_and_exact_redirect(client, changes):
    _, browser = _browser(client)
    grant = _authorize(client, browser).json()
    rejected = _exchange(client, grant["code"], **changes)
    assert rejected.status_code == (400 if "redirect_uri" in changes else 401)
    assert rejected.headers["Cache-Control"] == "no-store"
    assert _exchange(client, grant["code"]).status_code == 200


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_registered_https_handoff_exchanges_once_under_nonlocal_native_policy(
    client, monkeypatch, platform,
):
    import secrets

    from pydantic import SecretStr

    auth, browser = _browser(client)
    callback = "https://native.example.org/native/oauth/callback"
    other_callback = "https://native.example.org/native/oauth/other-callback"
    # Exercise the real HTTP endpoints with production native issuance rules.
    # The database, browser bootstrap and transports remain the offline fixture;
    # this does not claim a signed app or deployed-domain association.
    settings = get_settings().model_copy(update={
        "env": "production",
        "native_auth_enabled": True,
        "native_signing_enabled": True,
        "native_signing_secret": SecretStr(secrets.token_hex(32)),
        "native_redirect_uris": [callback, other_callback],
    })
    monkeypatch.setattr("caseops_api.core.native_auth.get_settings", lambda: settings)
    custom_scheme = _authorize(client, browser, platform=platform)
    assert custom_scheme.status_code == 400
    _assert_no_native_issuance()
    grant = _authorize(client, browser, platform=platform, redirect_uri=callback)
    assert grant.status_code == 200, grant.text
    assert grant.json()["redirect_uri"] == callback
    assert grant.json()["state"] == STATE
    code = grant.json()["code"]
    for changes in (
        {"redirect_uri": other_callback},
        {"platform": "ios" if platform == "android" else "android"},
        {"code_verifier": "w" * 64},
    ):
        rejected = _exchange(
            client, code, **{"platform": platform, "redirect_uri": callback, **changes},
        )
        assert rejected.status_code == 401
        assert rejected.headers["Cache-Control"] == "no-store"
        with get_session_factory()() as session:
            stored = session.scalar(select(NativeAuthorizationCode))
            assert stored.consumed_at is None
            assert session.scalar(select(func.count()).select_from(NativeDeviceSession)) == 0
    exchanged = _exchange(client, code, platform=platform, redirect_uri=callback)
    assert exchanged.status_code == 200, exchanged.text
    assert exchanged.json()["membership"]["id"] == auth["membership"]["id"]
    assert exchanged.headers["Cache-Control"] == "no-store"
    assert not exchanged.headers.get("set-cookie")
    principal = client.get("/api/auth/me", headers=_headers(exchanged.json()))
    assert principal.status_code == 200
    assert principal.json()["user"]["id"] == auth["user"]["id"]
    replay = _exchange(client, code, platform=platform, redirect_uri=callback)
    assert replay.status_code == 401
    with get_session_factory()() as session:
        assert session.scalar(select(NativeAuthorizationCode)).consumed_at is not None
        assert session.scalar(select(func.count()).select_from(NativeDeviceSession)) == 1
        assert session.scalar(select(func.count()).select_from(NativeRefreshToken)) == 1


def test_authorize_requires_cookie_csrf_and_never_native_authority(client):
    auth, browser = _browser(client)
    assert _authorize(client, {}).status_code == 403
    assert (
        _authorize(client, {"Authorization": "Bearer " + auth["access_token"]}).status_code == 401
    )
    no_csrf = {"Cookie": browser["Cookie"]}
    assert _authorize(client, no_csrf).status_code == 403
    device = _device(client, browser)
    assert _authorize(client, _headers(device)).status_code == 401


@pytest.mark.parametrize(
    "redirect",
    [
        "https://attacker.invalid/oauth/callback",
        "caseops://oauth/callback/",
        "caseops://oauth/callback#fragment",
        "CASEOPS://oauth/callback",
        "//attacker.invalid",
    ],
)
def test_development_redirect_is_one_exact_provisional_uri(client, redirect):
    _, browser = _browser(client)
    assert _authorize(client, browser, redirect_uri=redirect).status_code == 400


def test_expired_code_is_unusable(client):
    _, browser = _browser(client)
    grant = _authorize(client, browser).json()
    with get_session_factory()() as session:
        code = session.scalar(select(NativeAuthorizationCode))
        code.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert _exchange(client, grant["code"]).status_code == 401


def test_rotation_survives_access_expiry_and_replay_durably_revokes_family(client):
    _, browser = _browser(client)
    first = _device(client, browser)
    claims = decode_native_access_token(first["access_token"])
    claims["iat"] = datetime.now(UTC) - timedelta(minutes=10)
    claims["exp"] = datetime.now(UTC) - timedelta(minutes=1)
    expired = NATIVE_ACCESS_PREFIX + jwt.encode(claims, signing_key(), algorithm="HS256")
    assert (
        client.get("/api/auth/me", headers={"Authorization": "Bearer " + expired}).status_code
        == 401
    )
    rotated = client.post(BASE + "/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()
    assert second["session_id"] == first["session_id"]
    assert second["refresh_token"] != first["refresh_token"]
    assert client.get("/api/auth/me", headers=_headers(second)).status_code == 200
    replayed_refresh = client.post(
        BASE + "/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replayed_refresh.status_code == 401
    revoked_refresh = client.post(
        BASE + "/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert revoked_refresh.status_code == 401
    assert client.get("/api/auth/me", headers=_headers(second)).status_code == 401
    with get_session_factory()() as session:
        family = session.get(NativeDeviceSession, first["session_id"])
        assert family.revoked_at is not None
        assert family.revocation_reason == "refresh_replay"
        assert len(list(session.scalars(select(NativeRefreshToken)))) == 2


@pytest.mark.parametrize(
    "cookie",
    [
        "caseops_session",
        "caseops_portal_session",
        "caseops_console_session",
    ],
)
def test_mixed_native_cookie_authority_never_selects_a_principal(client, cookie):
    _, browser = _browser(client)
    device = _device(client, browser)
    headers = {**_headers(device), "Cookie": f"{cookie}=other-realm"}
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    mixed_refresh = client.post(
        BASE + "/refresh",
        headers={"Cookie": f"{cookie}=other-realm"},
        json={"refresh_token": device["refresh_token"]},
    )
    assert mixed_refresh.status_code == 401
    # Rejection does not consume the credential.
    cookie_free_refresh = client.post(
        BASE + "/refresh", json={"refresh_token": device["refresh_token"]}
    )
    assert cookie_free_refresh.status_code == 200


def test_native_cannot_mint_browser_cookie_or_enter_platform_or_portal_realms(client):
    _, browser = _browser(client)
    device = _device(client, browser)
    browser_refresh = client.post("/api/auth/refresh", headers=_headers(device))
    assert browser_refresh.status_code == 401
    assert client.get("/api/platform-admin/overview", headers=_headers(device)).status_code == 401
    assert client.get("/api/portal/me", headers=_headers(device)).status_code == 401
    native_token = client.post(
        BASE + "/token",
        headers=_headers(device),
        json={
            "code": "a" * 43,
            "code_verifier": VERIFIER,
            "platform": "android",
            "redirect_uri": LOCAL_REDIRECT,
        },
    )
    assert native_token.status_code == 401


def test_device_list_revoke_and_logout_do_not_revoke_other_device_or_browser(client):
    _, browser = _browser(client)
    first, second = _device(client, browser), _device(client, browser)
    sessions = client.get("/api/auth/native/sessions", headers=_headers(first))
    assert sessions.status_code == 200, sessions.text
    rows = sessions.json()["sessions"]
    assert {row["id"] for row in rows} == {first["session_id"], second["session_id"]}
    assert [row["id"] for row in rows if row["current"]] == [first["session_id"]]
    assert {row["platform"] for row in rows} == {"android"}
    revoked = client.delete(
        f"/api/auth/native/sessions/{first['session_id']}",
        headers=browser,
    )
    assert revoked.status_code == 204
    assert client.get("/api/auth/me", headers=_headers(first)).status_code == 401
    assert client.get("/api/auth/me", headers=_headers(second)).status_code == 200
    assert client.get("/api/auth/me", headers=browser).status_code == 200
    logout_response = client.post(
        "/api/auth/native/logout",
        json={"refresh_token": second["refresh_token"]},
    )
    assert logout_response.status_code == 204
    repeated_logout_response = client.post(
        "/api/auth/native/logout",
        json={"refresh_token": second["refresh_token"]},
    )
    assert repeated_logout_response.status_code == 204
    assert client.get("/api/auth/me", headers=_headers(second)).status_code == 401


@pytest.mark.parametrize(
    "change", ["membership", "user", "company", "member_cutoff", "user_cutoff"]
)
def test_native_access_and_refresh_recheck_authoritative_identity(client, change):
    auth, browser = _browser(client)
    device = _device(client, browser)
    with get_session_factory()() as session:
        if change in {"membership", "member_cutoff"}:
            row = session.get(CompanyMembership, auth["membership"]["id"])
        elif change in {"user", "user_cutoff"}:
            row = session.get(User, auth["user"]["id"])
        else:
            row = session.get(Company, auth["company"]["id"])
        if change.endswith("cutoff"):
            row.sessions_valid_after = datetime.now(UTC) + timedelta(seconds=1)
        else:
            row.is_active = False
        session.commit()
    assert client.get("/api/auth/me", headers=_headers(device)).status_code == (
        401 if change.endswith("cutoff") else 403
    )
    inactive_identity_refresh = client.post(
        BASE + "/refresh", json={"refresh_token": device["refresh_token"]}
    )
    assert inactive_identity_refresh.status_code == 401


def test_native_mfa_proof_is_current_session_bound_and_not_borrowed_later(client):
    auth, browser = _browser(client)
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        session.add(
            UserMFASetting(
                user_id=auth["user"]["id"],
                status="enrolled",
                verified_at=now - timedelta(minutes=2),
            )
        )
        session.add(
            UserMFAStepUp(
                user_id=auth["user"]["id"],
                membership_id=auth["membership"]["id"],
                purpose="step_up",
                method="totp",
                completed_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(minutes=5),
            )
        )
        session.commit()
    assert _authorize(client, browser).status_code == 403
    with get_session_factory()() as session:
        proof = session.scalar(select(UserMFAStepUp))
        proof.completed_at = datetime.now(UTC)
        # A newer proof from a different browser is not this source session.
        proof.source_token_issued_at = (
            float(decode_access_token(auth["access_token"])["issued_at_precise"]) + 1
        )
        session.commit()
    assert _authorize(client, browser).status_code == 403
    with get_session_factory()() as session:
        proof = session.scalar(select(UserMFAStepUp))
        proof.source_token_issued_at = float(
            decode_access_token(auth["access_token"])["issued_at_precise"]
        )
        session.commit()
    device = _device(client, browser)
    with get_session_factory()() as session:
        family = session.get(NativeDeviceSession, device["session_id"])
        family.mfa_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        # An unrelated fresh browser step-up must not revive this native proof.
        session.add(
            UserMFAStepUp(
                user_id=auth["user"]["id"],
                membership_id=auth["membership"]["id"],
                purpose="step_up",
                method="totp",
                completed_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        session.commit()
    assert client.get("/api/auth/me", headers=_headers(device)).status_code == 403
    expired_mfa_refresh = client.post(
        BASE + "/refresh", json={"refresh_token": device["refresh_token"]}
    )
    assert expired_mfa_refresh.status_code == 403


def test_cross_membership_cannot_list_or_revoke_native_family(client):
    auth, browser = _browser(client)
    device = _device(client, browser)
    with get_session_factory()() as session:
        user = User(
            email="other-native@example.com", full_name="Other Native", password_hash="unused"
        )
        session.add(user)
        session.flush()
        membership = CompanyMembership(
            company_id=auth["company"]["id"], user_id=user.id, role="member"
        )
        session.add(membership)
        session.commit()
        from caseops_api.core.security import create_access_token

        token = create_access_token(
            user_id=user.id,
            company_id=auth["company"]["id"],
            membership_id=membership.id,
            role="member",
        )
    other = {"Authorization": "Bearer " + token}
    assert client.get(BASE + "/sessions", headers=other).json() == {"sessions": []}
    denied_revoke = client.delete(BASE + "/sessions/" + device["session_id"], headers=other)
    assert denied_revoke.status_code == 404
    assert client.get("/api/auth/me", headers=_headers(device)).status_code == 200


def test_actual_browser_mfa_enrollment_proof_is_bound_to_its_source_session(client):
    import time

    from caseops_api.services.security import TOTP_PERIOD_SECONDS, _hotp

    auth, browser = _browser(client)
    with get_session_factory()() as session:
        session.add(
            TenantSecurityPolicy(
                company_id=auth["company"]["id"],
                all_users_mfa_required=True,
                mfa_enforced_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        session.commit()
    enrollment = client.post("/api/auth/mfa/enroll", headers=browser)
    assert enrollment.status_code == 200, enrollment.text
    secret = enrollment.json()["secret"]
    verified = client.post(
        "/api/auth/mfa/enroll/verify",
        headers=browser,
        json={
            "code": _hotp(secret, int(time.time()) // TOTP_PERIOD_SECONDS),
        },
    )
    assert verified.status_code == 200, verified.text
    with get_session_factory()() as session:
        proof = session.scalar(select(UserMFAStepUp))
        assert proof.source_token_issued_at == float(
            decode_access_token(auth["access_token"])["issued_at_precise"]
        )
    grant = _authorize(client, browser)
    assert grant.status_code == 200, grant.text
    issued = _exchange(client, grant.json()["code"])
    assert issued.status_code == 200, issued.text
    device = issued.json()
    assert client.get("/api/auth/me", headers=_headers(device)).status_code == 200
    matter = client.post(
        "/api/matters/",
        headers=browser,
        json={
            "title": "Synthetic MFA native matter",
            "matter_code": "MFA-NATIVE-01",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Synthetic MFA Client",
            "opposing_party": "Synthetic MFA Respondent",
        },
    )
    assert matter.status_code == 200, matter.text
    listed = client.get("/api/matters/?limit=25", headers=_headers(device))
    assert listed.status_code == 200, listed.text
    assert [row["id"] for row in listed.json()["matters"]] == [matter.json()["id"]]
    workspace = client.get(
        f"/api/matters/{matter.json()['id']}/workspace", headers=_headers(device)
    )
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["matter"]["id"] == matter.json()["id"]
    login = client.post(
        "/api/auth/login",
        json={
            "email": "owner@asterlegal.in",
            "password": "FoundersPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    csrf = client.cookies.get("caseops_csrf")
    second_browser = {
        "Cookie": f"caseops_session={login.json()['access_token']}; caseops_csrf={csrf}",
        "X-CSRF-Token": csrf,
    }
    client.cookies.clear()
    assert _authorize(client, second_browser).status_code == 403
    with get_session_factory()() as session:
        session.get(NativeDeviceSession, device["session_id"]).mfa_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        session.commit()
    stepped = client.post(
        "/api/auth/mfa/step-up",
        headers=second_browser,
        json={
            "code": _hotp(secret, int(time.time()) // TOTP_PERIOD_SECONDS),
            "purpose": "step_up",
        },
    )
    assert stepped.status_code == 200, stepped.text
    assert _authorize(client, second_browser).status_code == 200
    assert client.get("/api/auth/me", headers=_headers(device)).status_code == 403
    assert client.get("/api/matters/?limit=25", headers=_headers(device)).status_code == 403
    unrelated_step_up_refresh = client.post(
        "/api/auth/native/refresh",
        json={
            "refresh_token": device["refresh_token"],
        },
    )
    assert unrelated_step_up_refresh.status_code == 403


def test_nonlocal_grants_disabled_unless_all_explicit_release_settings_present(client, monkeypatch):
    _, browser = _browser(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "production")
    assert _authorize(client, browser).status_code == 503
    monkeypatch.setattr(settings, "native_auth_enabled", True)
    monkeypatch.setattr(settings, "native_signing_enabled", True)
    assert _authorize(client, browser).status_code == 503
    import secrets

    from pydantic import SecretStr

    monkeypatch.setattr(settings, "native_signing_secret", SecretStr(secrets.token_hex(32)))
    monkeypatch.setattr(settings, "native_redirect_uris", ["https://app.caseops.in/oauth/callback"])
    assert _authorize(client, browser).status_code == 400
    assert (
        _authorize(
            client, browser, redirect_uri="https://app.caseops.in/oauth/callback"
        ).status_code
        == 200
    )


@pytest.mark.parametrize("platform", ["web", "macos", "expo", "Android"])
def test_platform_is_truthful_android_or_ios_not_inferred_or_fabricated(client, platform):
    _, browser = _browser(client)
    response = _authorize(client, browser, platform=platform)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "secret",
    [
        "",
        "abcd" * 8,
        "n" * 64,
        "0" * 64,
        "0123456789abcdef" * 4,
        "change-me-change-me-change-me-2026",
        "aabbccdd" * 32,
    ],
)
def test_nonlocal_misconfigured_signing_secret_cannot_issue_or_decode(monkeypatch, secret):
    from fastapi import HTTPException
    from pydantic import SecretStr

    from caseops_api.core.native_auth import require_native_issuance

    settings = get_settings()
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(settings, "native_auth_enabled", True)
    monkeypatch.setattr(settings, "native_signing_enabled", True)
    monkeypatch.setattr(settings, "native_redirect_uris", ["https://app.caseops.in/oauth/callback"])
    # Bypass Settings validation to prove the issuance fence itself is closed.
    monkeypatch.setattr(settings, "native_signing_secret", SecretStr(secret))
    with pytest.raises(HTTPException) as denial:
        require_native_issuance("https://app.caseops.in/oauth/callback")
    assert denial.value.status_code == 503
    with pytest.raises(TokenValidationError):
        signing_key()


def test_refresh_family_has_non_sliding_expiry(client):
    _, browser = _browser(client)
    device = _device(client, browser)
    with get_session_factory()() as session:
        family = session.get(NativeDeviceSession, device["session_id"])
        original_expiry = family.expires_at
    response = client.post(BASE + "/refresh", json={"refresh_token": device["refresh_token"]})
    assert response.status_code == 200, response.text
    with get_session_factory()() as session:
        assert session.get(NativeDeviceSession, device["session_id"]).expires_at == original_expiry
        family = session.get(NativeDeviceSession, device["session_id"])
        family.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    expired_family_refresh = client.post(
        BASE + "/refresh", json={"refresh_token": response.json()["refresh_token"]}
    )
    assert expired_family_refresh.status_code == 401
