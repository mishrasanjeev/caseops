"""Real PostgreSQL proof that later events keep saved manifests fail-closed (2026-09-27).

The SQLite journey's saved generations, bare and real events, and decisions
before and after a later rebuild, on PostgreSQL.
"""

from __future__ import annotations

import pytest

from tests import test_20260927_saved_manifest_later_events as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_later_source_events_keep_saved_manifests_fail_closed_in_every_generation(
    isolated_postgres_client,
):
    journeys.test_later_source_events_keep_saved_manifests_fail_closed_in_every_generation(
        isolated_postgres_client
    )
