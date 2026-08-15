"""IPLF-030A trademark portfolio listing (IP-PORT-02, IP-PORT-05, UJ-04-EXC-02).

Stable manifest test IDs:

* ``IPLF-REQ-IP-PORT-02``  server-owned filter scope
* ``IPLF-REQ-IP-PORT-05``  asset and application records stay distinct
* ``IPLF-UJ-04-EXC-02``    restricted records are omitted, not teased
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from caseops_api.db.models import Matter
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_record_workflow import _particulars


def _docket(
    client: TestClient,
    headers: dict[str, str],
    *,
    matter_id: str,
    title: str,
    restricted: bool = False,
) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": restricted,
            "particulars": _particulars(title.upper()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _asset(client: TestClient, headers: dict[str, str], *, docket_id: str, **kw) -> dict:
    payload = {
        "asset_kind": "trademark",
        "jurisdiction": "IN",
        "title": "Aster Mark",
    }
    payload.update(kw)
    response = client.post(
        f"/api/ip/dockets/{docket_id}/assets", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _application(
    client: TestClient, headers: dict[str, str], *, docket_id: str, asset_id: str, **kw
) -> dict:
    payload = {
        "asset_id": asset_id,
        "office": "IP India",
        "jurisdiction": "IN",
        "filing_phase": "draft",
    }
    payload.update(kw)
    response = client.post(
        f"/api/ip/dockets/{docket_id}/applications",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()["application"]


def _portfolio(client: TestClient, headers: dict[str, str], **params):
    return client.get("/api/ip/portfolio", headers=headers, params=params)


def test_ip_port_05_one_mark_yields_one_row_per_jurisdiction(
    client: TestClient,
) -> None:
    """IPLF-REQ-IP-PORT-05 — asset and application records stay distinct."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-PORT-030A")
    docket = _docket(client, headers, matter_id=matter["id"], title="Aster Portfolio Mark")

    asset = _asset(client, headers, docket_id=docket["id"])
    india = _application(client, headers, docket_id=docket["id"], asset_id=asset["id"])
    uk = _application(
        client,
        headers,
        docket_id=docket["id"],
        asset_id=asset["id"],
        office="UKIPO",
        jurisdiction="GB",
        filing_phase="pre_filing",
    )

    response = _portfolio(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()

    # One mark, two jurisdiction/application records: two rows, one asset id.
    assert body["counts"]["total"] == 2
    ids = {row["application_id"] for row in body["rows"]}
    assert ids == {india["id"], uk["id"]}
    assert {row["asset_id"] for row in body["rows"]} == {asset["id"]}
    assert {row["jurisdiction"] for row in body["rows"]} == {"IN", "GB"}
    assert all(row["asset_title"] == "Aster Mark" for row in body["rows"])
    # The mark is not collapsed into the application row identity.
    assert all(row["application_id"] != row["asset_id"] for row in body["rows"])
    # Registry synchronisation is an M5 capability and must not be faked.
    assert body["counts"]["registry_sync_state"] == "unavailable"


def test_ip_port_02_filters_are_server_owned(client: TestClient) -> None:
    """IPLF-REQ-IP-PORT-02 — filter scope narrows the portfolio deterministically."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-PORT-030A-FILTER")
    docket = _docket(client, headers, matter_id=matter["id"], title="Filter Mark")
    asset = _asset(client, headers, docket_id=docket["id"], title="Filterable Mark")
    _application(client, headers, docket_id=docket["id"], asset_id=asset["id"])
    _application(
        client,
        headers,
        docket_id=docket["id"],
        asset_id=asset["id"],
        office="UKIPO",
        jurisdiction="GB",
        filing_phase="pre_filing",
    )

    assert _portfolio(client, headers).json()["counts"]["total"] == 2

    by_jurisdiction = _portfolio(client, headers, jurisdiction="GB").json()
    assert by_jurisdiction["counts"]["total"] == 1
    assert by_jurisdiction["rows"][0]["jurisdiction"] == "GB"

    by_phase = _portfolio(client, headers, filing_phase="draft").json()
    assert by_phase["counts"]["total"] == 1
    assert by_phase["rows"][0]["filing_phase"] == "draft"

    by_office = _portfolio(client, headers, office="IP India").json()
    assert by_office["counts"]["total"] == 1

    # Free-text search matches the mark and the docket, case-insensitively.
    assert _portfolio(client, headers, query="filterable").json()["counts"]["total"] == 2
    assert _portfolio(client, headers, query="nonexistent").json()["counts"]["total"] == 0

    # An unknown filter value narrows to nothing rather than falling open.
    assert _portfolio(client, headers, jurisdiction="ZZ").json()["counts"]["total"] == 0

    # Filters compose.
    combined = _portfolio(client, headers, jurisdiction="GB", filing_phase="draft").json()
    assert combined["counts"]["total"] == 0

    # The echoed scope is the server's normalized view, not raw client input.
    echoed = _portfolio(client, headers, jurisdiction="gb").json()
    assert echoed["counts"]["total"] == 1
    assert echoed["filters"]["jurisdiction"] == ["gb"]


def test_uj04_exc02_restricted_records_are_omitted_not_teased(
    client: TestClient,
) -> None:
    """IPLF-UJ-04-EXC-02 — a restricted record leaks no row, count, or field."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)

    created = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Portfolio Associate",
            "email": "portfolio-associate@asterlegal.in",
            "password": "PortfolioAssoc123!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "portfolio-associate@asterlegal.in",
            "password": "PortfolioAssoc123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    associate_headers = auth_headers(str(login.json()["access_token"]))

    matter = _mk_matter(client, owner_token, "IP-PORT-030A-ACL")
    open_docket = _docket(
        client, owner_headers, matter_id=matter["id"], title="Open Portfolio Mark"
    )
    secret_docket = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Restricted Portfolio Mark",
        restricted=True,
    )
    open_asset = _asset(client, owner_headers, docket_id=open_docket["id"])
    secret_asset = _asset(
        client, owner_headers, docket_id=secret_docket["id"], title="Confidential Mark"
    )
    _application(
        client, owner_headers, docket_id=open_docket["id"], asset_id=open_asset["id"]
    )
    secret_application = _application(
        client,
        owner_headers,
        docket_id=secret_docket["id"],
        asset_id=secret_asset["id"],
    )

    # The owner sees both records.
    assert _portfolio(client, owner_headers).json()["counts"]["total"] == 2

    # The associate sees only the open one: no row, no count, no title, no id.
    scoped = _portfolio(client, associate_headers).json()
    assert scoped["counts"]["total"] == 1
    assert scoped["rows"][0]["docket_id"] == open_docket["id"]
    serialized = str(scoped)
    assert secret_docket["id"] not in serialized
    assert secret_application["id"] not in serialized
    assert "Confidential Mark" not in serialized
    assert "Restricted Portfolio Mark" not in serialized

    # A direct filter for the restricted record cannot confirm its existence.
    probed = _portfolio(client, associate_headers, query="confidential").json()
    assert probed["counts"]["total"] == 0
    assert probed["rows"] == []


