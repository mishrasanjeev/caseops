from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from caseops_api.services.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    clamp_limit,
    decode_cursor,
    encode_cursor,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def test_clamp_limit_defaults_for_none_or_zero() -> None:
    assert clamp_limit(None) == DEFAULT_PAGE_SIZE
    assert clamp_limit(0) == DEFAULT_PAGE_SIZE
    assert clamp_limit(-1) == DEFAULT_PAGE_SIZE


def test_clamp_limit_caps_at_max() -> None:
    assert clamp_limit(MAX_PAGE_SIZE + 50) == MAX_PAGE_SIZE
    assert clamp_limit(10) == 10


def test_cursor_roundtrip() -> None:
    dt = datetime(2026, 4, 17, 12, 30, 45, tzinfo=UTC)
    encoded = encode_cursor(dt, "abc-123")
    decoded = decode_cursor(encoded)
    assert decoded is not None
    assert decoded.updated_at == dt
    assert decoded.id == "abc-123"


@pytest.mark.parametrize("bogus", ["", "not-base64!!", "abcdef", None])
def test_decode_cursor_is_forgiving(bogus: str | None) -> None:
    # Callers treat None as "start from top", so an invalid cursor must
    # not raise — it returns None and the list just starts fresh.
    assert decode_cursor(bogus) is None


def _seed_matters(
    client: TestClient, token: str, count: int, *, start: int = 0
) -> None:
    for i in range(start, start + count):
        resp = client.post(
            "/api/matters/",
            headers=auth_headers(token),
            json={
                "title": f"Matter {i:03d}",
                "matter_code": f"PAGE-{i:03d}",
                "practice_area": "Commercial",
                "forum_level": "high_court",
                "status": "active",
            },
        )
        assert resp.status_code == 200, resp.text


def test_matters_list_paginates(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _seed_matters(client, token, 7)

    first = client.get(
        "/api/matters/", headers=auth_headers(token), params={"limit": 3}
    )
    assert first.status_code == 200
    page1 = first.json()
    assert len(page1["matters"]) == 3
    assert page1["next_cursor"] is not None

    second = client.get(
        "/api/matters/",
        headers=auth_headers(token),
        params={"limit": 3, "cursor": page1["next_cursor"]},
    )
    assert second.status_code == 200
    page2 = second.json()
    assert len(page2["matters"]) == 3
    assert page2["next_cursor"] is not None

    third = client.get(
        "/api/matters/",
        headers=auth_headers(token),
        params={"limit": 3, "cursor": page2["next_cursor"]},
    )
    assert third.status_code == 200
    page3 = third.json()
    assert len(page3["matters"]) == 1  # 7 total, 3+3+1
    assert page3["next_cursor"] is None

    # No overlap across pages.
    ids_seen: set[str] = set()
    for page in (page1, page2, page3):
        for m in page["matters"]:
            assert m["id"] not in ids_seen
            ids_seen.add(m["id"])
    assert len(ids_seen) == 7


def test_matters_list_honours_max_page_size(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _seed_matters(client, token, 3)
    resp = client.get(
        "/api/matters/",
        headers=auth_headers(token),
        params={"limit": 10_000},
    )
    assert resp.status_code == 200
    # 3 rows total, limit clamped to MAX_PAGE_SIZE (>3), so all fit on page 1.
    assert len(resp.json()["matters"]) == 3
    assert resp.json()["next_cursor"] is None


def test_invalid_cursor_falls_back_to_first_page(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    _seed_matters(client, token, 2)
    resp = client.get(
        "/api/matters/",
        headers=auth_headers(token),
        params={"cursor": "totally-not-a-cursor"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["matters"]) == 2


def test_keyset_is_stable_under_insert(client: TestClient) -> None:
    """A new matter inserted mid-paging must not shift the current cursor."""
    token = str(bootstrap_company(client)["access_token"])
    _seed_matters(client, token, 5)

    first = client.get(
        "/api/matters/", headers=auth_headers(token), params={"limit": 2}
    )
    cursor = first.json()["next_cursor"]
    first_ids = {m["id"] for m in first.json()["matters"]}

    # Insert an additional matter between page fetches.
    _seed_matters(client, token, 1, start=5)

    second = client.get(
        "/api/matters/",
        headers=auth_headers(token),
        params={"limit": 2, "cursor": cursor},
    )
    second_ids = {m["id"] for m in second.json()["matters"]}
    # Keyset keeps the second page strictly below the cursor so no row
    # from page 1 reappears on page 2 even though we inserted since.
    assert first_ids.isdisjoint(second_ids)


def test_contracts_list_paginates(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    for i in range(5):
        resp = client.post(
            "/api/contracts/",
            headers=auth_headers(token),
            json={
                "title": f"Contract {i:03d}",
                "contract_code": f"CTR-PAGE-{i:03d}",
                "contract_type": "Master Services Agreement",
                "status": "draft",
                "counterparty_name": f"Counter {i}",
            },
        )
        assert resp.status_code == 200, resp.text

    first = client.get(
        "/api/contracts/", headers=auth_headers(token), params={"limit": 2}
    )
    assert first.status_code == 200
    payload = first.json()
    assert len(payload["contracts"]) == 2
    assert payload["next_cursor"] is not None

    second = client.get(
        "/api/contracts/",
        headers=auth_headers(token),
        params={"limit": 10, "cursor": payload["next_cursor"]},
    )
    assert second.status_code == 200
    assert len(second.json()["contracts"]) == 3
    assert second.json()["next_cursor"] is None


def test_cursor_encodes_monotonically(client: TestClient) -> None:
    early = datetime(2026, 4, 1, tzinfo=UTC)
    later = early + timedelta(days=5)
    c1 = encode_cursor(early, "id-early")
    c2 = encode_cursor(later, "id-later")
    assert c1 != c2
    d1 = decode_cursor(c1)
    d2 = decode_cursor(c2)
    assert d1 is not None and d2 is not None
    assert d1.updated_at < d2.updated_at
