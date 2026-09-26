"""Real PostgreSQL proof for the 2026-09-26 case identity policy.

The existing-matter annotation normalizes stored CNRs in SQL; SQLite cannot
prove that expression or the visibility filter's PostgreSQL plan.
"""

import pytest

from tests import test_20260926_case_match_policy as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


def test_cnr_identifies_the_case_despite_court_and_party_wording(
    isolated_postgres_client, monkeypatch
):
    journeys.test_cnr_identifies_the_case_despite_court_and_party_wording(
        isolated_postgres_client, monkeypatch
    )


def test_a_different_cnr_never_matches_even_with_identical_wording(
    isolated_postgres_client, monkeypatch
):
    journeys.test_a_different_cnr_never_matches_even_with_identical_wording(
        isolated_postgres_client, monkeypatch
    )


def test_without_a_cnr_the_case_number_needs_the_provider_case_type_and_court(
    isolated_postgres_client, monkeypatch
):
    journeys.test_without_a_cnr_the_case_number_needs_the_provider_case_type_and_court(
        isolated_postgres_client, monkeypatch
    )


def test_search_and_refresh_share_one_identity_policy(isolated_postgres_client, monkeypatch):
    journeys.test_search_and_refresh_share_one_identity_policy(
        isolated_postgres_client, monkeypatch
    )


def test_global_search_reports_only_visible_existing_matters(
    isolated_postgres_client, monkeypatch
):
    journeys.test_global_search_reports_only_visible_existing_matters(
        isolated_postgres_client, monkeypatch
    )


def test_link_rejects_a_selection_without_signed_provider_identity(
    isolated_postgres_client, monkeypatch
):
    journeys.test_link_rejects_a_selection_without_signed_provider_identity(
        isolated_postgres_client, monkeypatch
    )
