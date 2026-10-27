"""Same real HTTP self/receipt/concurrency contracts on isolated PostgreSQL."""

import pytest

from tests.test_account_privacy_20261027 import (
    concurrent_submission,
    native_roundtrip,
    postcommit_acknowledgement_failure,
    roundtrip,
    self_scope,
    tenant_export_privacy,
)
from tests.test_hearing_explicit_channels_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)

forbid_unadmitted_network = _forbid_unadmitted_network
pytestmark = pytest.mark.postgres


def test_receipt_and_replay_postgres(isolated_postgres_client):
    roundtrip(isolated_postgres_client)


def test_native_request_and_revocation_postgres(isolated_postgres_client):
    native_roundtrip(isolated_postgres_client)


def test_global_self_scope_postgres(isolated_postgres_client):
    self_scope(isolated_postgres_client)


def test_tenant_owner_exports_exclude_global_self_request_postgres(isolated_postgres_client):
    tenant_export_privacy(isolated_postgres_client)


def test_postcommit_failure_retains_single_private_audit_postgres(
    isolated_postgres_client, monkeypatch
):
    postcommit_acknowledgement_failure(isolated_postgres_client, monkeypatch)


@pytest.mark.parametrize("same_operation", [True, False])
def test_overlapping_http_requests_postgres(isolated_postgres_client, monkeypatch, same_operation):
    concurrent_submission(isolated_postgres_client, monkeypatch, same_operation=same_operation)
