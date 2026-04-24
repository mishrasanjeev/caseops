"""EG-001 (2026-04-23) — HttpOnly cookie session + CSRF middleware.

Closes the Codex audit gap that the access token was stashed in
``window.localStorage`` and therefore readable by any successful XSS.
The cookie sits behind ``HttpOnly`` so JavaScript can never read it,
and the paired ``X-CSRF-Token`` header (echoed from the JS-readable
``caseops_csrf`` cookie) blocks cross-site forgeries from a different
origin that can cause the cookie to be sent but cannot read its
value.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.cookies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from tests.test_auth_company import auth_headers, bootstrap_company


def test_cookies_set_parent_domain_in_non_local_env(
    client: TestClient,
    monkeypatch,
) -> None:
    """BUG-011 regression (2026-04-24, Ram). Web app on caseops.ai +
    API on api.caseops.ai => cookies must be scoped to .caseops.ai
    so document.cookie on the web origin can read the JS-readable
    CSRF cookie. Without this, every mutating request lands without
    X-CSRF-Token and the CSRF middleware returns 403 across the
    entire app.

    Local env keeps host-only cookies (no Domain) so localhost dev
    isn't affected.
    """
    from caseops_api.core import cookies as cookies_module
    from caseops_api.core import settings as settings_module

    bootstrap = bootstrap_company(client)
    settings_module.get_settings.cache_clear()
    monkeypatch.setattr(
        cookies_module,
        "_cookie_secure",
        lambda env: False,  # don't require Secure for the in-memory test
    )
    monkeypatch.setattr(
        cookies_module,
        "_cookie_domain",
        lambda env: ".caseops.ai",  # what prod _cookie_domain returns
    )
    client.cookies.clear()
    resp = client.post(
        "/api/auth/login",
        json={
            "email": bootstrap["user"]["email"],
            "password": "FoundersPass123!",
            "company_slug": bootstrap["company"]["slug"],
        },
    )
    assert resp.status_code == 200
    set_cookie = "\n".join(resp.headers.get_list("set-cookie")).lower()
    assert "domain=.caseops.ai" in set_cookie, (
        "Set-Cookie must carry Domain=.caseops.ai in non-local env "
        "so caseops.ai (web) and api.caseops.ai (api) can both read "
        f"the cookies. Got:\n{set_cookie}"
    )


def test_cookies_omit_domain_in_local_env(
    client: TestClient,
    monkeypatch,
) -> None:
    """Inverse of the above: in LOCAL env, no Domain so the cookie
    stays host-only on localhost. Setting Domain=localhost (or any
    Domain on a non-public TLD) would make the browser reject it."""
    from caseops_api.core import cookies as cookies_module
    from caseops_api.core import settings as settings_module

    bootstrap = bootstrap_company(client)
    settings_module.get_settings.cache_clear()
    monkeypatch.setattr(
        cookies_module, "_cookie_secure", lambda env: False,
    )
    monkeypatch.setattr(
        cookies_module, "_cookie_domain", lambda env: None,
    )
    client.cookies.clear()
    resp = client.post(
        "/api/auth/login",
        json={
            "email": bootstrap["user"]["email"],
            "password": "FoundersPass123!",
            "company_slug": bootstrap["company"]["slug"],
        },
    )
    assert resp.status_code == 200
    set_cookie = "\n".join(resp.headers.get_list("set-cookie")).lower()
    assert "domain=" not in set_cookie, (
        "Local env Set-Cookie must omit Domain so the cookie stays "
        f"host-only. Got:\n{set_cookie}"
    )


def test_login_sets_session_and_csrf_cookies(client: TestClient) -> None:
    """The login route must set ``caseops_session`` (HttpOnly) and
    ``caseops_csrf`` (JS-readable) cookies. Without both, the web
    client cannot make a single state-changing call."""
    bootstrap = bootstrap_company(client)
    # Wipe cookies from bootstrap so the login response is the only
    # source of Set-Cookie headers we examine.
    client.cookies.clear()
    resp = client.post(
        "/api/auth/login",
        json={
            "email": bootstrap["user"]["email"],
            "password": "FoundersPass123!",
            "company_slug": bootstrap["company"]["slug"],
        },
    )
    assert resp.status_code == 200, resp.text

    set_cookie = resp.headers.get_list("set-cookie")
    joined = "\n".join(set_cookie)
    assert SESSION_COOKIE in joined, f"missing session cookie in {joined!r}"
    assert CSRF_COOKIE in joined, f"missing CSRF cookie in {joined!r}"
    # Session cookie must be HttpOnly so JS cannot exfiltrate it.
    session_lines = [line for line in set_cookie if SESSION_COOKIE in line]
    assert any("httponly" in line.lower() for line in session_lines), (
        f"session cookie not HttpOnly: {session_lines!r}"
    )
    # CSRF cookie must NOT be HttpOnly — the web client has to read it
    # to echo as a header on mutations.
    csrf_lines = [
        line for line in set_cookie
        if CSRF_COOKIE in line and SESSION_COOKIE not in line
    ]
    assert csrf_lines, f"no CSRF-only cookie line in {set_cookie!r}"
    assert all("httponly" not in line.lower() for line in csrf_lines), (
        f"CSRF cookie was HttpOnly (would break header echo): {csrf_lines!r}"
    )
    # Both cookies must be SameSite=Lax — survives email links + still
    # blocks CSRF when paired with the X-CSRF-Token check.
    assert "samesite=lax" in joined.lower()


def test_authenticated_get_works_via_cookie_only(client: TestClient) -> None:
    """``get_current_context`` must accept cookie-only auth — the web
    client will stop sending Authorization once we cut over."""
    bootstrap = bootstrap_company(client)
    # Drop the bearer header; rely entirely on the cookie set by
    # bootstrap_company.
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["company"]["slug"] == bootstrap["company"]["slug"]


def test_authenticated_get_works_via_bearer_when_cookies_dropped(
    client: TestClient,
) -> None:
    """The bearer path must keep working for SDKs / automation /
    in-flight web bundles from the previous deploy."""
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    # Drop cookies entirely; send only the bearer header.
    client.cookies.clear()
    resp = client.get("/api/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text


def test_post_without_csrf_header_is_rejected_403(client: TestClient) -> None:
    """A cookie-authenticated POST that omits the ``X-CSRF-Token``
    header must return 403 from the CSRF middleware. Without this,
    CSRF protection would be a no-op."""
    bootstrap_company(client)
    # Cookie is set, but no X-CSRF-Token header → 403 expected.
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "CSRF-001",
            "title": "Should be blocked",
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert "CSRF" in body["detail"], body


def test_post_with_matching_csrf_header_is_accepted(client: TestClient) -> None:
    """The double-submit pattern: cookie + matching header are both
    required. When both match, the request goes through."""
    bootstrap_company(client)
    csrf_token = client.cookies.get(CSRF_COOKIE)
    assert csrf_token, "CSRF cookie should have been set by bootstrap"
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "CSRF-002",
            "title": "Allowed via header echo",
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
        headers={CSRF_HEADER: csrf_token},
    )
    assert resp.status_code == 200, resp.text


def test_post_with_mismatched_csrf_header_is_rejected_403(
    client: TestClient,
) -> None:
    """Even with a header set, the value must equal the cookie value
    (constant-time compare). A cross-site attacker can guess header
    names but cannot read the cookie's random value."""
    bootstrap_company(client)
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "CSRF-003",
            "title": "Should be blocked",
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
        headers={CSRF_HEADER: "obviously-wrong-value"},
    )
    assert resp.status_code == 403, resp.text


