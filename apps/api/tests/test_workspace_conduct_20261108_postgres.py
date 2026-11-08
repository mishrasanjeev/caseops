"""The native conduct boundary and actor fences on PostgreSQL."""

import pytest

from tests.test_workspace_conduct_20261108 import (
    test_acceptance_rechecks_membership_cutoff_after_request_authentication as revoked,
)
from tests.test_workspace_conduct_20261108 import (
    test_native_note_and_upload_require_current_rules_and_preserve_web_scanner as workflow,
)
from tests.test_workspace_conduct_20261108 import (
    test_native_upload_and_web_reprocessing_skip_external_embedding_provider as local_processing,
)
from tests.test_workspace_conduct_20261108 import (
    test_receipt_is_bound_to_authenticated_membership_and_tenant as tenant_scope,
)
from tests.test_workspace_conduct_20261108 import (
    test_store_review_workspace_composes_with_native_document_processing as composed_processing,
)
from tests.test_workspace_conduct_20261108 import (
    test_upload_rechecks_native_membership_after_storage_and_cleans_owned_copy as upload_race,
)
from tests.test_workspace_conduct_reports_20261108 import (
    test_concurrent_exact_report_replays_share_one_durable_receipt as duplicate,
)
from tests.test_workspace_conduct_reports_20261108 import (
    test_operator_intake_paginates_opaque_metadata_and_escalates_admins as intake,
)
from tests.test_workspace_conduct_reports_20261108 import (
    test_report_rechecks_revocation_after_authentication as report_race,
)
from tests.test_workspace_conduct_reports_20261108 import (
    test_reported_note_file_and_author_require_exact_current_visible_provenance as reports,
)

pytestmark = pytest.mark.postgres


def test_conduct_native_write_and_scanner(isolated_postgres_client, monkeypatch):
    workflow(isolated_postgres_client, monkeypatch)


def test_native_document_processing_privacy(isolated_postgres_client, monkeypatch):
    local_processing(isolated_postgres_client, monkeypatch)


def test_store_review_workspace_processing_privacy(isolated_postgres_client, monkeypatch):
    composed_processing(isolated_postgres_client, monkeypatch)


def test_conduct_tenant_receipt_scope(isolated_postgres_client):
    tenant_scope(isolated_postgres_client)


def test_conduct_rejects_revoked_acceptance(isolated_postgres_client, monkeypatch):
    revoked(isolated_postgres_client, monkeypatch)


def test_conduct_rejects_revocation_after_upload_storage(isolated_postgres_client, monkeypatch):
    upload_race(isolated_postgres_client, monkeypatch)



def test_conduct_report_target_provenance(isolated_postgres_client):
    reports(isolated_postgres_client)


def test_conduct_report_operator_intake(isolated_postgres_client, monkeypatch):
    intake(isolated_postgres_client, monkeypatch)


def test_conduct_report_rejects_stale_authority(isolated_postgres_client, monkeypatch):
    report_race(isolated_postgres_client, monkeypatch)


def test_conduct_report_duplicate_atomicity(isolated_postgres_client, monkeypatch):
    duplicate(isolated_postgres_client, monkeypatch)
