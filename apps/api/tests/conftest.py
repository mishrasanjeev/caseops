from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.main import create_application


# Autouse fixture — defense against suite-order leakage.
#
# Monkeypatch restores environment variables at test teardown, but it does
# NOT touch in-process caches. Any test that calls
# ``get_settings.cache_clear()`` after a ``monkeypatch.setenv`` leaves the
# cached Settings object holding the monkeypatched values. The NEXT test
# that reads settings without going through the ``client`` fixture sees
# the stale object and — if it happened to be pointed at the shared prod
# DSN — produces the 5 spurious failures Codex flagged in the
# 2026-04-20 gap audit (full suite 382 / 5, isolated 15 / 0).
#
# Clearing the caches at teardown is cheap (microseconds) and breaks the
# leak at source. Individual tests can still opt into setting up a fresh
# environment inside their body; the autouse wipe just makes sure nobody
# hands a polluted cache to the next test.
@pytest.fixture(autouse=True)
def _reset_settings_and_engine_caches_after_test() -> Generator[None]:
    yield
    get_settings.cache_clear()
    clear_engine_cache()


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    database_path = tmp_path / "caseops-test.db"
    storage_path = tmp_path / "documents"
    # EG-003 (2026-04-23) — pin the test process to "local" env.
    # ``services.virus_scan._required_default_for_env`` reads
    # ``CASEOPS_ENV`` straight from ``os.environ`` (not the cached
    # Settings), so without this the strict ``is_non_local_env``
    # allow-list treats a bare test environment as non-local,
    # defaults ``CLAMAV_REQUIRED=True``, and 503s every attachment
    # upload because no scanner is configured.
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "test-secret-should-be-at-least-32-bytes")
    monkeypatch.setenv("CASEOPS_PUBLIC_APP_URL", "http://testserver")
    monkeypatch.setenv("CASEOPS_CORS_ORIGINS", '["http://localhost:3000","http://testserver"]')
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_PATH", storage_path.as_posix())
    monkeypatch.setenv("CASEOPS_PINE_LABS_API_BASE_URL", "https://uat-pinelabs.example")
    monkeypatch.setenv("CASEOPS_PINE_LABS_PAYMENT_LINK_PATH", "/payments")
    monkeypatch.setenv("CASEOPS_PINE_LABS_PAYMENT_STATUS_PATH", "/payments/{provider_order_id}")
    monkeypatch.setenv("CASEOPS_PINE_LABS_MERCHANT_ID", "merchant-uat")
    monkeypatch.setenv("CASEOPS_PINE_LABS_API_KEY", "pine-api-key")
    monkeypatch.setenv("CASEOPS_PINE_LABS_API_SECRET", "pine-api-secret")
    monkeypatch.setenv("CASEOPS_PINE_LABS_WEBHOOK_SECRET", "pine-webhook-secret")
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "caseops-mock-1")
    monkeypatch.delenv("CASEOPS_LLM_API_KEY", raising=False)
    # Force the deterministic mock embedding provider. Without this the
    # suite inherits .env (typically fastembed), which makes tests depend
    # on model weights being cached on disk and leaks latency into unit
    # runs. The mock provider is normalised and dimension-faithful.
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_EMBEDDING_MODEL", "caseops-mock-embed")
    # Empty string (not delenv) so pydantic-settings does not fall back
    # to a real Voyage key sitting in apps/api/.env.
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "")
    get_settings.cache_clear()
    clear_engine_cache()

    from caseops_api.core.rate_limit import limiter

    limiter.reset()

    app = create_application()
    with TestClient(app) as test_client:
        # 2026-04-24 (CI breakage from EG-001 cookie-first auth +
        # TestClient cookie persistence). The starlette TestClient
        # persists every Set-Cookie across requests, and
        # ``get_current_context`` prefers the cookie when both a
        # cookie and a Bearer header arrive. Tenant-isolation tests
        # bootstrap two tenants (each setting a session cookie),
        # then issue Bearer-authed cross-tenant calls — expecting
        # the bearer to take effect, but the persisted cookie wins
        # and silently routes the request to whichever tenant
        # bootstrapped LAST. Result: tenant A appears to see tenant
        # B's matters in test_tenant_isolation, and 9 other tests
        # fail similarly.
        #
        # Fix at the conftest layer: any request that carries an
        # explicit ``Authorization: Bearer`` header strips the
        # cookie jar so the bearer alone decides identity. This
        # mirrors REAL CLIENT BEHAVIOR — a CLI / SDK that sends
        # bearer auth never carries the web session cookie. Routes
        # that need the cookie pathway (every test that intentionally
        # doesn't send Authorization) are unaffected.
        original_request = test_client.request

        def request_with_auth_aware_cookies(method, url, **kwargs):
            headers = kwargs.get("headers") or {}
            auth_header = (
                headers.get("Authorization")
                or headers.get("authorization")
                or ""
            )
            if isinstance(auth_header, str) and auth_header.startswith(
                "Bearer "
            ):
                # Pop the cookie jar for this single request only.
                saved = list(test_client.cookies.jar)
                test_client.cookies.clear()
                try:
                    return original_request(method, url, **kwargs)
                finally:
                    for cookie in saved:
                        test_client.cookies.jar.set_cookie(cookie)
            return original_request(method, url, **kwargs)

        test_client.request = request_with_auth_aware_cookies  # type: ignore[method-assign]
        yield test_client

    get_settings.cache_clear()
    clear_engine_cache()
    limiter.reset()
    if database_path.exists():
        os.remove(database_path)
