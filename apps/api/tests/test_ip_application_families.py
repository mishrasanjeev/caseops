"""IPLF-033A application family grouping (IP-PROS-11) and the UJ-06 timeline.

Stable manifest test IDs:

* ``IPLF-REQ-IP-PROS-11``  related applications group without losing identity
* ``IPLF-UJ-06-NORMAL``    record a prosecution event and read it back
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_client, _mk_matter
from tests.test_ip_record_workflow import _particulars


def _docket(client: TestClient, headers, *, matter_id: str, title: str) -> dict:
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": False,
            "particulars": _particulars(title.upper()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _asset(client: TestClient, headers, *, docket_id: str, title: str) -> dict:
    response = client.post(
        f"/api/ip/dockets/{docket_id}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _application(client: TestClient, headers, *, docket_id: str, asset_id: str, **kw) -> dict:
    payload = {
        "asset_id": asset_id,
        "office": "IP India",
        "jurisdiction": "IN",
        "filing_phase": "draft",
    }
    payload.update(kw)
    response = client.post(
        f"/api/ip/dockets/{docket_id}/applications", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()["application"]


def _families(client: TestClient, headers, **params):
    return client.get("/api/ip/portfolio/families", headers=headers, params=params)


def test_ip_pros_11_marks_group_without_losing_member_identity(
    client: TestClient,
) -> None:
    """IPLF-REQ-IP-PROS-11 — one mark, several jurisdictions, independent members."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-FAM-033A")
    docket = _docket(client, headers, matter_id=matter["id"], title="Family Mark")
    asset = _asset(client, headers, docket_id=docket["id"], title="Aster Family Mark")

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

    response = _families(client, headers, grouping="mark")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["grouping"] == "mark"
    assert len(body["families"]) == 1

    family = body["families"][0]
    assert family["family_key"] == asset["id"]
    assert family["label"] == "Aster Family Mark"
    assert family["member_count"] == 2
    assert family["distinct_jurisdictions"] == ["GB", "IN"]
    assert sorted(family["distinct_filing_phases"]) == ["draft", "pre_filing"]

    # IP-PROS-11: members keep independent identity, office, jurisdiction,
    # phase and lifecycle. The family exposes no shared phase or identifier.
    members = {m["application_id"]: m for m in family["members"]}
    assert set(members) == {india["id"], uk["id"]}
    assert members[india["id"]]["jurisdiction"] == "IN"
    assert members[uk["id"]]["jurisdiction"] == "GB"
    assert members[india["id"]]["filing_phase"] != members[uk["id"]]["filing_phase"]
    assert members[india["id"]]["office"] != members[uk["id"]]["office"]
    assert "filing_phase" not in family
    assert "primary_identifier" not in family


