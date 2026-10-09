"""Prove new-only release QA whitespace fixtures on independently migrated PostgreSQL."""

import pytest

from tests import test_bootstrap_ip_production_qa as bootstrap

pytestmark = pytest.mark.postgres


def test_new_fixture_and_legacy_active_replay(isolated_postgres_client) -> None:
    bootstrap.test_bootstrap_private_retrieval_fixture_is_release_scoped_and_idempotent(
        isolated_postgres_client
    )


def test_new_iteration_preserves_terminal_predecessor(isolated_postgres_client) -> None:
    bootstrap.test_bootstrap_private_retrieval_fixture_creates_a_new_terminal_safe_iteration(
        isolated_postgres_client
    )
