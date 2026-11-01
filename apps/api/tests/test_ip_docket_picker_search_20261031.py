"""GET /api/ip/dockets search and keyset paging for the shared docket picker.

Ram 2026-10-30 (BUG-012 adjacent): six IP pages fed their docket pickers from
an unparameterised GET /api/ip/dockets, so only the 100 most recently updated
dockets could ever be chosen. The picker now searches on the server and pages
by cursor; these tests pin that a docket beyond the first hundred is reachable,
that pages are complete and disjoint, and that search never widens visibility.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from caseops_api.db.models import IpDocketRecord
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_authorities import _bootstrap_second_company
from tests.test_ip_record_access_foundation import _invite_member, _particulars


def _create_docket(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str,
    identifier: str | None = None,
    restricted: bool = False,
) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "primary_identifier": identifier,
            "restricted": restricted,
            "particulars": _particulars(title.upper()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _list(client: TestClient, headers: dict[str, str], **params: object) -> dict:
    response = client.get("/api/ip/dockets", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _walk(client: TestClient, headers: dict[str, str], **params: object) -> list[dict]:
    rows: list[dict] = []
    cursor: str | None = None
    totals: set[int] = set()
    for _ in range(100):
        page = _list(client, headers, **params, **({"cursor": cursor} if cursor else {}))
        rows.extend(page["dockets"])
        totals.add(page["total_count"])
        assert page["count"] == len(page["dockets"])
        cursor = page["next_cursor"]
        assert page["has_more"] is (cursor is not None)
        if cursor is None:
            break
    else:  # pragma: no cover - a cursor that never ends is the defect
        raise AssertionError("docket cursor did not terminate")
    # Every page reports the same population size, and it is the true one.
    assert totals == {len(rows)}
    return rows


def test_search_and_cursor_reach_every_docket_beyond_the_first_hundred(
    client: TestClient,
) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    # Created first, so it is the least recently updated: docket #102.
    needle = _create_docket(
        client, headers, title="Zeta Biscuits Device", identifier="TM-NEEDLE-4009154"
    )
    for index in range(101):
        _create_docket(
            client, headers, title=f"Picker docket {index:03d}", identifier=f"TM-PICK-{index:03d}"
        )
    # Several dockets share one timestamp, as a bulk import commit does; the
    # id tie-break must keep them in order without skipping or repeating. The
    # tie sits mid-list so the needle stays the least recently updated.
    with get_session_factory()() as session:
        tied_at = session.scalar(
            select(IpDocketRecord.updated_at).where(IpDocketRecord.title == "Picker docket 070")
        )
        assert tied_at is not None
        tied = session.scalars(
            select(IpDocketRecord.id).where(IpDocketRecord.title.like("Picker docket 04%"))
        ).all()
        assert len(tied) == 10
        session.execute(
            update(IpDocketRecord).where(IpDocketRecord.id.in_(tied)).values(updated_at=tied_at)
        )
        session.commit()

    first = _list(client, headers)
    assert first["count"] == 100
    assert first["has_more"] is True
    assert first["total_count"] == 102
    assert first["next_cursor"]
    assert needle["id"] not in {row["id"] for row in first["dockets"]}

    # Search by mark title (any case), by part of the displayed identifier,
    # and by the identifier exactly as it is displayed.
    for query in ("zeta biscuits", "ZETA", "4009154", "tm-needle-4009154"):
        found = _list(client, headers, query=query)
        assert [row["id"] for row in found["dockets"]] == [needle["id"]], query
        assert found["total_count"] == 1
        assert found["has_more"] is False
        assert found["next_cursor"] is None

    nothing = _list(client, headers, query="no such mark anywhere")
    assert nothing == {
        "dockets": [],
        "count": 0,
        "has_more": False,
        "next_cursor": None,
        "total_count": 0,
    }

    walked = _walk(client, headers, limit=9)
    walked_ids = [row["id"] for row in walked]
    assert len(walked_ids) == len(set(walked_ids)) == 102
    assert needle["id"] in walked_ids
    complete = _list(client, headers, limit=200)
    assert complete["has_more"] is False
    assert walked_ids == [row["id"] for row in complete["dockets"]]
    ordering = [(row["updated_at"], row["id"]) for row in walked]
    assert ordering == sorted(ordering, reverse=True)

    # A searched population pages the same way.
    searched = _walk(client, headers, query="picker docket 0", limit=4)
    assert {row["title"] for row in searched} == {
        f"Picker docket {index:03d}" for index in range(100)
    }


def test_search_and_pages_never_show_a_restricted_docket_to_a_non_member(
    client: TestClient,
) -> None:
    owner_token = str(bootstrap_company(client)["access_token"])
    owner_headers = auth_headers(owner_token)
    walled = _create_docket(
        client, owner_headers, title="Walled Needle", identifier="TM-WALL-1", restricted=True
    )
    open_docket = _create_docket(
        client, owner_headers, title="Open Needle", identifier="TM-OPEN-1"
    )
    _, member_headers = _invite_member(client, owner_token)

    owner_view = _list(client, owner_headers, query="needle")
    assert {row["id"] for row in owner_view["dockets"]} == {walled["id"], open_docket["id"]}

    for query in ("needle", "walled", "TM-WALL-1"):
        member_view = _list(client, member_headers, query=query)
        assert walled["id"] not in {row["id"] for row in member_view["dockets"]}, query
    member_view = _list(client, member_headers, query="needle")
    assert [row["id"] for row in member_view["dockets"]] == [open_docket["id"]]
    # The total does not reveal that a hidden docket matched.
    assert member_view["total_count"] == 1
    paged = _walk(client, member_headers, limit=1)
    assert [row["id"] for row in paged] == [open_docket["id"]]

    # A deep link to the restricted docket stays closed to the non-member and
    # open to the creator.
    assert client.get(f"/api/ip/dockets/{walled['id']}", headers=member_headers).status_code == 404
    deep_link = client.get(f"/api/ip/dockets/{walled['id']}", headers=owner_headers)
    assert deep_link.status_code == 200, deep_link.text
    assert deep_link.json()["id"] == walled["id"]


def test_docket_search_and_cursor_stay_inside_the_caller_tenant(client: TestClient) -> None:
    first_headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    second_headers = auth_headers(str(_bootstrap_second_company(client)["access_token"]))
    ours = _create_docket(client, first_headers, title="Shared Needle Mark", identifier="TM-A-1")
    theirs = _create_docket(
        client, second_headers, title="Shared Needle Mark", identifier="TM-B-1"
    )
    for _ in range(2):
        _create_docket(client, second_headers, title="Other tenant filler")

    first_view = _list(client, first_headers, query="shared needle")
    assert [row["id"] for row in first_view["dockets"]] == [ours["id"]]
    assert first_view["total_count"] == 1
    assert _list(client, first_headers, query="TM-B-1")["dockets"] == []

    # A cursor minted by the other tenant only positions the caller's own
    # keyset; it never yields the other tenant's rows.
    foreign_cursor = _list(client, second_headers, limit=1)["next_cursor"]
    assert foreign_cursor
    replayed = _list(client, first_headers, cursor=foreign_cursor)
    assert theirs["id"] not in {row["id"] for row in replayed["dockets"]}
    assert all(row["company_id"] == ours["company_id"] for row in replayed["dockets"])
    assert client.get(f"/api/ip/dockets/{theirs['id']}", headers=first_headers).status_code == 404


def test_docket_listing_rejects_invalid_cursors_and_anonymous_callers(
    client: TestClient,
) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    _create_docket(client, headers, title="Cursor Fixture")

    def encoded(raw: str) -> str:
        return urlsafe_b64encode(raw.encode()).decode()

    for cursor in (
        "not base64 !!",
        encoded("no separator"),
        encoded("not-a-date|abc"),
        encoded("2026-10-30T11:05:00+00:00|"),
        encoded(f"2026-10-30T11:05:00+00:00|{'x' * 37}"),
        "A" * 513,
    ):
        response = client.get("/api/ip/dockets", headers=headers, params={"cursor": cursor})
        assert response.status_code == 422, (cursor, response.text)
        assert response.headers["content-type"].startswith("application/problem+json")
        assert "cursor" in response.json()["detail"].lower()

    too_long = client.get("/api/ip/dockets", headers=headers, params={"query": "q" * 201})
    assert too_long.status_code == 422
    assert too_long.json()["detail"].startswith("Query: ")
    # Bootstrap left a session cookie on the test client; drop it to be anonymous.
    client.cookies.clear()
    assert client.get("/api/ip/dockets", params={"query": "cursor"}).status_code == 401
