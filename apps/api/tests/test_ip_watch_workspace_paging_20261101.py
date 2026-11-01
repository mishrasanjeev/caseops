"""GET /api/ip/watch states every list's total and pages to the end (B4-ADJ-05).

The workspace returned at most `limit` profiles, hits and journal entries with
no total, and read hits only for the profiles on that page, so a hit on an
older profile never appeared at all. Each fixture here spans three pages with
the row that matters sorted last.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.db.models import MembershipRole
from tests.test_auth_company import auth_headers
from tests.test_ip_journal_watch import (
    _application,
    _asset,
    _colleague,
    _fixture,
    _ingest,
    _publication,
    _word_profile,
)
from tests.test_ip_record_workflow import _particulars

PAGE = 5
OTHER_PROFILES = 11  # plus the oldest ALPHA profile: 12 profiles, three pages of 5
ALPHA_ENTRIES = 12


def _page(client: TestClient, headers: dict[str, str], offset: int, **params: str) -> dict:
    response = client.get(
        "/api/ip/watch",
        headers=headers,
        params={"limit": str(PAGE), "offset": str(offset), **params},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _every_page(client: TestClient, headers: dict[str, str], **params: str) -> list[dict]:
    pages = [_page(client, headers, 0, **params)]
    total = max(pages[0]["profile_total"], pages[0]["hit_total"], pages[0]["publication_total"])
    while len(pages) * PAGE < total:
        pages.append(_page(client, headers, len(pages) * PAGE, **params))
    return pages


def _alpha_entry(application_id: str, index: int) -> dict:
    entry = _publication(
        application_id=application_id,
        application_number=f"TM-77{index:05d}",
        journal_number=f"TMJ-{3000 + index}",
        # The first capture has the oldest journal date, so its hit sorts last.
        journal_date=f"2026-07-{index + 1:02d}",
    )
    entry["mark_text"] = "ALPHA"
    entry["device_reference"] = None
    entry["raw_evidence"] = {"journal_heading": f"Trade Marks Journal No. {3000 + index}"}
    return entry


def _setup(client: TestClient) -> dict:
    bootstrap, headers, docket, application = _fixture(client, "PAGEWATCH")
    owner = bootstrap["membership"]["id"]
    alpha = _word_profile(client, headers, docket_id=docket["id"], word="ALPHA", recipient=owner)
    for index in range(ALPHA_ENTRIES):
        _ingest(
            client,
            headers=headers,
            key=f"watch-paging-{index:04d}",
            publication=_alpha_entry(application["id"], index),
            cost_minor=0,
        )
    # Profiles changed after the captures, so ALPHA is the oldest change: the
    # last profile on the last page, while its hits lead the hit list.
    for index in range(OTHER_PROFILES):
        _word_profile(
            client, headers, docket_id=docket["id"], word=f"QZX{index:02d}KW", recipient=owner
        )
    return {"bootstrap": bootstrap, "headers": headers, "docket": docket, "alpha": alpha}


def test_watch_workspace_pages_every_list_to_its_total(client: TestClient) -> None:
    fixture = _setup(client)
    headers, alpha = fixture["headers"], fixture["alpha"]
    pages = _every_page(client, headers)
    assert len(pages) == 3
    first = pages[0]
    assert (first["limit"], first["offset"]) == (PAGE, 0)
    assert first["profile_total"] == OTHER_PROFILES + 1
    assert first["hit_total"] == ALPHA_ENTRIES
    assert first["publication_total"] == ALPHA_ENTRIES
    assert first["paused_profile_total"] == 0
    assert first["ingestion_run_total"] == ALPHA_ENTRIES
    assert first["ingestion_run_limit"] == 20

    profiles = [row["id"] for page in pages for row in page["profiles"]]
    hits = [row for page in pages for row in page["hits"]]
    entries = {row["id"] for page in pages for row in page["publications"]}
    assert len(profiles) == len(set(profiles)) == OTHER_PROFILES + 1
    assert profiles[-1] == alpha["id"]  # the oldest profile is reached on the last page
    assert len(hits) == len({row["id"] for row in hits}) == ALPHA_ENTRIES
    assert len(entries) == ALPHA_ENTRIES

    # Every hit is on the ALPHA profile, which is not on the first profile
    # page: the hits are still listed, with the profile they were compared to.
    assert alpha["id"] not in {row["id"] for row in first["profiles"]}
    assert {row["profile_id"] for row in hits} == {alpha["id"]}
    assert [row["id"] for row in first["hit_profiles"]] == [alpha["id"]]
    # Newest hit first; the oldest capture is the last hit of the last page.
    dates = [row["hit_date"] for row in hits]
    assert dates == sorted(dates, reverse=True)
    assert pages[-1]["hits"][-1]["hit_date"] == min(dates)

    # Scoped to the docket, the same totals; past the end, empty pages.
    scoped = _page(client, headers, 0, docket_id=fixture["docket"]["id"])
    assert (scoped["profile_total"], scoped["hit_total"]) == (OTHER_PROFILES + 1, ALPHA_ENTRIES)
    beyond = _page(client, headers, 100)
    assert beyond["profiles"] == beyond["hits"] == beyond["publications"] == []
    assert beyond["hit_total"] == ALPHA_ENTRIES


def test_watch_workspace_totals_follow_tenant_wall_and_auth(client: TestClient) -> None:
    fixture = _setup(client)
    headers = fixture["headers"]
    owner = fixture["bootstrap"]["membership"]["id"]
    restricted = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": "WALLPAGE", "restricted": True, "particulars": _particulars("WALLPAGE")},
    )
    assert restricted.status_code == 201, restricted.text
    walled = restricted.json()["id"]
    walled_application = _application(
        client, headers, walled, _asset(client, headers, walled, "WALLPAGE")["id"]
    )
    walled_profile = _word_profile(
        client, headers, docket_id=walled, word="WALLPAGE", recipient=owner
    )
    entry = _alpha_entry(walled_application["id"], 20)
    entry["mark_text"] = "WALLPAGE"
    captured = _ingest(
        client, headers=headers, key="watch-paging-walled", publication=entry, cost_minor=0
    )
    walled_hits = [hit for hit in captured["hits"] if hit["profile_id"] == walled_profile["id"]]
    open_hits = len(captured["hits"]) - len(walled_hits)
    assert len(walled_hits) == 1

    owner_view = _page(client, headers, 0)
    assert owner_view["profile_total"] == OTHER_PROFILES + 2
    assert owner_view["hit_total"] == ALPHA_ENTRIES + len(captured["hits"])

    member = _colleague(client, headers, email="pager@aster.example", role=MembershipRole.MEMBER)
    member_pages = _every_page(client, member)
    member_view = member_pages[0]
    assert member_view["profile_total"] == OTHER_PROFILES + 1
    assert member_view["hit_total"] == ALPHA_ENTRIES + open_hits
    listed_profiles = {row["id"] for page in member_pages for row in page["profiles"]}
    listed_hits = {row["id"] for page in member_pages for row in page["hits"]}
    assert walled_profile["id"] not in listed_profiles
    assert walled_hits[0]["id"] not in listed_hits
    assert len(listed_hits) == member_view["hit_total"]
    walled_scope = client.get(
        "/api/ip/watch", headers=member, params={"docket_id": walled, "limit": str(PAGE)}
    )
    assert walled_scope.status_code == 404

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Pager Other LLP",
            "company_slug": "pager-other",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@pager-other.example",
            "owner_password": "PagerOther123!",
        },
    )
    assert other.status_code == 200, other.text
    foreign = _page(client, auth_headers(other.json()["access_token"]), 0)
    totals = ("profile_total", "hit_total", "publication_total", "ingestion_run_total")
    assert [foreign[key] for key in totals] == [0, 0, 0, 0]

    bad = client.get("/api/ip/watch", headers=headers, params={"offset": "-1"})
    assert bad.status_code == 422
    # The test client keeps the last sign-in cookie; an anonymous reader has none.
    client.cookies.clear()
    assert client.get("/api/ip/watch").status_code == 401
