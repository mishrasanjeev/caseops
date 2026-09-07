"""Real PostgreSQL seed upgrade and HTTP contracts for BUG-010."""

import pytest

from tests import test_official_statute_release as journeys

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "journey",
    [
        "test_complete_release_seed_details_history_and_idempotence",
        "test_seed_preserves_reviewed_labels_and_pending_history_when_upgrading_legacy_rows",
    ],
)
def test_official_release_on_postgres(isolated_postgres_client, journey):
    getattr(journeys, journey)(isolated_postgres_client)
