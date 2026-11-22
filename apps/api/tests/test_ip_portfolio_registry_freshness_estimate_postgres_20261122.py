"""The Registry freshness filter stays linear at tenant width (B4-ADJ-44).

``registry_sync_state`` compared a correlated ``max(ip_docket_events.entered_at)``
scalar subquery with ``IS NULL``, ``IS NOT NULL`` and ``<`` / ``>=``. PostgreSQL
estimates ``(scalar subquery) IS NULL`` at a fixed 0.5%, the estimate class of
B4-ADJ-41, so the ``unavailable`` filter planned about one matching docket and
rescanned the portfolio per docket. The filter now tests the same seek with
``[NOT] EXISTS``. This test seeds 1,000 dockets, gives a few hundred of them
fresh, old, unconfirmed and non-registry events, analyzes, rejects the quadratic
plan shape, and checks each list read returns exactly the expected application count.
"""

import pytest
from sqlalchemy import text

from tests.test_ip_portfolio_policy_estimate_postgres_20261106 import WIDTH, _portfolio_rescans

pytestmark = pytest.mark.postgres

FRESH = 150
OLD = 150
UNCONFIRMED = 100
OTHER_SOURCE = 100


def _registry_events(connection):
    # Dockets are split by id order: fresh confirmed sync, old confirmed sync,
    # fresh unconfirmed sync, fresh confirmed non-registry event, then none.
    company_id, membership_id = connection.execute(
        text(
            "SELECT company_id, id FROM company_memberships "
            "WHERE company_id = (SELECT company_id FROM ip_docket_records LIMIT 1) LIMIT 1"
        )
    ).one()
    offset = 0
    for count, source, status, age in (
        (FRESH, "registry_sync", "confirmed", "1 hour"),
        (OLD, "registry_sync", "confirmed", "3 days"),
        (UNCONFIRMED, "registry_sync", "candidate", "1 hour"),
        (OTHER_SOURCE, "import", "confirmed", "1 hour"),
    ):
        inserted = connection.execute(
            text(
                "INSERT INTO ip_docket_events (id, company_id, docket_id, sequence, event_kind, "
                "source, source_reference, effective_at, entered_at, responsible_membership_id, "
                "entered_by_membership_id, evidence_refs_json, document_refs_json, "
                "resulting_deadline_refs_json, candidate_status, payload_json, created_at) "
                "SELECT gen_random_uuid()::text, d.company_id, d.id, "
                "COALESCE((SELECT max(e.sequence) FROM ip_docket_events e "
                "WHERE e.company_id = d.company_id AND e.docket_id = d.id), 0) + 1, "
                "'registry_snapshot_accepted', CAST(:source AS VARCHAR), 'b4-adj-44', "
                "now() - CAST(:age AS INTERVAL), now() - CAST(:age AS INTERVAL), "
                "CAST(:membership AS VARCHAR), CAST(:membership AS VARCHAR), '[]', '[]', '[]', "
                "CAST(:status AS VARCHAR), '{}', now() "
                "FROM (SELECT id, company_id FROM ip_docket_records "
                "WHERE company_id = CAST(:company AS VARCHAR) "
                "ORDER BY id OFFSET :offset LIMIT :rows) d"
            ),
            {
                "company": company_id,
                "membership": membership_id,
                "source": source,
                "status": status,
                "age": age,
                "offset": offset,
                "rows": count,
            },
        )
        assert inserted.rowcount == count
        offset += count


def test_registry_freshness_filters_never_rescan_per_docket(
    isolated_postgres_client, monkeypatch, record_property
):
    never_synced = WIDTH - FRESH - OLD
    expected = {
        "unavailable": never_synced,
        "stale": OLD,
        "current": FRESH,
        "stale-or-unavailable": OLD + never_synced,
    }
    requests = {
        "unavailable": ("/api/ip/portfolio", {"registry_sync_state": "unavailable", "limit": 50}),
        "unavailable-families": (
            "/api/ip/portfolio/families",
            {"registry_sync_state": "unavailable"},
        ),
        "stale": ("/api/ip/portfolio", {"registry_sync_state": "stale", "limit": 50}),
        "current": ("/api/ip/portfolio", {"registry_sync_state": "current", "limit": 50}),
        "stale-or-unavailable": (
            "/api/ip/portfolio",
            {"registry_sync_state": ["stale", "unavailable"], "limit": 50},
        ),
    }
    bodies = {}
    rescans = _portfolio_rescans(
        isolated_postgres_client,
        monkeypatch,
        record_property,
        requests,
        prepare=_registry_events,
        bodies=bodies,
    )
    # Family reads page by family, so only the list reads carry a total.
    observed = {
        label: body["counts"]["total"] for label, body in bodies.items() if "counts" in body
    }
    assert observed == expected
    assert bodies["unavailable-families"]["families"]
    assert rescans == {}
