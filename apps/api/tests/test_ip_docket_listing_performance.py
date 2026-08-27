from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import event

from caseops_api.db.session import get_engine
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_prd_slices import _particulars


def test_ip_docket_listing_is_bounded_and_has_constant_query_count(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    for index in range(26):
        response = client.post(
            "/api/ip/dockets",
            headers=headers,
            json={
                "title": f"Bounded docket {index:02d}",
                "primary_identifier": f"TM-BOUND-{index:02d}",
                "particulars": _particulars(mark=f"BOUND {index:02d}"),
            },
        )
        assert response.status_code == 201, response.text

    query_count = 0

    def count_query(*_args: object) -> None:
        nonlocal query_count
        query_count += 1

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", count_query)
    try:
        response = client.get("/api/ip/dockets?limit=25", headers=headers)
    finally:
        event.remove(engine, "before_cursor_execute", count_query)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["count"] == 25
    assert len(payload["dockets"]) == 25
    assert payload["has_more"] is True
    assert query_count <= 18