def test_bearer_auth_post_skips_csrf_check(client: TestClient) -> None:
    """SDKs / automation that hold a bearer token should not need to
    play the CSRF dance — the bearer token IS the secret. Without
    this exemption every E2E test would have to scrape the cookie."""
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    client.cookies.clear()  # No cookie at all → not a browser client.
    resp = client.post(
        "/api/matters",
        json={
            "matter_code": "CSRF-BEARER-001",
            "title": "Bearer path bypasses CSRF",
            "practice_area": "Civil",
            "forum_level": "high_court",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def test_login_endpoint_is_csrf_exempt(client: TestClient) -> None:
    """The login endpoint cannot require CSRF — the user has no
    cookie yet on first sign-in. Pre-auth endpoints must be exempt."""
    # Bootstrap a company so we have a valid user to log in as.
    bootstrap = bootstrap_company(client)
    # Wipe cookies so the next login looks like a fresh browser
    # session with no prior CSRF cookie.
    client.cookies.clear()
    resp = client.post(
        "/api/auth/login",
        json={
            "email": bootstrap["user"]["email"],
            "password": "FoundersPass123!",
            "company_slug": bootstrap["company"]["slug"],
        },
    )
    assert resp.status_code == 200, resp.text


def test_logout_clears_session_cookie(client: TestClient) -> None:
    """Logout must zero the session cookie so a subsequent /me call
    returns 401."""
    bootstrap_company(client)
    csrf_token = client.cookies.get(CSRF_COOKIE)
    resp = client.post("/api/auth/logout", headers={CSRF_HEADER: csrf_token or ""})
    assert resp.status_code == 204, resp.text
    # The Set-Cookie header should overwrite the session cookie with
    # an empty value + Max-Age=0.
    set_cookie = "\n".join(
        [v for k, v in resp.headers.items() if k.lower() == "set-cookie"]
    )
    assert SESSION_COOKIE in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie

    # /me with no cookie + no bearer must 401.
    client.cookies.clear()
    me = client.get("/api/auth/me")
    assert me.status_code == 401


def test_webhook_path_is_csrf_exempt(client: TestClient) -> None:
    """Provider-signed webhooks (PineLabs, SendGrid event hooks) have
    their own integrity check. They must not be blocked by CSRF or
    the integration silently dies."""
    # We don't care about the response shape — only that the request
    # gets PAST the CSRF middleware. A 404 / 401 / 422 from the route
    # handler all prove CSRF didn't reject; we just must not see a
    # 403 with detail "CSRF token mismatch."
    resp = client.post(
        "/api/webhooks/pinelabs",
        json={"event": "ping"},
    )
    assert resp.status_code != 403 or "CSRF" not in resp.text


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/health"),
        ("get", "/api/auth/me"),  # still exempt — GET, not state-changing
    ],
)
def test_get_routes_are_csrf_exempt(
    client: TestClient, method: str, path: str
) -> None:
    """Per RFC, only state-changing methods need CSRF protection.
    GET / HEAD / OPTIONS must pass through the middleware unchanged.
    Without this, the cockpit would 403 every page load."""
    bootstrap_company(client)
    resp = getattr(client, method)(path)
    # /api/auth/me is authenticated; /api/health is not. Both should
    # NOT 403 with a CSRF detail.
    assert resp.status_code != 403 or "CSRF" not in resp.text
