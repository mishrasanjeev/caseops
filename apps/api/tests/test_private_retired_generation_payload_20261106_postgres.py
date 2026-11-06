"""Real PostgreSQL proof that retired generations keep no deleted-source payload (B4-ADJ-40).

Replays the SQLite journeys, deletion through the archive route and direct and
scoped tombstones, saved-output proofs, maintenance and per-tenant purges, on
PostgreSQL, where the purge claims rows with SKIP LOCKED and the scan and purge
read ix_private_projection_retained_payload.
"""

from __future__ import annotations

import pytest

from tests import test_private_retired_generation_payload_20261106 as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("deleted", ["document_direct", "matter_scope"])
def test_deleted_source_leaves_no_text_or_vector_in_any_retained_generation(
    isolated_postgres_client, deleted
):
    journeys.test_deleted_source_leaves_no_text_or_vector_in_any_retained_generation(
        isolated_postgres_client, deleted
    )


def test_archived_client_text_is_gone_from_every_retained_generation(isolated_postgres_client):
    journeys.test_archived_client_text_is_gone_from_every_retained_generation(
        isolated_postgres_client
    )


def test_retirement_keeps_active_payload_saved_proofs_and_embedding_reuse(
    isolated_postgres_client,
):
    journeys.test_retirement_keeps_active_payload_saved_proofs_and_embedding_reuse(
        isolated_postgres_client
    )


def test_integrity_blocks_retained_retired_payload_until_purged_per_tenant(
    isolated_postgres_client,
):
    journeys.test_integrity_blocks_retained_retired_payload_until_purged_per_tenant(
        isolated_postgres_client
    )


def test_maintenance_purges_the_pre_fix_backlog_and_reports_it(isolated_postgres_client):
    journeys.test_maintenance_purges_the_pre_fix_backlog_and_reports_it(isolated_postgres_client)


def test_pre_fix_tombstone_labels_are_counted_and_purged(isolated_postgres_client):
    journeys.test_pre_fix_tombstone_labels_are_counted_and_purged(isolated_postgres_client)


def test_undrained_backlog_never_stops_maintenance_rebuilding_a_stale_generation(
    isolated_postgres_client, monkeypatch
):
    journeys.test_undrained_backlog_never_stops_maintenance_rebuilding_a_stale_generation(
        isolated_postgres_client, monkeypatch
    )
