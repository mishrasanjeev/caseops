"""The provider-operations cap advice is true in the view that gives it (B4-ADJ-15).

The admin page caps the list at one read. In "Needs action only" view
(include_resolved=false) it tells the operator that resolving or ignoring a
listed operation brings the next one in; in the "All operations" view a
handled row stays listed, so that advice would be false there.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_provider_operations import _notification_intent_fixture


def test_handling_an_operation_brings_the_next_one_into_the_open_view(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    company_id = str(boot["company"]["id"])
    membership_id = str(boot["membership"]["id"])
    created = {
        "notification_delivery:"
        + _notification_intent_fixture(company_id=company_id, membership_id=membership_id)
        for _ in range(3)
    }

    def read(include_resolved: bool) -> dict:
        response = client.get(
            "/api/admin/provider-operations/jobs",
            headers=headers,
            params={"limit": 2, "include_resolved": str(include_resolved).lower()},
        )
        assert response.status_code == 200, response.text
        return response.json()

    capped = read(False)
    assert capped["has_more"] is True and capped["returned_count"] == 2
    listed = [row["id"] for row in capped["operations"]]
    hidden = created - set(listed)
    assert len(hidden) == 1

    resolved = client.post(
        f"/api/admin/provider-operations/jobs/{listed[0]}/mark-resolved",
        headers=headers,
        json={"reason": "Handled in the provider console."},
    )
    assert resolved.status_code == 200, resolved.text
    ignored = client.post(
        f"/api/admin/provider-operations/jobs/{listed[1]}/ignore",
        headers=headers,
        json={"reason": "Known duplicate provider event."},
    )
    assert ignored.status_code == 200, ignored.text

    after = read(False)
    assert [row["id"] for row in after["operations"]] == list(hidden)
    assert after["has_more"] is False

    # The "All operations" view keeps handled rows, which is why the page
    # never tells the operator to resolve rows there to make room.
    everything = read(True)
    assert {row["id"] for row in everything["operations"]} <= created
    assert everything["has_more"] is True
    assert {row["operator_state"] for row in everything["operations"]} & {"resolved", "ignored"}