def test_ip_pros_11_member_lifecycle_stays_independent(client: TestClient) -> None:
    """IPLF-REQ-IP-PROS-11 — advancing one member does not move its siblings."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-FAM-033A-LC")
    docket = _docket(client, headers, matter_id=matter["id"], title="Lifecycle Family")
    asset = _asset(client, headers, docket_id=docket["id"], title="Lifecycle Mark")
    first = _application(client, headers, docket_id=docket["id"], asset_id=asset["id"])
    second = _application(
        client,
        headers,
        docket_id=docket["id"],
        asset_id=asset["id"],
        office="UKIPO",
        jurisdiction="GB",
    )

    before = _families(client, headers, grouping="mark").json()["families"][0]
    versions = {m["application_id"]: m["lifecycle_version"] for m in before["members"]}

    advanced = client.patch(
        f"/api/ip/applications/{first['id']}/filing-phase",
        headers=headers,
        json={"filing_phase": "pre_filing", "expected_version": first["version"]},
    )
    assert advanced.status_code == 200, advanced.text

    after = _families(client, headers, grouping="mark").json()["families"][0]
    members = {m["application_id"]: m for m in after["members"]}
    assert members[first["id"]]["filing_phase"] == "pre_filing"
    # The sibling is untouched: same phase and same lifecycle version.
    assert members[second["id"]]["filing_phase"] == "draft"
    assert members[second["id"]]["lifecycle_version"] == versions[second["id"]]
    assert after["member_count"] == 2


def test_families_group_by_client_and_report_ungrouped(client: TestClient) -> None:
    """Client grouping crosses Matters and preserves a truthful ungrouped count."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    first_matter = _mk_matter(client, token, "IP-FAM-033A-C1")
    second_matter = _mk_matter(client, token, "IP-FAM-033A-C2")
    ungrouped_matter = _mk_matter(client, token, "IP-FAM-033A-C3")
    shared_client_response = _mk_client(
        client,
        token,
        name="Shared Trademark Client",
        primary_contact_email="shared-client@example.com",
    )
    assert shared_client_response.status_code == 200, shared_client_response.text
    shared_client = shared_client_response.json()
    for matter in (first_matter, second_matter):
        assigned = client.post(
            f"/api/matters/{matter['id']}/clients",
            headers=headers,
            json={"client_id": shared_client["id"], "role": "proprietor"},
        )
        assert assigned.status_code == 200, assigned.text

    d1 = _docket(client, headers, matter_id=first_matter["id"], title="Client One Mark")
    d2 = _docket(client, headers, matter_id=second_matter["id"], title="Client Two Mark")
    d3 = _docket(client, headers, matter_id=ungrouped_matter["id"], title="No Client Mark")
    a1 = _asset(client, headers, docket_id=d1["id"], title="Mark One")
    a2 = _asset(client, headers, docket_id=d2["id"], title="Mark Two")
    a3 = _asset(client, headers, docket_id=d3["id"], title="Mark Three")
    _application(client, headers, docket_id=d1["id"], asset_id=a1["id"])
    _application(
        client, headers, docket_id=d1["id"], asset_id=a1["id"], office="UKIPO", jurisdiction="GB"
    )
    _application(client, headers, docket_id=d2["id"], asset_id=a2["id"])
    _application(client, headers, docket_id=d3["id"], asset_id=a3["id"])

    by_client = _families(client, headers, grouping="client").json()
    assert by_client["grouping"] == "client"
    assert [f["member_count"] for f in by_client["families"]] == [3]
    assert by_client["families"][0]["family_key"] == shared_client["id"]
    assert by_client["families"][0]["label"] == "Shared Trademark Client"
    assert by_client["ungrouped_member_count"] == 1

    by_mark = _families(client, headers, grouping="mark").json()
    assert sorted(f["member_count"] for f in by_mark["families"]) == [1, 1, 2]

    # Filters still apply to the grouped view.
    filtered = _families(client, headers, grouping="mark", jurisdiction="GB").json()
    assert sum(f["member_count"] for f in filtered["families"]) == 1

    assert _families(client, headers, grouping="invalid").status_code == 422


