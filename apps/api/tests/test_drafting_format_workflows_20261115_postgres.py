"""Replay every new format HTTP journey on the canonical isolated PostgreSQL client.

The ordinary client fixture always uses SQLite. These are explicit PostgreSQL
cases, not a claim that changing an environment URL changes that fixture.
"""
from __future__ import annotations

import pytest

from tests import test_drafting_format_workflows_20261115 as journeys

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("template_type,facts", journeys._reference_cases())
def test_postgres_format_preview_generation_review_history_and_exports(
    isolated_postgres_client, monkeypatch, template_type, facts,
):
    journeys.test_new_format_preview_generation_review_history_and_real_exports(
        isolated_postgres_client, monkeypatch, template_type, facts,
    )


@pytest.mark.parametrize("facts", journeys.INVALID_DEED_FACTS)
def test_postgres_invalid_deed_has_no_persisted_side_effects(
    isolated_postgres_client, monkeypatch, facts,
):
    journeys.test_invalid_new_deed_is_refused_over_http_without_persisted_side_effects(
        isolated_postgres_client, monkeypatch, facts,
    )


@pytest.mark.parametrize("template,field,valid", journeys.EXISTING_VARIANT_CASES)
def test_postgres_invalid_existing_variant_admission_and_retained_generation(
    isolated_postgres_client, monkeypatch, template, field, valid,
):
    journeys.test_invalid_existing_variant_is_refused_before_admission_and_retained_generation(
        isolated_postgres_client, monkeypatch, template, field, valid,
    )


@pytest.mark.parametrize("template_type,facts", journeys.MISSING_LAW_CASES)
def test_postgres_required_law_has_safe_errors_and_no_writes(
    isolated_postgres_client, template_type, facts,
):
    journeys.test_required_governing_law_is_enforced_by_the_http_server_without_echoing_inputs(
        isolated_postgres_client, template_type, facts,
    )


def test_postgres_reference_keeps_zero_citation_approval_and_export_guards(
    isolated_postgres_client, monkeypatch,
):
    journeys.test_new_reference_does_not_bypass_zero_citation_approval_or_export_controls(
        isolated_postgres_client, monkeypatch,
    )


@pytest.mark.parametrize("retained_approved_fixture", [False, True])
def test_postgres_execution_table_refusal_and_repaired_revision(
    isolated_postgres_client, monkeypatch, retained_approved_fixture,
):
    journeys.test_incomplete_execution_table_cannot_be_approved_finalized_or_exported(
        isolated_postgres_client, monkeypatch, retained_approved_fixture,
    )