def test_portfolio_is_tenant_isolated_and_paginates(client: TestClient) -> None:
    """Cross-company isolation plus a stable cursor contract."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-PORT-030A-PAGE")
    docket = _docket(client, headers, matter_id=matter["id"], title="Paging Mark")
    asset = _asset(client, headers, docket_id=docket["id"])
    for index in range(3):
        _application(
            client,
            headers,
            docket_id=docket["id"],
            asset_id=asset["id"],
            office=f"Office {index}",
        )

    first = _portfolio(client, headers, limit=2).json()
    assert len(first["rows"]) == 2
    assert first["next_cursor"]
    second = _portfolio(client, headers, limit=2, cursor=first["next_cursor"]).json()
    assert len(second["rows"]) == 1
    assert second["next_cursor"] is None
    # Pages are disjoint.
    assert not {r["application_id"] for r in first["rows"]} & {
        r["application_id"] for r in second["rows"]
    }

    assert _portfolio(client, headers, cursor="not-a-cursor").status_code == 400

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Portfolio Firm",
            "company_slug": "other-portfolio-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-portfolio.example",
            "owner_password": "OtherPortfolio123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    leaked = _portfolio(client, other_headers).json()
    assert leaked["counts"]["total"] == 0
    assert leaked["rows"] == []


def test_disposed_matter_filter_is_applied_before_portfolio_limit(
    client: TestClient,
) -> None:
    """A hidden leading candidate cannot swallow later operational records."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)

    live_matter = _mk_matter(client, token, "IP-PORT-LIVE-AFTER-DISPOSED")
    live_docket = _docket(
        client,
        headers,
        matter_id=live_matter["id"],
        title="Visible portfolio row",
    )
    live_asset = _asset(client, headers, docket_id=live_docket["id"])
    live_application = _application(
        client,
        headers,
        docket_id=live_docket["id"],
        asset_id=live_asset["id"],
    )

    # Create this application second so it sorts ahead of the live row.  A
    # legacy/inconsistent disposal can leave the docket active; the portfolio
    # must still hide it without consuming the page limit.
    disposed_matter = _mk_matter(client, token, "IP-PORT-DISPOSED-FIRST")
    disposed_docket = _docket(
        client,
        headers,
        matter_id=disposed_matter["id"],
        title="Hidden disposed portfolio row",
    )
    disposed_asset = _asset(client, headers, docket_id=disposed_docket["id"])
    _application(
        client,
        headers,
        docket_id=disposed_docket["id"],
        asset_id=disposed_asset["id"],
    )

    factory = get_session_factory()
    with factory() as session:
        row = session.get(Matter, disposed_matter["id"])
        assert row is not None
        row.status = "disposed"
        row.is_active = False
        session.commit()

    first = _portfolio(client, headers, limit=1)
    assert first.status_code == 200, first.text
    body = first.json()
    assert [row["application_id"] for row in body["rows"]] == [live_application["id"]]
    assert body["next_cursor"] is None
    assert disposed_docket["id"] not in str(body)
