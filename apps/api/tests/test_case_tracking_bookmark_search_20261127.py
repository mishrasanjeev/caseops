"""Case Tracking Bookmarks search (Nov 27 workbook, Aishwarya row 6).

Users had to scroll every bookmark to find one Matter Code such as
MTR-2026-200. Search must run on the server over every active bookmark, so a
match on a page the browser never opened is found, and paging must keep a
server total. Fixtures hold more bookmarks than two pages with the target
sorted last.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from caseops_api.db.models import EthicalWall, Matter, TrackedCase, TrackedCaseBookmark
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_today_view_matter_access import _invite_member

BOOKMARKS = "/api/case-tracking/bookmarks"
TARGET_CODE = "MTR-2026-200"
TARGET_CNR = "DLHC010099992026"


def _create_matter(client: TestClient, token: str, code: str, title: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": title,
            "matter_code": code,
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "Fixture Client",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _seed_bookmarks(
    *,
    company_id: str,
    membership_id: str,
    count: int,
    target_matter_id: str | None,
    decoy_matter_id: str | None = None,
    prefix: str = "Routine",
    target_name: str = "Arbitration enforcement",
) -> dict[str, str]:
    """`count` active bookmarks; the target is the oldest, so it sorts last."""

    base = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    ids: dict[str, str] = {}
    with get_session_factory()() as session:
        for index in range(count):
            is_target = index == 0
            tracked = TrackedCase(
                company_id=company_id,
                provider="ecourtsindia",
                identity_key=f"{prefix.lower()}-identity-{index:04d}",
                cnr_number=TARGET_CNR if is_target else f"DLHC01{index:06d}2025",
                normalized_cnr_number=TARGET_CNR if is_target else f"DLHC01{index:06d}2025",
                case_number="CS(COMM) 731/2026" if is_target else f"WP(C) {index}/2025",
                normalized_case_number=(
                    "CS(COMM) 731/2026" if is_target else f"WP(C) {index}/2025"
                ),
                court_name="Delhi High Court",
                case_title=(
                    "Saraswati Exports v Union of India"
                    if is_target
                    else f"{prefix} Petitioner {index} v State"
                ),
                party_names_json=(
                    ["Saraswati Exports", "Union of India", "Ganga Traders"]
                    if is_target
                    else [f"{prefix} Petitioner {index}", "State"]
                ),
            )
            session.add(tracked)
            session.flush()
            matter_id = None
            if is_target:
                matter_id = target_matter_id
            elif index == 1:
                matter_id = decoy_matter_id
            moment = base + timedelta(minutes=index)
            bookmark = TrackedCaseBookmark(
                company_id=company_id,
                tracked_case_id=tracked.id,
                created_by_membership_id=membership_id,
                matter_id=matter_id,
                scope_key=matter_id or "company",
                active_scope_key=matter_id or "company",
                name=target_name if is_target else None,
                created_at=moment,
                updated_at=moment,
            )
            session.add(bookmark)
            session.flush()
            if is_target:
                ids["target"] = bookmark.id
            if index == 1:
                ids["decoy"] = bookmark.id
        session.commit()
    return ids


def _page_through(client: TestClient, token: str, *, q: str | None, limit: int) -> list[dict]:
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"limit": limit, "include_total": cursor is None}
        if q is not None:
            params["q"] = q
        if cursor:
            params["cursor"] = cursor
        response = client.get(BOOKMARKS, headers=auth_headers(token), params=params)
        assert response.status_code == 200, response.text
        pages.append(response.json())
        cursor = response.json()["next_cursor"]
        if not cursor:
            return pages


def _owner(client: TestClient) -> tuple[str, str, str]:
    boot = bootstrap_company(client)
    return (
        str(boot["access_token"]),
        str(boot["company"]["id"]),
        str(boot["membership"]["id"]),
    )


def test_matter_code_search_finds_a_bookmark_beyond_two_page_boundaries(
    client: TestClient,
) -> None:
    token, company_id, membership_id = _owner(client)
    target_matter = _create_matter(client, token, TARGET_CODE, "Saraswati Exports enforcement")
    decoy_matter = _create_matter(client, token, "MTR-2026-201", "Unrelated recovery suit")
    ids = _seed_bookmarks(
        company_id=company_id,
        membership_id=membership_id,
        count=120,
        target_matter_id=target_matter,
        decoy_matter_id=decoy_matter,
    )

    # The unsearched list pages to the end with a server total; the target is
    # only on the third page, which a one-page reader never sees.
    pages = _page_through(client, token, q=None, limit=50)
    assert [len(page["bookmarks"]) for page in pages] == [50, 50, 20]
    assert pages[0]["total_count"] == 120
    seen = [row["id"] for page in pages for row in page["bookmarks"]]
    assert len(seen) == len(set(seen)) == 120
    assert ids["target"] not in {row["id"] for row in pages[0]["bookmarks"]}
    assert pages[-1]["bookmarks"][-1]["id"] == ids["target"]

    for query in (TARGET_CODE, TARGET_CODE.lower(), f"  {TARGET_CODE}  "):
        found = client.get(
            BOOKMARKS,
            headers=auth_headers(token),
            params={"q": query, "limit": 50, "include_total": True},
        )
        assert found.status_code == 200, found.text
        body = found.json()
        assert [row["id"] for row in body["bookmarks"]] == [ids["target"]], query
        assert body["total_count"] == 1
        assert body["next_cursor"] is None
        assert body["bookmarks"][0]["matter_code"] == TARGET_CODE

    # A prefix lists both codes that start with it, newest first.
    prefix = client.get(
        BOOKMARKS,
        headers=auth_headers(token),
        params={"q": "MTR-2026-20", "limit": 50, "include_total": True},
    ).json()
    assert [row["id"] for row in prefix["bookmarks"]] == [ids["decoy"], ids["target"]]
    assert [row["matter_code"] for row in prefix["bookmarks"]] == ["MTR-2026-201", TARGET_CODE]


def test_bookmark_search_covers_case_identity_title_party_and_name(client: TestClient) -> None:
    token, company_id, membership_id = _owner(client)
    ids = _seed_bookmarks(
        company_id=company_id,
        membership_id=membership_id,
        count=60,
        target_matter_id=None,
    )
    for query in (
        TARGET_CNR,
        "DLHC01-009999-2026",  # CNR typed with separators
        "dlhc0100999",
        "CS(COMM) 731",
        "saraswati exports",
        "Ganga Traders",  # party only, not in the title
        "arbitration enforcement",  # bookmark name
    ):
        response = client.get(
            BOOKMARKS,
            headers=auth_headers(token),
            params={"q": query, "limit": 25, "include_total": True},
        )
        assert response.status_code == 200, response.text
        assert [row["id"] for row in response.json()["bookmarks"]] == [ids["target"]], query
        assert response.json()["total_count"] == 1, query

    # LIKE wildcards are literal text, not "match everything".
    for wildcard in ("%", "_", "\\", '","', "[", "]"):
        response = client.get(
            BOOKMARKS,
            headers=auth_headers(token),
            params={"q": wildcard, "limit": 25, "include_total": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total_count"] == 0, wildcard

    missing = client.get(
        BOOKMARKS,
        headers=auth_headers(token),
        params={"q": "MTR-2099-999", "limit": 25, "include_total": True},
    ).json()
    assert missing == {"bookmarks": [], "next_cursor": None, "total_count": 0}


def test_unpaged_bookmark_list_stays_complete_for_existing_clients(client: TestClient) -> None:
    token, company_id, membership_id = _owner(client)
    _seed_bookmarks(
        company_id=company_id, membership_id=membership_id, count=120, target_matter_id=None
    )
    legacy = client.get(BOOKMARKS, headers=auth_headers(token))
    assert legacy.status_code == 200, legacy.text
    assert len(legacy.json()["bookmarks"]) == 120
    assert legacy.json()["next_cursor"] is None
    searched = client.get(BOOKMARKS, headers=auth_headers(token), params={"q": "Petitioner 11"})
    assert {row["tracked_case"]["case_title"] for row in searched.json()["bookmarks"]} == {
        "Routine Petitioner 11 v State",
        *{f"Routine Petitioner {n} v State" for n in range(110, 120)},
    }


def test_bookmark_list_rejects_invalid_paging_and_search_input(client: TestClient) -> None:
    token, _, _ = _owner(client)
    for params in (
        {"limit": 0},
        {"limit": 101},
        {"q": "x" * 121},
        {"limit": 10, "cursor": "not-a-cursor"},
    ):
        response = client.get(BOOKMARKS, headers=auth_headers(token), params=params)
        assert response.status_code == 422, (params, response.text)


def test_walled_matter_code_is_neither_shown_nor_searchable(client: TestClient) -> None:
    token, company_id, _ = _owner(client)
    walled = _create_matter(client, token, TARGET_CODE, "Walled enforcement")
    member_id, member_token = _invite_member(client, token, "bookmark-member@example.com")
    # Auto-linked bookmarks are named after the Matter code (matter_create_auto_link).
    ids = _seed_bookmarks(
        company_id=company_id,
        membership_id=member_id,
        count=3,
        target_matter_id=walled,
        target_name=TARGET_CODE,
    )
    with get_session_factory()() as session:
        matter = session.get(Matter, walled)
        assert matter is not None
        session.add(
            EthicalWall(
                company_id=company_id,
                matter_id=walled,
                excluded_membership_id=member_id,
                reason="Conflict fixture",
            )
        )
        session.commit()

    listed = client.get(BOOKMARKS, headers=auth_headers(member_token)).json()["bookmarks"]
    target = next(row for row in listed if row["id"] == ids["target"])
    assert target["matter_code"] is None
    assert target["name"] is None
    by_code = client.get(
        BOOKMARKS,
        headers=auth_headers(member_token),
        params={"q": TARGET_CODE, "limit": 10, "include_total": True},
    ).json()
    assert by_code["total_count"] == 0 and by_code["bookmarks"] == []
    # The member's own case identity remains searchable.
    by_cnr = client.get(
        BOOKMARKS,
        headers=auth_headers(member_token),
        params={"q": TARGET_CNR, "limit": 10},
    ).json()
    assert [row["id"] for row in by_cnr["bookmarks"]] == [ids["target"]]


def test_bookmark_search_never_crosses_member_or_tenant_scope(client: TestClient) -> None:
    token, company_id, membership_id = _owner(client)
    matter = _create_matter(client, token, TARGET_CODE, "Owner enforcement")
    owner_ids = _seed_bookmarks(
        company_id=company_id, membership_id=membership_id, count=2, target_matter_id=matter
    )
    member_id, member_token = _invite_member(client, token, "colleague-search@example.com")
    _seed_bookmarks(
        company_id=company_id,
        membership_id=member_id,
        count=2,
        target_matter_id=matter,
        prefix="Colleague",
    )
    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Bookmark Firm LLP",
            "company_slug": "other-bookmark-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-bookmark-firm.example",
            "owner_password": "OtherBookmarkFirm!234",
        },
    )
    assert other.status_code == 200, other.text
    other_token = str(other.json()["access_token"])
    other_matter = _create_matter(client, other_token, TARGET_CODE, "Other tenant matter")
    other_ids = _seed_bookmarks(
        company_id=str(other.json()["company"]["id"]),
        membership_id=str(other.json()["membership"]["id"]),
        count=2,
        target_matter_id=other_matter,
        prefix="Foreign",
    )

    owner_hits = client.get(
        BOOKMARKS,
        headers=auth_headers(token),
        params={"q": TARGET_CODE, "limit": 10, "include_total": True},
    ).json()
    assert [row["id"] for row in owner_hits["bookmarks"]] == [owner_ids["target"]]
    assert owner_hits["total_count"] == 1
    other_hits = client.get(
        BOOKMARKS,
        headers=auth_headers(other_token),
        params={"q": TARGET_CODE, "limit": 10, "include_total": True},
    ).json()
    assert [row["id"] for row in other_hits["bookmarks"]] == [other_ids["target"]]
    member_hits = client.get(
        BOOKMARKS,
        headers=auth_headers(member_token),
        params={"q": "Saraswati", "include_total": True, "limit": 10},
    ).json()
    assert owner_ids["target"] not in {row["id"] for row in member_hits["bookmarks"]}
    assert member_hits["total_count"] == 1


def test_bookmark_created_through_the_api_is_searchable_by_its_case_identity(
    client: TestClient,
) -> None:
    token, company_id, membership_id = _owner(client)
    _seed_bookmarks(
        company_id=company_id, membership_id=membership_id, count=55, target_matter_id=None
    )
    created = client.post(
        BOOKMARKS,
        headers=auth_headers(token),
        json={
            "provider": "ecourtsindia",
            "cnr_number": "MHHC01-004321-2026",
            "case_number": "COMAP 88/2026",
            "case_title": "Kaveri Mills v Narmada Textiles",
            "party_names": ["Kaveri Mills", "Narmada Textiles"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["matter_code"] is None
    for query in ("MHHC01-004321-2026", "Narmada", "COMAP 88"):
        response = client.get(
            BOOKMARKS,
            headers=auth_headers(token),
            params={"q": query, "limit": 50, "include_total": True},
        ).json()
        assert [row["id"] for row in response["bookmarks"]] == [created.json()["id"]], query
