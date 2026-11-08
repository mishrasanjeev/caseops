"""The native conduct boundary and actor fences on PostgreSQL."""

import pytest

from tests.test_workspace_conduct_20261108 import (
    test_acceptance_rechecks_membership_cutoff_after_request_authentication as revoked,
)
from tests.test_workspace_conduct_20261108 import (
    test_native_note_and_upload_require_current_rules_and_preserve_web_scanner as workflow,
)
from tests.test_workspace_conduct_20261108 import (
    test_receipt_is_bound_to_authenticated_membership_and_tenant as tenant_scope,
)
from tests.test_workspace_conduct_20261108 import (
    test_upload_rechecks_native_membership_after_storage_and_cleans_owned_copy as upload_race,
)

pytestmark = pytest.mark.postgres


def test_conduct_native_write_and_scanner(isolated_postgres_client, monkeypatch):
    workflow(isolated_postgres_client, monkeypatch)


def test_conduct_tenant_receipt_scope(isolated_postgres_client):
    tenant_scope(isolated_postgres_client)


def test_conduct_rejects_revoked_acceptance(isolated_postgres_client, monkeypatch):
    revoked(isolated_postgres_client, monkeypatch)


def test_conduct_rejects_revocation_after_upload_storage(isolated_postgres_client, monkeypatch):
    upload_race(isolated_postgres_client, monkeypatch)
