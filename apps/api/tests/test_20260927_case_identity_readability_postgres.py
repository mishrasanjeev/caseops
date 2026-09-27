"""Real PostgreSQL proof for the 2026-09-27 automatic-path identity decision.

The scheduled poll gates each tracked case inside a savepoint and the manual
refresh inside the request transaction, before any provider spend; SQLite cannot
prove either boundary on the production engine.
"""

import pytest

from tests import test_20260927_case_identity_readability as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(("code", "fields", "expected"), journeys.AUTO_LINK_CASES)
def test_automatic_link_at_matter_creation_uses_the_manual_identity_decision(
    isolated_postgres_client, monkeypatch, code, fields, expected
):
    journeys.test_automatic_link_at_matter_creation_uses_the_manual_identity_decision(
        isolated_postgres_client, monkeypatch, code, fields, expected
    )


def test_scheduled_backfill_never_finds_a_case_from_a_bare_number(
    isolated_postgres_client, monkeypatch
):
    journeys.test_scheduled_backfill_never_finds_a_case_from_a_bare_number(
        isolated_postgres_client, monkeypatch
    )


def test_existing_automatic_link_stops_before_the_provider_when_the_type_is_lost(
    isolated_postgres_client, monkeypatch
):
    journeys.test_existing_automatic_link_stops_before_the_provider_when_the_type_is_lost(
        isolated_postgres_client, monkeypatch
    )


@pytest.mark.parametrize(
    ("fields", "reason", "message"),
    [
        (
            {"case_number": "WP(C) 6d661b/2026"},
            "unreadable_case_number",
            journeys.CASE_NUMBER_UNREADABLE,
        ),
        ({"case_number": "6209/2019"}, "case_type_required", journeys.CASE_TYPE_REQUIRED),
    ],
)
def test_resolve_and_search_name_the_gap_before_any_provider_call(
    isolated_postgres_client, monkeypatch, fields, reason, message
):
    journeys.test_resolve_and_search_name_the_gap_before_any_provider_call(
        isolated_postgres_client, monkeypatch, fields, reason, message
    )
