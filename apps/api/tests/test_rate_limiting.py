from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.rate_limit import limiter
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.main import create_application


@pytest.fixture
def rate_limited_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    database_path = tmp_path / "caseops-rate.db"
    storage_path = tmp_path / "documents"
    monkeypatch.setenv("CASEOPS_DATABASE_URL", f"sqlite+pysqlite:///{database_path.as_posix()}")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "test-secret-should-be-at-least-32-bytes")
    monkeypatch.setenv("CASEOPS_PUBLIC_APP_URL", "http://testserver")
    monkeypatch.setenv("CASEOPS_DOCUMENT_STORAGE_PATH", storage_path.as_posix())
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_LOGIN_PER_MINUTE", "3")
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_BOOTSTRAP_PER_HOUR", "2")

    get_settings.cache_clear()
    clear_engine_cache()
    limiter.reset()

    app = create_application()
    with TestClient(app) as client:
        yield client

    get_settings.cache_clear()
    clear_engine_cache()
    limiter.reset()


def _bootstrap_once(client: TestClient, slug: str) -> int:
    return client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"Rate Firm {slug}",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Rate Owner",
            "owner_email": f"{slug}@ratefirm.in",
            "owner_password": "StrongPass123!",
        },
    ).status_code


def test_login_endpoint_rate_limit_returns_429(rate_limited_client: TestClient) -> None:
    assert _bootstrap_once(rate_limited_client, "rate-firm") == 200
    payload = {
        "email": "rate-firm@ratefirm.in",
        "password": "wrong-password",
        "company_slug": "rate-firm",
    }
    statuses = [
        rate_limited_client.post("/api/auth/login", json=payload).status_code
        for _ in range(5)
    ]
    # First three: 401 invalid credentials, then 429 rate-limit.
    assert statuses.count(401) == 3
    assert statuses.count(429) == 2


def test_bootstrap_endpoint_rate_limit_returns_429(rate_limited_client: TestClient) -> None:
    first = _bootstrap_once(rate_limited_client, "firm-alpha")
    second = _bootstrap_once(rate_limited_client, "firm-beta")
    third = _bootstrap_once(rate_limited_client, "firm-gamma")
    fourth = _bootstrap_once(rate_limited_client, "firm-delta")
    assert first == 200
    assert second == 200
    assert third == 429
    assert fourth == 429
