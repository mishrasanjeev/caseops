"""Real PostgreSQL proof for batched appeal-strength citation resolution.

The same journey as the SQLite regression: statement counts stay constant as
grounds and citations grow, and every citation resolves as the deterministic
per-citation rule does. PostgreSQL orders ``created_at`` as a real timestamp,
where SQLite compares stored text.
"""

from __future__ import annotations

import pytest

from tests import test_20260928_appeal_strength_citation_batch as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_appeal_strength_resolves_every_citation_in_one_statement_on_postgres(
    isolated_postgres_client,
):
    journeys.analyze_small_and_large(isolated_postgres_client)


def test_largest_accepted_draft_stays_below_the_parameter_ceiling_on_postgres(
    isolated_postgres_client,
):
    journeys.analyze_largest_accepted_draft(isolated_postgres_client)
