"""Replay original Portal/source-date HTTP assertions on isolated PostgreSQL."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from caseops_api.db.session import get_session_factory
from tests import (
    test_ip_current_source_reminders_20261013 as source_reminders,
)
from tests import (
    test_ip_portfolio_spec_20261013 as portfolio,
)
from tests import (
    test_portal_ip as portal,
)
from tests.test_ip_current_source_reminders_20261013 import (
    reminder_clock as _source_reminder_clock,
)
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres
reminder_clock = _source_reminder_clock


@pytest.fixture(autouse=True)
def _assert_native_client_database(
    isolated_postgres_client: TestClient,
    http_pg_engine: Engine,
) -> None:
    assert http_pg_engine.dialect.name == "postgresql"
    assert isolated_postgres_client.headers["X-CaseOps-Automated-Test"] == "no-paid-providers"
    with get_session_factory()() as session:
        bind = session.get_bind()
        assert bind.dialect.name == "postgresql"
        assert bind.url == http_pg_engine.url


def test_native_portal_report_instruction_acknowledgement_and_revoke(
    isolated_postgres_client: TestClient,
) -> None:
    portal.test_ip_portal_report_instruction_acknowledgement_and_revoke(isolated_postgres_client)


def test_native_report_publication_rejects_stale_preview_and_withholds_stale_targets(
    isolated_postgres_client: TestClient,
) -> None:
    portal.test_report_publication_rejects_stale_preview_and_withholds_stale_targets(
        isolated_postgres_client
    )


@pytest.mark.parametrize("invalidation", ["privileged", "patent_link", "patent_domain"])
def test_native_document_publication_allows_only_granted_approved_nonprivileged_version(
    isolated_postgres_client: TestClient,
    invalidation: str,
) -> None:
    portal.test_document_publication_allows_only_granted_approved_nonprivileged_version(
        isolated_postgres_client, invalidation
    )


def test_native_portal_lists_keep_a_fixed_query_budget_as_rows_grow(
    isolated_postgres_client: TestClient,
) -> None:
    portal.test_portal_lists_keep_a_fixed_query_budget_as_rows_grow(isolated_postgres_client)


def test_native_source_alert_uses_tenant_timezone_without_workspace_configuration(
    isolated_postgres_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio.test_source_alert_uses_tenant_timezone_without_workspace_configuration(
        isolated_postgres_client, monkeypatch
    )


def test_native_due_soon_alert_uses_existing_delivery_owner_and_idempotency(
    isolated_postgres_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio.test_due_soon_alert_uses_existing_delivery_owner_and_idempotency(
        isolated_postgres_client, monkeypatch
    )


@pytest.mark.parametrize("active", [True, False], ids=["authorized-recipient", "revoked-recipient"])
def test_native_source_reminder_actual_in_app_dispatch_rechecks_recipient(
    isolated_postgres_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    active: bool,
) -> None:
    portfolio.test_source_reminder_actual_in_app_dispatch_rechecks_recipient(
        isolated_postgres_client, monkeypatch, active
    )


@pytest.mark.parametrize("new_due", ["2028-04-30", None], ids=["date-change", "date-removal"])
def test_native_source_predicate_rejects_actual_canonical_version_correction(
    isolated_postgres_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    new_due: str | None,
) -> None:
    portfolio.test_source_predicate_rejects_actual_canonical_version_correction(
        isolated_postgres_client, monkeypatch, new_due
    )


def test_native_source_date_edit_clear_stale_replay_and_actual_delivery(
    isolated_postgres_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio.test_source_date_edit_clear_stale_replay_and_actual_delivery(
        isolated_postgres_client, monkeypatch
    )


@pytest.mark.parametrize("boundary", ["revoked-recipient", "retained-old-version", "removed-date"])
def test_native_current_facts_do_not_bypass_delivery_fences(
    isolated_postgres_client: TestClient,
    reminder_clock,
    boundary: str,
) -> None:
    source_reminders.test_current_facts_do_not_bypass_delivery_fences(
        isolated_postgres_client, reminder_clock, boundary
    )
