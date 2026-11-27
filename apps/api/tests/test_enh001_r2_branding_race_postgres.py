"""ENH-001 review: two first-time branding saves race safely on PostgreSQL too.

The SQLite journeys in ``test_enh001_r2_verification_and_counsel_ids`` commit a
competing row between the existence check and the insert; here the same
journeys run against PostgreSQL, where the loser's insert fails on the unique
constraint inside the request's open transaction.
"""

import pytest

from tests import test_enh001_r2_verification_and_counsel_ids as journeys

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "check",
    [
        journeys.test_racing_first_branding_patch_updates_the_winner_row,
        journeys.test_racing_first_branding_upload_updates_the_winner_row,
    ],
)
def test_first_branding_save_race_on_postgres(isolated_postgres_client, monkeypatch, check):
    check(isolated_postgres_client, monkeypatch)
