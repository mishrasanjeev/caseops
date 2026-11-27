"""Nov 27 workbook row 5: the court badge opens the court's official website.

The website lives once, on the shared forum catalogue row, and every read
path that renders the court badge (matter list, matter detail and workspace,
client and counsel portal matter detail) resolves it from the matter's
canonical identity (catalogue entry, master Court row, or the write path's own
name/reviewed-alias predicate) in one batched lookup. Mutation responses and
dashboards do not render the badge and return ``None`` without a catalogue
query; the web refetches the workspace after every matter edit. Unmapped
courts come back as ``None`` so the page renders plain text.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from caseops_api.db.models import ForumCatalogAlias, ForumCatalogEntry, Matter
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.forum_catalog import (
    matter_court_website_url,
    official_website_or_none,
)
from tests.test_auth_company import auth_headers, bootstrap_company

DELHI_HC = "https://delhihighcourt.nic.in/"
_CATALOGUE_TABLE = re.compile(r"\b(?:from|join) forum_catalog_(?:entries|aliases)\b")


def _create(client: TestClient, token: str, code: str, **forum: object) -> dict:
    payload: dict[str, object] = {
        "title": f"Court website {code}",
        "matter_code": code,
        "client_name": "Acme Industries",
        "status": "intake",
        "practice_area": "Commercial Litigation",
        "forum_level": "high_court",
        **forum,
    }
    response = client.post("/api/matters/", headers=auth_headers(token), json=payload)
    assert response.status_code == 200, response.text
    # A create response renders no badge, so it never pays for the lookup.
    assert response.json()["court_website_url"] is None
    detail = client.get(f"/api/matters/{response.json()['id']}", headers=auth_headers(token))
    assert detail.status_code == 200, detail.text
    return detail.json()


@contextmanager
def _catalogue_selects() -> Iterator[list[str]]:
    engine = get_engine()
    selects: list[str] = []

    def capture(_conn, _cursor, statement, _params, _context, _many) -> None:
        normalized = " ".join(statement.casefold().split())
        # Statements that read the catalogue tables, not matters' identity column.
        if normalized.startswith("select") and _CATALOGUE_TABLE.search(normalized):
            selects.append(normalized)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield selects
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def _seed_legacy(company_id: str, code: str, *, court_name: str, forum_level: str) -> str:
    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            title=f"Legacy {code}",
            matter_code=code,
            client_name="Legacy Client",
            status="active",
            practice_area="commercial",
            forum_level=forum_level,
            court_name=court_name,
        )
        session.add(matter)
        session.commit()
        return matter.id


def test_every_read_path_returns_the_catalogue_website_for_the_selected_court(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    matter = _create(client, token, "CW-DHC", forum_catalog_entry_id="hc:delhi")
    assert matter["court_name"] == "Delhi High Court"
    assert matter["court_website_url"] == DELHI_HC

    headers = auth_headers(token)
    detail = client.get(f"/api/matters/{matter['id']}", headers=headers)
    assert detail.json()["court_website_url"] == DELHI_HC
    workspace = client.get(f"/api/matters/{matter['id']}/workspace", headers=headers)
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["matter"]["court_website_url"] == DELHI_HC
    listing = client.get("/api/matters/", headers=headers)
    row = next(item for item in listing.json()["matters"] if item["id"] == matter["id"])
    assert row["court_website_url"] == DELHI_HC

    # Update path: moving the matter to another catalogued court moves the link.
    updated = client.patch(
        f"/api/matters/{matter['id']}",
        headers=headers,
        json={
            "forum_catalog_entry_id": "hc:bombay",
            "court_id": "bombay-hc",
            "court_name": "Bombay High Court",
            "forum_state": "Maharashtra",
            "forum_city": "Mumbai",
            "expected_updated_at": detail.json()["updated_at"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["court_name"] == "Bombay High Court"
    # The update response carries no website; the next badge read does.
    assert updated.json()["court_website_url"] is None
    reread = client.get(f"/api/matters/{matter['id']}/workspace", headers=headers)
    assert reread.json()["matter"]["court_website_url"] == "https://bombayhighcourt.gov.in/"
    listing = client.get("/api/matters/", headers=headers)
    row = next(item for item in listing.json()["matters"] if item["id"] == matter["id"])
    assert row["court_website_url"] == "https://bombayhighcourt.gov.in/"


def test_master_court_and_supreme_court_and_tribunal_identities_resolve(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    by_court = _create(client, token, "CW-COURT", court_id="delhi-hc")
    assert by_court["forum_catalog_entry_id"] is None
    assert by_court["court_website_url"] == DELHI_HC

    supreme = _create(
        client,
        token,
        "CW-SC",
        forum_level="supreme_court",
        forum_catalog_entry_id="sc:india",
    )
    assert supreme["court_website_url"] == "https://www.sci.gov.in/"

    nclt = _create(
        client, token, "CW-NCLT", forum_level="tribunal", forum_catalog_entry_id="company-law:nclt"
    )
    assert nclt["court_website_url"] == "https://nclt.gov.in/"

    district = _create(
        client,
        token,
        "CW-DIST",
        forum_level="lower_court",
        forum_catalog_entry_id="district:india-gov:delhi:southwestdelhi",
    )
    host = urlsplit(district["court_website_url"]).hostname or ""
    assert host.endswith(".dcourts.gov.in")


def test_unmapped_courts_have_no_link(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    # Official site is not on a government domain, so it stays plain text.
    allahabad = _create(client, token, "CW-ALD", forum_catalog_entry_id="hc:allahabad")
    assert allahabad["court_website_url"] is None
    free_text = _create(
        client,
        token,
        "CW-FREE",
        forum_level="lower_court",
        court_name="Kamrup Metro District Court",
        forum_state="Assam",
        forum_district="Kamrup Metro",
    )
    assert free_text["court_website_url"] is None
    state_commission = _create(
        client,
        token,
        "CW-SCDRC",
        forum_level="tribunal",
        forum_catalog_entry_id="consumer:scdrc:11070000",
    )
    assert state_commission["court_website_url"] is None


def test_legacy_free_text_court_resolves_through_canonical_name_and_reviewed_alias(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    with get_session_factory()() as session:
        session.add(
            ForumCatalogAlias(
                forum_catalog_entry_id="hc:delhi",
                alias="High Court of Delhi at New Delhi",
                normalized_alias="highcourtofdelhiatnewdelhi",
                source_name="Regression fixture",
                source_url="https://example.test/forum-alias",
                verification_status="verified",
                is_active=True,
            )
        )
        session.add(
            ForumCatalogAlias(
                forum_catalog_entry_id="hc:delhi",
                alias="Unreviewed Delhi Bench",
                normalized_alias="unrevieweddelhibench",
                source_name="Regression fixture",
                source_url="https://example.test/forum-alias",
                verification_status="pending",
                is_active=True,
            )
        )
        session.commit()
    canonical = _seed_legacy(
        company_id, "CW-L1", court_name="Delhi High Court", forum_level="high_court"
    )
    aliased = _seed_legacy(
        company_id, "CW-L2", court_name="High Court of Delhi at New Delhi", forum_level="high_court"
    )
    pending = _seed_legacy(
        company_id, "CW-L3", court_name="Unreviewed Delhi Bench", forum_level="high_court"
    )
    wrong_level = _seed_legacy(
        company_id, "CW-L4", court_name="Delhi High Court", forum_level="lower_court"
    )
    headers = auth_headers(token)
    urls = {
        matter_id: client.get(f"/api/matters/{matter_id}", headers=headers).json()[
            "court_website_url"
        ]
        for matter_id in (canonical, aliased, pending, wrong_level)
    }
    assert urls[canonical] == DELHI_HC
    assert urls[aliased] == DELHI_HC
    assert urls[pending] is None
    assert urls[wrong_level] is None


def test_a_selected_catalogue_row_without_a_website_never_falls_back(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            title="Identity wins",
            matter_code="CW-ID",
            status="active",
            practice_area="commercial",
            forum_level="high_court",
            # Display text names Delhi, identity is Allahabad (no website).
            court_name="Delhi High Court",
            forum_catalog_entry_id="hc:allahabad",
            next_hearing_on=date(2026, 12, 1),
        )
        session.add(matter)
        session.commit()
        assert matter_court_website_url(session, matter) is None


def test_catalogue_websites_are_government_https_and_cover_every_superior_court(
    client: TestClient,
) -> None:
    del client  # migrated database only
    with get_session_factory()() as session:
        rows = session.scalars(
            select(ForumCatalogEntry).where(ForumCatalogEntry.is_active.is_(True))
        ).all()
    linked = [row for row in rows if row.official_website_url]
    assert linked, "the migrated catalogue must carry official websites"
    for row in linked:
        assert official_website_or_none(row.official_website_url) == row.official_website_url, (
            row.id
        )
        assert row.official_website_source_url, f"{row.id} has no verification source"
        assert urlsplit(row.official_website_source_url).scheme == "https"
    superior = [row.id for row in rows if row.forum_level in {"supreme_court", "high_court"}]
    missing = sorted(
        row_id
        for row_id in superior
        if row_id != "hc:allahabad"
        and not next(r for r in rows if r.id == row_id).official_website_url
    )
    assert missing == [], f"superior courts without a verified website: {missing}"
    districts = [row for row in rows if row.id.startswith("district:india-gov:")]
    assert districts
    assert all(row.official_website_url == row.source_url for row in districts)


def test_only_government_https_addresses_are_ever_linked() -> None:
    assert official_website_or_none("https://delhihighcourt.nic.in/") == DELHI_HC
    assert official_website_or_none("https://www.sci.gov.in/") == "https://www.sci.gov.in/"
    for rejected in (
        "http://delhihighcourt.nic.in/",
        "https://allahabadhighcourt.in/",
        "https://evil.example/gov.in",
        "https://user:pass@delhihighcourt.nic.in/",
        "https://delhihighcourt.nic.in/?next=https://evil.example",
        "https://delhihighcourt.nic.in.evil.example/",
        "javascript:alert(1)",
        "",
        None,
    ):
        assert official_website_or_none(rejected) is None, rejected

# (forum identity, expected website) for the scale test; every rule appears.
_SCALE_KINDS: list[tuple[dict[str, object], str | None]] = [
    ({"forum_level": "high_court", "forum_catalog_entry_id": "hc:delhi"}, DELHI_HC),
    (
        {"forum_level": "high_court", "forum_catalog_entry_id": "hc:bombay"},
        "https://bombayhighcourt.gov.in/",
    ),
    (
        {"forum_level": "supreme_court", "forum_catalog_entry_id": "sc:india"},
        "https://www.sci.gov.in/",
    ),
    (
        {"forum_level": "tribunal", "forum_catalog_entry_id": "company-law:nclt"},
        "https://nclt.gov.in/",
    ),
    ({"forum_level": "high_court", "forum_catalog_entry_id": "hc:allahabad"}, None),
    ({"forum_level": "tribunal", "forum_catalog_entry_id": "consumer:scdrc:11070000"}, None),
    ({"forum_level": "high_court", "court_id": "delhi-hc"}, DELHI_HC),
    ({"forum_level": "high_court", "court_name": "Delhi High Court"}, DELHI_HC),
    ({"forum_level": "lower_court", "court_name": "Delhi High Court"}, None),
    ({"forum_level": "lower_court", "court_name": "Kamrup Metro District Court"}, None),
]


def test_matter_list_resolves_websites_in_a_bounded_batch_for_many_courts(
    client: TestClient,
) -> None:
    """Review finding on row 5: the website must not cost catalogue queries per
    matter. 30 matters across ten court identities, read in three pages and in
    one page, take at most two catalogue queries per response (catalogue rows
    and their aliases); mutation and dashboard responses take none."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    expected: dict[str, str | None] = {}
    with get_session_factory()() as session:
        for index in range(30):
            forum, url = _SCALE_KINDS[index % len(_SCALE_KINDS)]
            matter = Matter(
                company_id=company_id,
                title=f"Scale {index}",
                matter_code=f"CW-SCALE-{index:02d}",
                client_name="Scale Client",
                status="active",
                practice_area="commercial",
                **forum,
            )
            session.add(matter)
            session.flush()
            expected[matter.id] = url
        session.commit()
    headers = auth_headers(token)

    seen: dict[str, str | None] = {}
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, object] = {"limit": 10}
        if cursor:
            params["cursor"] = cursor
        with _catalogue_selects() as selects:
            page = client.get("/api/matters/", headers=headers, params=params)
        assert page.status_code == 200, page.text
        assert 1 <= len(selects) <= 2, selects
        pages += 1
        seen.update({row["id"]: row["court_website_url"] for row in page.json()["matters"]})
        cursor = page.json()["next_cursor"]
        if not cursor:
            break
    assert pages == 3
    assert seen == expected

    with _catalogue_selects() as selects:
        whole = client.get("/api/matters/", headers=headers, params={"limit": 200})
    assert 1 <= len(selects) <= 2, selects
    assert {row["id"]: row["court_website_url"] for row in whole.json()["matters"]} == expected

    with _catalogue_selects() as selects:
        dashboard = client.get("/api/matters/dashboard-summary", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert selects == []
    for key in ("upcoming_hearings", "recent_matters"):
        assert all(row["court_website_url"] is None for row in dashboard.json()[key])

    linked = next(matter_id for matter_id, url in expected.items() if url == DELHI_HC)
    before = client.get(f"/api/matters/{linked}", headers=headers).json()
    with _catalogue_selects() as selects:
        renamed = client.patch(
            f"/api/matters/{linked}",
            headers=headers,
            json={"title": "Scale renamed", "expected_updated_at": before["updated_at"]},
        )
    assert renamed.status_code == 200, renamed.text
    assert selects == []
    assert renamed.json()["court_website_url"] is None
    after = client.get(f"/api/matters/{linked}/workspace", headers=headers).json()
    assert after["matter"]["court_website_url"] == DELHI_HC



def test_portal_matter_detail_links_the_court_and_portal_lists_do_not_query(
    client: TestClient,
) -> None:
    """Both portal matter pages render the badge, so both detail routes resolve
    the website; the portal lists render no badge and take no catalogue query."""

    from tests.test_portal_matters import (
        _bootstrap,
        _invite_client_portal_user,
        _verify_and_session,
    )
    from tests.test_portal_outside_counsel import _invite_oc_portal_user

    boot = _bootstrap(client, slug="cw-portal", email="owner@cw-portal.example")
    token = str(boot["access_token"])
    with get_session_factory()() as session:
        matter = Matter(
            company_id=boot["company"]["id"],
            client_name="Portal Client",
            title="Portal court link",
            matter_code="CW-PORTAL",
            status="active",
            practice_area="commercial",
            forum_level="high_court",
            court_name="Delhi High Court",
            forum_catalog_entry_id="hc:delhi",
        )
        session.add(matter)
        session.commit()
        matter_id = matter.id

    _, client_link = _invite_client_portal_user(
        client, token, matter_id, email="client@cw-portal.example"
    )
    _, counsel_link = _invite_oc_portal_user(
        client, token, matter_id, email="oc@cw-portal.example"
    )
    for link, prefix in ((client_link, "/api/portal"), (counsel_link, "/api/portal/oc")):
        _verify_and_session(client, link)
        detail = client.get(f"{prefix}/matters/{matter_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["court_website_url"] == DELHI_HC
        with _catalogue_selects() as selects:
            listing = client.get(f"{prefix}/matters")
        assert listing.status_code == 200, listing.text
        assert selects == []
        assert [row["court_website_url"] for row in listing.json()["matters"]] == [None]


# The same journeys on PostgreSQL, where the CI query-graph contracts run.
@pytest.mark.postgres
def test_matter_list_website_batch_is_bounded_on_postgres(isolated_postgres_client) -> None:
    test_matter_list_resolves_websites_in_a_bounded_batch_for_many_courts(
        isolated_postgres_client
    )


@pytest.mark.postgres
def test_read_paths_resolve_on_postgres(isolated_postgres_client) -> None:
    test_every_read_path_returns_the_catalogue_website_for_the_selected_court(
        isolated_postgres_client
    )


@pytest.mark.postgres
def test_legacy_aliases_resolve_on_postgres(isolated_postgres_client) -> None:
    test_legacy_free_text_court_resolves_through_canonical_name_and_reviewed_alias(
        isolated_postgres_client
    )


@pytest.mark.postgres
def test_portal_routes_resolve_on_postgres(isolated_postgres_client) -> None:
    test_portal_matter_detail_links_the_court_and_portal_lists_do_not_query(
        isolated_postgres_client
    )
