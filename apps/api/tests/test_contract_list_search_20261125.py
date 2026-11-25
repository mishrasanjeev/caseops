"""Contracts list: server search and total (adjacent path of Nov 24 workbook row 5).

The Contracts page had the same defect as Matters: its search box and pager
only saw the 50 contracts already loaded. The API had no search parameter at
all, so the page could not have searched the rest. These tests pin the server
contract the page now uses.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_legalworkspace_matter_search_tags import _auth, _bootstrap


def _create(client: TestClient, token: str, index: int, **fields: object) -> None:
    payload = {
        "title": f"Supply agreement {index:02d}",
        "contract_code": f"CON-{index:02d}",
        "contract_type": "Supply",
        "counterparty_name": f"Vendor {index:02d}",
        **fields,
    }
    response = client.post("/api/contracts/", headers=_auth(token), json=payload)
    assert response.status_code == 200, response.text


def _list(client: TestClient, token: str, **params: object) -> dict:
    response = client.get("/api/contracts/", headers=_auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_search_finds_a_contract_beyond_the_first_page(client: TestClient) -> None:
    token = str(_bootstrap(client, "nov24-contracts", "owner")["access_token"])
    _create(
        client, token, 0, title="Warehouse lease Bhiwandi", counterparty_name="Kaveri Logistics"
    )
    for index in range(1, 7):
        _create(client, token, index)

    first = _list(client, token, limit=3, include_total="true")
    assert first["total_count"] == 7
    assert "CON-00" not in {c["contract_code"] for c in first["contracts"]}

    for needle in ("bhiwandi", "con-00", "Kaveri"):
        body = _list(client, token, q=needle, limit=3, include_total="true")
        assert [c["contract_code"] for c in body["contracts"]] == ["CON-00"], needle
        assert body["total_count"] == 1
        assert body["next_cursor"] is None

    codes: list[str] = []
    cursor = None
    totals = []
    while True:
        params: dict[str, object] = {"q": "Vendor", "limit": 2, "include_total": "true"}
        if cursor:
            params["cursor"] = cursor
        body = _list(client, token, **params)
        codes.extend(c["contract_code"] for c in body["contracts"])
        totals.append(body["total_count"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert set(totals) == {6}
    assert sorted(codes) == [f"CON-{i:02d}" for i in range(1, 7)]
    assert len(totals) == 3  # two page boundaries


def test_search_and_total_stay_inside_the_tenant(client: TestClient) -> None:
    mine = str(_bootstrap(client, "nov24-con-a", "owner")["access_token"])
    theirs = str(_bootstrap(client, "nov24-con-b", "owner")["access_token"])
    _create(client, mine, 1, title="Shared phrase agreement")
    _create(client, theirs, 2, title="Shared phrase agreement")

    body = _list(client, mine, q="Shared phrase", include_total="true")
    assert [c["contract_code"] for c in body["contracts"]] == ["CON-01"]
    assert body["total_count"] == 1
    assert _list(client, mine)["total_count"] is None