def test_family_pages_are_bounded_and_cursor_stable(client: TestClient) -> None:
    """IPLF-033B returns whole families without an unbounded application scan."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    expected_keys: set[str] = set()
    for number in range(4):
        matter = _mk_matter(client, token, f"IP-FAM-033B-PAGE-{number}")
        docket = _docket(
            client,
            headers,
            matter_id=matter["id"],
            title=f"Paged Mark {number}",
        )
        asset = _asset(
            client,
            headers,
            docket_id=docket["id"],
            title=f"Paged Mark {number}",
        )
        expected_keys.add(asset["id"])
        _application(client, headers, docket_id=docket["id"], asset_id=asset["id"])

    first = _families(client, headers, grouping="mark", limit=2)
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["limit"] == 2
    assert len(first_body["families"]) == 2
    assert first_body["next_cursor"]

    second = _families(
        client,
        headers,
        grouping="mark",
        limit=2,
        cursor=first_body["next_cursor"],
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert len(second_body["families"]) == 2
    assert second_body["next_cursor"] is None
    returned_keys = {
        family["family_key"]
        for family in [*first_body["families"], *second_body["families"]]
    }
    assert returned_keys == expected_keys
    assert _families(client, headers, grouping="mark", cursor="broken").status_code == 400


def test_families_are_access_scoped_and_tenant_isolated(client: TestClient) -> None:
    """A record the caller cannot open contributes no family and no member."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    created = client.post(
        "/api/companies/current/users",
        headers=owner_headers,
        json={
            "full_name": "Family Associate",
            "email": "family-associate@asterlegal.in",
            "password": "FamilyAssoc123!",
            "role": "admin",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "family-associate@asterlegal.in",
            "password": "FamilyAssoc123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    associate_headers = auth_headers(str(login.json()["access_token"]))

    matter = _mk_matter(client, owner_token, "IP-FAM-033A-ACL")
    open_docket = _docket(client, owner_headers, matter_id=matter["id"], title="Open Family")
    restricted = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "Secret Family",
            "matter_id": matter["id"],
            "restricted": True,
            "particulars": _particulars("SECRET FAMILY"),
        },
    )
    assert restricted.status_code == 201, restricted.text
    secret = restricted.json()

    open_asset = _asset(client, owner_headers, docket_id=open_docket["id"], title="Open Mark")
    secret_asset = _asset(client, owner_headers, docket_id=secret["id"], title="Secret Mark")
    _application(client, owner_headers, docket_id=open_docket["id"], asset_id=open_asset["id"])
    _application(client, owner_headers, docket_id=secret["id"], asset_id=secret_asset["id"])

    assert len(_families(client, owner_headers, grouping="mark").json()["families"]) == 2

    scoped = _families(client, associate_headers, grouping="mark").json()
    assert len(scoped["families"]) == 1
    serialized = str(scoped)
    assert secret["id"] not in serialized
    assert secret_asset["id"] not in serialized
    assert "Secret Mark" not in serialized

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Family Firm",
            "company_slug": "other-family-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-family.example",
            "owner_password": "OtherFamily123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    leaked = _families(client, other_headers, grouping="mark").json()
    assert leaked["families"] == []


def test_uj06_normal_record_prosecution_event_and_read_timeline(
    client: TestClient,
) -> None:
    """IPLF-UJ-06-NORMAL — record an event and read it back from the workspace."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    membership_id = str(bootstrap["membership"]["id"])
    headers = auth_headers(token)
    matter = _mk_matter(client, token, "IP-PROS-033A")
    docket = _docket(client, headers, matter_id=matter["id"], title="Prosecution Mark")

    preview = client.post(
        f"/api/ip/dockets/{docket['id']}/events/preview",
        headers=headers,
        json={
            "event_kind": "examination_report",
            "source": "manual",
            "effective_at": "2026-08-10T09:00:00Z",
            "reason": "Examination report received from the registry.",
            "responsible_membership_id": membership_id,
            "expected_lifecycle_version": docket["lifecycle_version"],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["operational_effects_are_proposals"] is True
    assert preview.json()["filing_claimed"] is False

    created = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json={
            "event_kind": "examination_report",
            "source": "manual",
            "effective_at": "2026-08-10T09:00:00Z",
            "reason": "Examination report received from the registry.",
            "responsible_membership_id": membership_id,
            "expected_lifecycle_version": docket["lifecycle_version"],
        },
    )
    assert created.status_code == 201, created.text
    event = created.json()
    assert event["event_kind"] == "examination_report"
    assert event["source"] == "manual"
    assert event["supersedes_event_id"] is None

    workspace = client.get(
        f"/api/ip/dockets/{docket['id']}/prosecution", headers=headers
    )
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    assert [item["id"] for item in body["events"]] == [event["id"]]
    assert body["docket_id"] == docket["id"]
    # IP-PROS-12 dispositions are reported separately, not collapsed.
    for key in (
        "operational_completion_count",
        "filing_evidence_count",
        "registry_acceptance_count",
        "final_disposition_count",
    ):
        assert key in body
