"""Compatibility metadata does not authenticate or weaken a native session."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx import Headers
from pydantic import ValidationError
from sqlalchemy import func, select

from caseops_api.core.native_client_versions import version_parts
from caseops_api.core.settings import Settings, get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    NativeDeviceSession,
    NativeRefreshToken,
    User,
    UserMFASetting,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.native_client_compatibility import compatibility, enforce_minimum
from tests.test_native_auth_20261024 import _authorize, _browser, _exchange, _headers


@pytest.fixture(autouse=True)
def clean_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def set_floor(monkeypatch, platform="android", value="1.2.0"):
    if platform not in {"android", "ios"}:
        raise ValueError("Unsupported fixture platform.")
    monkeypatch.setenv(f"CASEOPS_NATIVE_MINIMUM_{platform.upper()}_VERSION", value)
    get_settings.cache_clear()


def device_for_platform(client, browser, platform):
    if platform not in {"android", "ios"}:
        raise ValueError("Unsupported fixture platform.")
    grant = _authorize(client, browser, platform=platform)
    assert grant.status_code == 200, grant.text
    exchanged = _exchange(client, grant.json()["code"], platform=platform)
    assert exchanged.status_code == 200, exchanged.text
    return exchanged.json()


@pytest.mark.parametrize("value,expected", [
    ("0.0.0", (0, 0, 0)), ("0.1.0", (0, 1, 0)), ("1.10.0", (1, 10, 0)),
    ("999999999.999999999.999999999", (999999999, 999999999, 999999999)),
])
def test_numeric_store_version_has_exact_literal_components(value, expected):
    assert version_parts(value) == expected


@pytest.mark.parametrize("value", [
    None, True, 1, 1.2, "", "1.2", "01.2.3", "1.2.03", "1.2.3-beta.1",
    "1.2.3+4", "1.2.3\n", " 1.2.3", "١.٢.٣", "1000000000.0.0",
])
def test_invalid_versions_are_not_coerced_or_normalized(value):
    with pytest.raises(ValueError, match="three numeric components"):
        version_parts(value)


@pytest.mark.parametrize("field", ["native_minimum_android_version", "native_minimum_ios_version"])
@pytest.mark.parametrize("value", [True, 1.2, "1.2", "1.2.3-beta"])
def test_invalid_operator_floor_refuses_settings(field, value):
    with pytest.raises(ValidationError, match="three numeric components"):
        Settings(_env_file=None, **{field: value})


def test_unset_floor_preserves_legacy_and_numeric_comparison_is_not_lexical():
    settings = Settings(_env_file=None)
    enforce_minimum(settings, platform="android", client_version=None)
    settings = settings.model_copy(update={"native_minimum_android_version": "1.2.0"})
    result = compatibility(settings, "android", "1.10.0")
    assert result.model_dump() == {
        "protocol_version": 1, "platform": "android", "client_version": "1.10.0",
        "minimum_supported_version": "1.2.0", "status": "supported",
    }
    equal = compatibility(settings, "android", "1.2.0")
    lower = compatibility(settings, "android", "1.1.99")
    assert equal.status == "supported"
    assert lower.status == "update_required"
    with pytest.raises(HTTPException) as refused:
        enforce_minimum(settings, platform="android", client_version="1.1.99")
    assert refused.value.status_code == 426
    assert "1.1.99" not in str(refused.value.detail)
    enforce_minimum(settings, platform="ios", client_version=None)


def test_public_policy_is_bounded_metadata_not_login_or_cookie_authority(client, monkeypatch):
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    set_floor(monkeypatch)
    response = client.get("/api/auth/native/compatibility", params={
        "platform": "android", "client_version": "1.0.0",
    })
    assert response.status_code == 200, response.text
    assert response.json() == {
        "protocol_version": 1, "platform": "android", "client_version": "1.0.0",
        "minimum_supported_version": "1.2.0", "status": "update_required",
    }
    assert not response.headers.get("set-cookie")
    # The shared native-auth middleware owns this contract for every outcome.
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    with get_session_factory()() as session:
        count = session.scalar(select(func.count()).select_from(NativeDeviceSession))
    assert count == 0


@pytest.mark.parametrize("value", ["secret-not-a-version", "1.2.3\n", "x" * 40])
def test_public_format_errors_keep_location_without_echoing_input(client, value):
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    response = client.get("/api/auth/native/compatibility", params={
        "platform": "ios", "client_version": value,
    })
    assert response.status_code == 422, response.text
    assert value not in response.text
    errors = response.json()["errors"]
    assert errors and errors[0]["loc"] == ["query", "client_version"]
    assert all(set(row) <= {"loc", "type", "msg"} for row in errors)
    assert all(row["msg"] for row in errors)


@pytest.mark.parametrize("version", [None, "1.1.99", "do-not-echo", "1.2.0", "1.10.0"])
@pytest.mark.parametrize("platform", ["android", "ios"])
def test_native_floor_rejects_only_incompatible_business_requests(
    client, monkeypatch, version, platform,
):
    auth, browser = _browser(client)
    device = device_for_platform(client, browser, platform)
    set_floor(monkeypatch, platform)
    headers = _headers(device)
    if version is not None:
        headers["X-CaseOps-Client-Version"] = version
    # A forged platform header cannot choose the other platform's unset floor.
    headers["X-CaseOps-Client-Platform"] = "ios" if platform == "android" else "android"
    response = client.get("/api/auth/me", headers=headers)
    expected = 200 if version in {"1.2.0", "1.10.0"} else 426
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json()["user"]["id"] == auth["user"]["id"]
    else:
        assert response.json()["code"] == "native_client_update_required"
        assert response.json()["platform"] == platform
        assert response.json()["minimum_supported_version"] == "1.2.0"
        if version is not None:
            assert version not in response.text
    with get_session_factory()() as session:
        saved = session.get(NativeDeviceSession, device["session_id"])
        tokens = list(session.scalars(select(NativeRefreshToken)))
        assert saved.revoked_at is None
        assert len(tokens) == 1 and tokens[0].consumed_at is None


def test_update_boundary_blocks_mutation_but_keeps_security_and_browser_paths(client, monkeypatch):
    _auth, browser = _browser(client)
    device = device_for_platform(client, browser, "android")
    set_floor(monkeypatch)
    payload = {
        "title": "Synthetic compatibility matter", "matter_code": "NATIVE-COMPAT-01",
        "practice_area": "litigation", "forum_level": "high_court",
        "court_name": "Delhi High Court", "client_name": "Synthetic Client",
        "opposing_party": "Synthetic Respondent",
    }
    with get_session_factory()() as session:
        before = session.scalar(select(func.count()).select_from(Matter))
    refused = client.post("/api/matters/", headers=_headers(device), json=payload)
    assert refused.status_code == 426, refused.text
    with get_session_factory()() as session:
        after = session.scalar(select(func.count()).select_from(Matter))
    assert after == before
    admitted = client.post("/api/matters/", headers={
        **_headers(device), "X-CaseOps-Client-Version": "1.2.0",
    }, json=payload)
    assert admitted.status_code == 200, admitted.text
    with get_session_factory()() as session:
        after_admitted = session.scalar(select(func.count()).select_from(Matter))
    assert after_admitted == before + 1
    browser_read = client.get("/api/auth/me", headers=browser)
    sessions = client.get("/api/auth/native/sessions", headers=_headers(device))
    security = client.get("/api/auth/security", headers=_headers(device))
    assert browser_read.status_code == 200, browser_read.text
    assert sessions.status_code == 200, sessions.text
    assert security.status_code == 200, security.text
    revoked = client.delete(
        "/api/auth/native/sessions/" + device["session_id"], headers=_headers(device),
    )
    assert revoked.status_code == 204, revoked.text
    rejected = client.get("/api/auth/me", headers={
        **_headers(device), "X-CaseOps-Client-Version": "99.0.0",
    })
    assert rejected.status_code == 401, rejected.text


def test_floor_rollback_preserves_the_same_valid_native_session(client, monkeypatch):
    auth, browser = _browser(client)
    device = device_for_platform(client, browser, "android")
    set_floor(monkeypatch)
    blocked = client.get("/api/auth/me", headers=_headers(device))
    assert blocked.status_code == 426, blocked.text
    monkeypatch.delenv("CASEOPS_NATIVE_MINIMUM_ANDROID_VERSION")
    get_settings.cache_clear()
    restored = client.get("/api/auth/me", headers=_headers(device))
    assert restored.status_code == 200, restored.text
    assert restored.json()["user"]["id"] == auth["user"]["id"]


def test_duplicate_version_headers_do_not_select_a_permissive_value(client, monkeypatch):
    _auth, browser = _browser(client)
    device = device_for_platform(client, browser, "android")
    set_floor(monkeypatch)
    response = client.get("/api/auth/me", headers=Headers([
        ("Authorization", "Bearer " + device["access_token"]),
        ("X-CaseOps-Client-Version", "99.0.0"),
        ("X-CaseOps-Client-Version", "0.1.0"),
    ]))
    assert response.status_code == 426, response.text


@pytest.mark.parametrize("platform", ["android", "ios"])
def test_below_floor_refresh_and_logout_keep_strict_token_only_contract(
    client, monkeypatch, platform,
):
    _auth, browser = _browser(client)
    device = device_for_platform(client, browser, platform)
    set_floor(monkeypatch, platform)
    refreshed = client.post("/api/auth/native/refresh", json={
        "refresh_token": device["refresh_token"],
    })
    assert refreshed.status_code == 200, refreshed.text
    current = refreshed.json()
    assert current["session_id"] == device["session_id"]
    blocked = client.get("/api/auth/me", headers=_headers(current))
    assert blocked.status_code == 426, blocked.text
    wrong_realm = client.post("/api/auth/native/logout", headers=_headers(current), json={
        "refresh_token": current["refresh_token"],
    })
    assert wrong_realm.status_code == 401, wrong_realm.text
    logged_out = client.post("/api/auth/native/logout", json={
        "refresh_token": current["refresh_token"],
    })
    assert logged_out.status_code == 204, logged_out.text
    rejected = client.get("/api/auth/me", headers={
        **_headers(current), "X-CaseOps-Client-Version": "99.0.0",
    })
    assert rejected.status_code == 401, rejected.text


@pytest.mark.parametrize(
    "change", ["membership", "user", "company", "member_cutoff", "user_cutoff"],
)
def test_version_header_never_overrides_current_identity_refusal(client, monkeypatch, change):
    auth, browser = _browser(client)
    device = device_for_platform(client, browser, "ios")
    set_floor(monkeypatch, "ios")
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
    rejected = client.get("/api/auth/me", headers={
        **_headers(device), "X-CaseOps-Client-Version": "99.0.0",
    })
    assert rejected.status_code == (401 if change.endswith("cutoff") else 403), rejected.text


def test_version_header_does_not_replace_a_newly_required_mfa_proof(client, monkeypatch):
    auth, browser = _browser(client)
    device = device_for_platform(client, browser, "android")
    set_floor(monkeypatch)
    with get_session_factory()() as session:
        session.add(UserMFASetting(
            user_id=auth["user"]["id"], status="enrolled", verified_at=datetime.now(UTC),
        ))
        session.commit()
    response = client.get("/api/auth/me", headers={
        **_headers(device), "X-CaseOps-Client-Version": "99.0.0",
    })
    assert response.status_code == 403, response.text


def test_version_header_alone_never_authenticates_a_request(client, monkeypatch):
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    set_floor(monkeypatch)
    response = client.get("/api/auth/me", headers={"X-CaseOps-Client-Version": "99.0.0"})
    assert response.status_code == 401, response.text
