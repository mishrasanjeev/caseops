"""Real PostgreSQL proof; independent migrated HTTP template, never tenant clones."""

import pytest

from tests import test_20260910_hearing_matching_races as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
@pytest.mark.parametrize("defect", ["missing_court", "malformed_cnr"])
def test_existing_incomplete_bookmark_recovers_after_matter_correction(
    isolated_postgres_client, monkeypatch, boundary, defect
):
    journeys.test_legacy_bookmark_requires_court_and_recovers_from_current_matter(
        isolated_postgres_client, monkeypatch, boundary, defect
    )


@pytest.mark.parametrize("boundary", ["manual", "scheduled"])
@pytest.mark.parametrize(
    "change",
    [
        "none",
        "case_number",
        "court_name",
        "filing_number",
        "opposing_party",
        "dispose",
        "archive",
        "membership",
    ],
)
def test_non_cnr_transport_races(isolated_postgres_client, monkeypatch, boundary, change):
    journeys.exercise_boundary(isolated_postgres_client, monkeypatch, boundary, change)


@pytest.mark.parametrize("ambient", ["true", "false"])
@pytest.mark.parametrize("mode", ["case_number", "filing_number"])
def test_legacy_identifier_discovery_and_persisted_nearest_date(
    isolated_postgres_client, monkeypatch, ambient, mode
):
    journeys.test_scheduled_legacy_discovery_uses_current_identifiers_and_nearest_date(
        isolated_postgres_client,
        monkeypatch,
        ambient,
        mode,
    )
