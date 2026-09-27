"""Real PostgreSQL proof for bounded Draft lists and reads (2026-09-27).

The SQLite journeys' drafts, decisions and statement bounds, on PostgreSQL.
The volume test repeats them with 10,000 unrelated projections and 10,000
unrelated ledger events retained in each of two generations of the private
index, without a manual ANALYZE, inside a 1,500 ms per-statement budget and
with hash and merge joins disabled, so an adverse nested-loop plan cannot hide
behind the planner's choice.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from caseops_api.db.session import get_session_factory
from tests import test_20260927_draft_lists_bounded as journeys
from tests.test_20260927_review_history_bounded_postgres import (
    RETAINED_EVENTS_PER_GENERATION,
    RETAINED_PROJECTIONS_PER_GENERATION,
    _adverse_statement_budget,
    _retain_production_volume,
)
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_draft_lists_and_reads_reauthorize_every_version_in_one_bounded_query_set(
    isolated_postgres_client,
):
    journeys.test_draft_lists_and_reads_reauthorize_every_version_in_one_bounded_query_set(
        isolated_postgres_client
    )


def test_draft_lists_and_reads_keep_revoked_sources_hidden_after_a_later_rebuild(
    isolated_postgres_client,
):
    journeys.test_draft_lists_and_reads_keep_revoked_sources_hidden_after_a_later_rebuild(
        isolated_postgres_client
    )


def test_draft_lists_and_reads_are_bounded_at_production_private_index_volume(
    isolated_postgres_client,
):
    targets = journeys.build_draft_targets(
        isolated_postgres_client,
        after_rebuild=_retain_production_volume,
    )
    with get_session_factory()() as session:
        retained = session.scalar(
            text(
                "SELECT count(*) FROM private_index_projections "
                "WHERE company_id = :company_id AND source_type = 'client'"
            ),
            {"company_id": targets["company_id"]},
        )
        generations = session.scalar(
            text("SELECT count(*) FROM private_index_generations WHERE company_id = :company_id"),
            {"company_id": targets["company_id"]},
        )
        ledger = session.scalar(
            text("SELECT count(*) FROM private_projection_events WHERE company_id = :company_id"),
            {"company_id": targets["company_id"]},
        )
    assert retained >= 2 * RETAINED_PROJECTIONS_PER_GENERATION
    assert generations >= 2
    assert ledger >= 2 * RETAINED_EVENTS_PER_GENERATION
    journeys.assert_bounded_draft_lists(
        isolated_postgres_client,
        targets,
        copies=3,
        repeat=4,
        prepare_session=_adverse_statement_budget,
    )
