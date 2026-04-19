from __future__ import annotations

import pytest
from pydantic import ValidationError

from caseops_api.core.settings import PLACEHOLDER_AUTH_SECRET, Settings


def test_placeholder_auth_secret_allowed_in_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", PLACEHOLDER_AUTH_SECRET)
    settings = Settings()
    assert settings.auth_secret == PLACEHOLDER_AUTH_SECRET


@pytest.mark.parametrize("env", ["staging", "production", "prod"])
def test_placeholder_auth_secret_rejected_in_non_local(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("CASEOPS_ENV", env)
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", PLACEHOLDER_AUTH_SECRET)
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "CASEOPS_AUTH_SECRET" in str(exc_info.value)


def test_non_placeholder_auth_secret_allowed_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_ENV", "production")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "real-rotated-production-secret-32bytes+")
    settings = Settings()
    assert settings.env == "production"
    assert settings.auth_secret != PLACEHOLDER_AUTH_SECRET


def test_local_env_auto_augments_dev_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the 2026-04-19 bug Codex caught: in non-prod
    envs every common dev port (3000/3100/3500 × localhost/127.0.0.1)
    must be in cors_origins so the browser doesn't get CORS-blocked
    on POST /api/auth/login during prod-build E2E from port 3100.
    A misconfigured CORS list silently broke the entire authenticated
    web flow."""
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_CORS_ORIGINS", '["http://localhost:3000"]')
    settings = Settings()
    expected_added = {
        "http://localhost:3000",   # already in env, kept
        "http://localhost:3100",
        "http://localhost:3500",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3100",
        "http://127.0.0.1:3500",
    }
    assert expected_added.issubset(set(settings.cors_origins))


def test_production_env_does_not_augment_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The augment is local-only; prod keeps the strict configured
    list so a stale dev port slipping into the deployed allow-list
    can't widen the attack surface."""
    monkeypatch.setenv("CASEOPS_ENV", "production")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "real-rotated-production-secret-32bytes+")
    monkeypatch.setenv("CASEOPS_CORS_ORIGINS", '["https://app.caseops.ai"]')
    settings = Settings()
    assert settings.cors_origins == ["https://app.caseops.ai"]
