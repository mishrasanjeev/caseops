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
