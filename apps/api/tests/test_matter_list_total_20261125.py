"""Matters list: server search and paging with a real total (Nov 24 workbook rows 4-5).

The Matters page used to page and search only the rows already loaded in the
browser, so a matter on an unloaded page was "not found" and Next stopped at
the last loaded page. The page now asks the server for each page and for the
total. These tests pin the server contract it relies on:

* the total counts every visible matching Matter, across page boundaries, and
  does not change with the page asked for;
* a search finds a Matter that sits beyond the first page, by title, code and
  client;
* walking every page returns each Matter exactly once;
* the total never counts another tenant's Matters, a restricted Matter or a
  walled Matter the reader cannot open.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_legalworkspace_matter_search_tags import (
    _auth,
    _bootstrap,
    _create_matter,
    _invite_member,
)

PAGE = 3


def _list(client: TestClient, token: str, **params: object) -> dict:
    response = client.get("/api/matters/", headers=_auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _walk(client: TestClient, token: str, **params: object) -> tuple[list[str], list[int | None]]:
    codes: list[str] = []
    totals: list[int | None] = []
    cursor: str | None = None
    for _ in range(50):
        query = {**params, "limit": PAGE, "include_total": "true"}
        if cursor:
            query["cursor"] = cursor
        body = _list(client, token, **query)
        codes.extend(m["matter_code"] for m in body["matters"])
        totals.append(body["total_count"])
        cursor = body["next_cursor"]
        if not cursor:
            break
    return codes, totals


def _seed(client: TestClient, token: str, count: int, prefix: str) -> list[str]:
    codes = []
    for index in range(count):
        code = f"{prefix}-{index:02d}"
        _create_matter(
            client,
            token,
            code,
            title=f"Portfolio matter {index:02d}",
            client_name="Shared Client" if index % 2 else "Other Client",
            status="intake",
        )
        codes.append(code)
    return codes


def test_total_is_opt_in_and_old_clients_are_unchanged(client: TestClient) -> None:
    owner = _bootstrap(client, "nov24-optin", "owner")
    token = str(owner["access_token"])
    _seed(client, token, 2, "OPT")

    body = _list(client, token, limit=1)
    assert body["total_count"] is None
    assert len(body["matters"]) == 1
    assert body["next_cursor"]


def test_total_and_pages_cover_every_matter_exactly_once(client: TestClient) -> None:
    owner = _bootstrap(client, "nov24-walk", "owner")
    token = str(owner["access_token"])
    seeded = _seed(client, token, 8, "WALK")

    codes, totals = _walk(client, token)
    # 8 matters at 3 per page crosses two page boundaries (3 + 3 + 2).
    assert len(totals) == 3
    assert totals == [8, 8, 8]
    assert sorted(codes) == sorted(seeded)
    assert len(codes) == len(set(codes))


def test_search_reaches_matters_beyond_the_first_page(client: TestClient) -> None:
    owner = _bootstrap(client, "nov24-search", "owner")
    token = str(owner["access_token"])
    _create_matter(
        client,
        token,
        "DEEP-TARGET",
        title="Sharma Textiles recovery suit",
        client_name="Kaveri Mills",
        status="intake",
    )
    # Created later, so they sort ahead of the target and push it off page 1.
    _seed(client, token, 7, "FILL")
    first_page = _list(client, token, limit=PAGE)
    assert "DEEP-TARGET" not in {m["matter_code"] for m in first_page["matters"]}

    for needle in ("Sharma Textiles", "deep-target", "kaveri"):
        body = _list(client, token, q=needle, limit=PAGE, include_total="true")
        assert [m["matter_code"] for m in body["matters"]] == ["DEEP-TARGET"], needle
        assert body["total_count"] == 1, needle
        assert body["next_cursor"] is None, needle

    codes, totals = _walk(client, token, q="Shared Client")
    assert set(totals) == {3}
    assert len(codes) == 3


def test_total_excludes_other_tenants_restricted_and_walled_matters(
    client: TestClient,
) -> None:
    owner = _bootstrap(client, "nov24-acl", "owner")
    owner_token = str(owner["access_token"])
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug="nov24-acl",
        email="member@nov24-acl.in",
    )
    other = _bootstrap(client, "nov24-other", "owner")
    _seed(client, str(other["access_token"]), 4, "ACLX")

    _seed(client, owner_token, 4, "ACL")
    restricted = _create_matter(
        client, owner_token, "ACL-RESTRICTED", title="Portfolio matter restricted",
        status="intake",
    )
    walled = _create_matter(
        client, owner_token, "ACL-WALLED", title="Portfolio matter walled",
        status="intake",
    )
    response = client.post(
        f"/api/matters/{restricted['id']}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/api/matters/{walled['id']}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert response.status_code == 200, response.text

    owner_codes, owner_totals = _walk(client, owner_token, q="Portfolio matter")
    assert set(owner_totals) == {6}
    assert sorted(owner_codes) == sorted(
        ["ACL-00", "ACL-01", "ACL-02", "ACL-03", "ACL-RESTRICTED", "ACL-WALLED"]
    )

    member_codes, member_totals = _walk(client, member_token, q="Portfolio matter")
    assert set(member_totals) == {4}
    assert sorted(member_codes) == ["ACL-00", "ACL-01", "ACL-02", "ACL-03"]
    assert not any(code.startswith("ACLX") for code in owner_codes + member_codes)
