"""Native MFA recovery classification with real, independently isolated PostgreSQL."""

import pytest

from tests import test_native_auth_20261024 as native
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_optional_native_mfa_recovery_on_postgres(isolated_postgres_client, http_pg_engine):
    assert http_pg_engine.dialect.name == "postgresql"
    assert isolated_postgres_client.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
    native.test_optional_policy_native_mfa_requires_same_browser_proof_and_explicit_recovery(
        isolated_postgres_client
    )


@pytest.mark.parametrize("enrolled", [False, True])
def test_required_native_mfa_refusal_on_postgres(isolated_postgres_client, enrolled):
    native.test_required_policy_native_mfa_proof_refusal_is_typed_without_grants(
        isolated_postgres_client, enrolled
    )
