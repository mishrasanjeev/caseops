from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.main import create_application
from tests.test_postgres_validation import _ensure_migrations, migration_pg_engine  # noqa: F401


@pytest.fixture
def isolated_postgres_client(
    request: pytest.FixtureRequest, monkeypatch, tmp_path,
) -> Generator[TestClient]:
    # API fixtures and global aggregators own a freshly migrated, disposable database.
    engine = request.getfixturevalue("migration_pg_engine")
    assert engine.dialect.name == "postgresql"
    for name, value in {
        "CASEOPS_ENV": "local",
        "CASEOPS_AUTO_MIGRATE": "false",
        "CASEOPS_AUTH_SECRET": "test-secret-should-be-at-least-32-bytes",
        "CASEOPS_AUTH_RATE_LIMIT_ENABLED": "false",
        "CASEOPS_PUBLIC_APP_URL": "http://testserver",
        "CASEOPS_CORS_ORIGINS": '["http://testserver"]',
        "CASEOPS_LLM_PROVIDER": "mock",
        "CASEOPS_LLM_MODEL": "caseops-mock-1",
        "CASEOPS_LLM_API_KEY": "",
        "CASEOPS_EMBEDDING_PROVIDER": "mock",
        "CASEOPS_EMBEDDING_MODEL": "caseops-mock-embed",
        "CASEOPS_EMBEDDING_API_KEY": "",
        "CASEOPS_DOCUMENT_STORAGE_PATH": (tmp_path / "documents").as_posix(),
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    clear_engine_cache()
    with TestClient(
        create_application(),
        headers={"X-CaseOps-Automated-Test": "no-paid-providers"},
    ) as client:
        yield client
