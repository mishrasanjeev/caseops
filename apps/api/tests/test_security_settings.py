from __future__ import annotations

import pytest
from pydantic import ValidationError

from caseops_api.core.settings import PLACEHOLDER_AUTH_SECRET, Settings


def test_placeholder_auth_secret_allowed_in_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", PLACEHOLDER_AUTH_SECRET)
    settings = Settings()
    assert settings.auth_secret == PLACEHOLDER_AUTH_SECRET


@pytest.mark.parametrize(
    "env",
    [
        "staging",
        "production",
        "prod",
        # Codex's 2026-04-19 cybersecurity review (finding #3):
        # `cloud` is the value Cloud Run sets via
        # infra/cloudrun/api-service.yaml; the previous allow-list
        # treated it as local and skipped the placeholder-secret guard.
        "cloud",
        "gke",
        # Strict allow-list: any unknown env defaults to non-local so
        # security guards apply by default. Fail closed.
        "ee-prod",
        "uat",
        "qa",
    ],
)
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
    # EG-002: prod requires explicit auto-migrate opt-out.
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    settings = Settings()
    assert settings.env == "production"
    assert settings.auth_secret != PLACEHOLDER_AUTH_SECRET


@pytest.mark.parametrize("env", ["staging", "production", "prod", "cloud", "gke"])
def test_auto_migrate_rejected_in_non_local(
    monkeypatch: pytest.MonkeyPatch, env: str,
) -> None:
    """EG-002 (2026-04-23): production / cloud API services MUST NOT
    auto-migrate at startup. The validator rejects the combination
    so a fresh deploy that forgets to set CASEOPS_AUTO_MIGRATE=false
    fails fast at boot instead of starting a multi-instance migration
    race in prod.
    """
    monkeypatch.setenv("CASEOPS_ENV", env)
    monkeypatch.setenv(
        "CASEOPS_AUTH_SECRET", "real-rotated-production-secret-32bytes+",
    )
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "true")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "CASEOPS_AUTO_MIGRATE" in str(exc_info.value)
    assert "caseops-migrate-job" in str(exc_info.value)


def test_auto_migrate_allowed_in_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local + dev keep the existing pytest / docker-compose flow:
    auto_migrate=True is fine because there's exactly one instance."""
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv(
        "CASEOPS_AUTH_SECRET", PLACEHOLDER_AUTH_SECRET,
    )
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "true")
    settings = Settings()
    assert settings.auto_migrate is True


def test_auto_migrate_false_allowed_everywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit opt-out is always accepted, no matter the env."""
    monkeypatch.setenv("CASEOPS_ENV", "production")
    monkeypatch.setenv(
        "CASEOPS_AUTH_SECRET", "real-rotated-production-secret-32bytes+",
    )
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    settings = Settings()
    assert settings.env == "production"
    assert settings.auto_migrate is False


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
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    settings = Settings()
    assert settings.cors_origins == ["https://app.caseops.ai"]


@pytest.mark.parametrize("env", ["cloud", "gke", "uat", "qa", "ee-prod"])
def test_cloud_env_does_not_augment_cors_origins(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """The Cloud Run / GKE / unknown env profiles must NOT receive the
    dev-port augment (Codex 2026-04-19 finding #3). A misclassified
    env that auto-allowed http://localhost:* in a deployed environment
    would widen the CORS attack surface unnecessarily."""
    monkeypatch.setenv("CASEOPS_ENV", env)
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", "real-rotated-secret-not-the-placeholder")
    monkeypatch.setenv("CASEOPS_CORS_ORIGINS", '["https://app.caseops.ai"]')
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    settings = Settings()
    assert settings.cors_origins == ["https://app.caseops.ai"]
