from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.main import create_application


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient]:
    database_path = tmp_path / "caseops-test.db"
    storage_path = tmp_path / "documents"
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
    get_settings.cache_clear()
    clear_engine_cache()

    from caseops_api.core.rate_limit import limiter

    limiter.reset()

    app = create_application()
    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
    clear_engine_cache()
    limiter.reset()
    if database_path.exists():
        os.remove(database_path)
