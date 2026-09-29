"""The hidden-control HTTP regressions on independently isolated PostgreSQL."""

from __future__ import annotations

import pytest

from tests import test_20260929_assistant_hidden_controls as journeys
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "hidden_by",
    [
        "locked",
        "reauthorization_required",
        "redacted",
        "citation_version",
    ],
)
def test_hidden_turns_and_exports_remove_private_labels_links_and_controls(
    isolated_postgres_client,
    monkeypatch,
    hidden_by,
):
    journeys.test_hidden_turns_and_exports_remove_private_labels_links_and_controls(
        isolated_postgres_client,
        monkeypatch,
        hidden_by,
    )


@pytest.mark.parametrize("confirmed", [False, True], ids=["pending-write", "confirmed-replay"])
def test_hidden_answer_rejects_cached_preview_confirmation_and_result_replay(
    isolated_postgres_client,
    monkeypatch,
    confirmed,
):
    journeys.test_hidden_answer_rejects_cached_preview_confirmation_and_result_replay(
        isolated_postgres_client,
        monkeypatch,
        confirmed,
    )
