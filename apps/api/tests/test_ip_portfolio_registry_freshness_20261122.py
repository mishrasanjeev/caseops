"""Registry freshness filters select exactly the right dockets (B4-ADJ-44).

The filter moved from a ``max(entered_at)`` scalar subquery to ``[NOT] EXISTS``
over the same confirmed ``registry_sync`` seek. Each docket below isolates one
way a branch could drift: no event, only an old or only a fresh confirmed sync,
both, an old sync with a fresh unconfirmed one, and fresh events that are not
confirmed registry syncs. Every state and combination must return exactly its
dockets, and each row's displayed state must agree with the filter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import combinations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import IpDocketEvent, IpDocketRecord
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_portfolio_listing import _application, _asset, _docket, _portfolio

FRESH = timedelta(hours=1)
OLD = timedelta(days=3)

# docket label -> events as (source, candidate_status, age)
DOCKETS = {
    "never-synced": [],
    "old-sync": [("registry_sync", "confirmed", OLD)],
    "fresh-sync": [("registry_sync", "confirmed", FRESH)],
    "old-and-fresh-sync": [
        ("registry_sync", "confirmed", OLD),
        ("registry_sync", "confirmed", FRESH),
    ],
    "old-sync-fresh-candidate": [
        ("registry_sync", "confirmed", OLD),
        ("registry_sync", "candidate", FRESH),
    ],
    "fresh-candidate-only": [("registry_sync", "candidate", FRESH)],
    "fresh-other-source-only": [("import", "confirmed", FRESH)],
}
EXPECTED = {
    "current": {"fresh-sync", "old-and-fresh-sync"},
    "stale": {"old-sync", "old-sync-fresh-candidate"},
    "unavailable": {"never-synced", "fresh-candidate-only", "fresh-other-source-only"},
    "failed": set(),
}


def _seed(client: TestClient) -> tuple[dict[str, str], dict[str, str]]:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-REG-FRESH")
    applications: dict[str, str] = {}
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        for index, (label, events) in enumerate(DOCKETS.items()):
            docket = _docket(
                client, headers, matter_id=matter["id"], title=f"Freshness Mark {index}"
            )
            asset = _asset(client, headers, docket_id=docket["id"], title=f"Freshness {index}")
            application = _application(
                client, headers, docket_id=docket["id"], asset_id=asset["id"]
            )
            applications[application["id"]] = label
            row = session.get(IpDocketRecord, docket["id"])
            assert row is not None and row.created_by_membership_id
            sequence = session.scalar(
                select(func.coalesce(func.max(IpDocketEvent.sequence), 0)).where(
                    IpDocketEvent.company_id == row.company_id,
                    IpDocketEvent.docket_id == row.id,
                )
            )
            for source, status, age in events:
                sequence += 1
                session.add(
                    IpDocketEvent(
                        company_id=row.company_id,
                        docket_id=row.id,
                        sequence=sequence,
                        application_id=application["id"],
                        event_kind="registry_snapshot_accepted",
                        source=source,
                        source_reference=f"b4-adj-44:{label}",
                        effective_at=now - age,
                        entered_at=now - age,
                        responsible_membership_id=row.created_by_membership_id,
                        entered_by_membership_id=row.created_by_membership_id,
                        candidate_status=status,
                    )
                )
        session.commit()
    return headers, applications


def test_registry_freshness_states_return_exactly_their_dockets(client: TestClient) -> None:
    headers, applications = _seed(client)
    states = sorted(EXPECTED)
    checked = 0
    for size in range(1, len(states) + 1):
        for selected in combinations(states, size):
            response = _portfolio(client, headers, registry_sync_state=list(selected), limit=200)
            assert response.status_code == 200, response.text
            body = response.json()
            rows = body["rows"]
            returned = {applications[row["application_id"]] for row in rows}
            expected = set().union(*(EXPECTED[state] for state in selected))
            assert returned == expected, selected
            assert body["counts"]["total"] == len(expected), selected
            assert len(rows) == len(expected), selected
            for row in rows:
                assert row["registry_sync_state"] in selected, (selected, row)
                assert applications[row["application_id"]] in EXPECTED[row["registry_sync_state"]]
            checked += 1
    assert checked == 2 ** len(states) - 1

    unfiltered = _portfolio(client, headers, limit=200)
    assert unfiltered.status_code == 200, unfiltered.text
    assert {applications[row["application_id"]] for row in unfiltered.json()["rows"]} == set(
        DOCKETS
    )
