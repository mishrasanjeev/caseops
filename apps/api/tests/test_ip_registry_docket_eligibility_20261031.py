"""BUG-012 (Ram 2026-10-30): the registry docket picker and the link validator agree.

A registry identity attaches to a national trademark application or an IP
proceeding of the chosen docket. A Madrid international registration or
designation docket has neither, so the registry page auto-selected one and
offered an empty "Legal record" list. GET /api/ip/dockets now narrows by
record type on the server, so the registry picker lists only national
dockets with honest totals and pages, and the link writer keeps refusing a
target that is not on the docket.
"""

from __future__ import annotations

from typing import get_args

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import IpRegistryLink
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_operations import IpTrademarkDocketRecordType
from caseops_api.services.ip_domain_policy import TRADEMARK_RECORD_TYPES
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_authorities import _bootstrap_second_company
from tests.test_ip_international import _registration_payload
from tests.test_ip_record_workflow import _application, _asset, _docket


def _national(client: TestClient, headers: dict[str, str], title: str) -> tuple[dict, dict]:
    docket = _docket(client, headers, title)
    asset = _asset(client, headers, docket["id"], title)
    return docket, _application(client, headers, docket["id"], asset["id"])


def _madrid(client: TestClient, headers: dict[str, str], application_id: str) -> dict:
    created = client.post(
        "/api/ip/international-registrations",
        headers=headers,
        json=_registration_payload(basic_application_id=application_id, ir_number="1888777"),
    )
    assert created.status_code == 201, created.text
    return created.json()


def _list(client: TestClient, headers: dict[str, str], **params: object) -> dict:
    response = client.get("/api/ip/dockets", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _link_body(*, application_id: str) -> dict[str, object]:
    return {
        "application_id": application_id,
        "provider_key": "ipindia-registry",
        "office": "IP India",
        "jurisdiction": "IN",
        "identifier_kind": "application",
        "raw_identifier": "TM 4009154",
        "source_url": "https://tmrsearch.ipindia.gov.in/eregister/4009154",
        "match_confidence": "0.9500",
        "match_evidence": {"capture": "manual"},
        "terms_version": None,
        "capability_version": "manual-evidence-v1",
    }


def _link_count(company_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(IpRegistryLink)
                .where(IpRegistryLink.company_id == company_id)
            )
            or 0
        )


def test_record_type_filter_is_the_trademark_domain_vocabulary() -> None:
    assert set(get_args(IpTrademarkDocketRecordType)) == set(TRADEMARK_RECORD_TYPES)


def test_registry_picker_lists_only_national_dockets_with_honest_totals(
    client: TestClient,
) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    first, application = _national(client, headers, "PINE LABS")
    second, _ = _national(client, headers, "ASTER BISCUITS")
    # Created last, so it is the most recently updated docket: the one the
    # old page auto-selected.
    madrid = _madrid(client, headers, application["id"])

    everything = _list(client, headers)
    assert madrid["docket_id"] in {row["id"] for row in everything["dockets"]}
    assert everything["dockets"][0]["id"] == madrid["docket_id"]
    assert everything["total_count"] == 3

    national = _list(client, headers, record_type="trademark")
    assert [row["id"] for row in national["dockets"]] == [second["id"], first["id"]]
    assert {row["record_type"] for row in national["dockets"]} == {"trademark"}
    assert national["total_count"] == 2
    assert national["has_more"] is False

    # Totals and cursor pages count only the requested type.
    page = _list(client, headers, record_type="trademark", limit=1)
    assert page["total_count"] == 2
    assert page["has_more"] is True
    rest = _list(client, headers, record_type="trademark", limit=1, cursor=page["next_cursor"])
    assert rest["total_count"] == 2
    assert [row["id"] for row in page["dockets"] + rest["dockets"]] == [
        second["id"],
        first["id"],
    ]
    assert rest["next_cursor"] is None

    # Search inside the filter: the Madrid mark is not reachable from it.
    assert _list(client, headers, record_type="trademark", query="1888777")["total_count"] == 0
    madrid_only = _list(client, headers, record_type="international_registration")
    assert [row["id"] for row in madrid_only["dockets"]] == [madrid["docket_id"]]
    both = _list(
        client,
        headers,
        record_type=["trademark", "international_registration"],
    )
    assert both["total_count"] == 3


def test_record_type_filter_rejects_other_domains_with_a_field_error(
    client: TestClient,
) -> None:
    headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    for value in ("patent_family", "copyright_intake", "TRADEMARK", ""):
        response = client.get(
            "/api/ip/dockets", headers=headers, params={"record_type": value}
        )
        assert response.status_code == 422, (value, response.text)
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["detail"].startswith("Record type"), response.text
        assert response.json()["errors"][0]["loc"][:2] == ["query", "record_type"]
    client.cookies.clear()
    assert (
        client.get("/api/ip/dockets", params={"record_type": "trademark"}).status_code == 401
    )


def test_madrid_docket_has_no_registry_target_and_the_writer_refuses_foreign_records(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    headers = auth_headers(str(bootstrap["access_token"]))
    pine, pine_application = _national(client, headers, "PINE LABS")
    aster, aster_application = _national(client, headers, "ASTER BISCUITS")
    madrid = _madrid(client, headers, pine_application["id"])

    core = client.get(f"/api/ip/dockets/{madrid['docket_id']}/core-records", headers=headers)
    assert core.status_code == 200, core.text
    assert core.json()["applications"] == []
    assert core.json()["proceedings"] == []

    # The Madrid docket has nothing to attach to, and a national record of
    # another docket is refused there and on any other docket.
    for docket_id, application_id, message in (
        (madrid["docket_id"], pine_application["id"], "Trademark application not found"),
        (aster["id"], pine_application["id"], "Trademark application not found"),
    ):
        refused = client.post(
            f"/api/ip/dockets/{docket_id}/registry-links",
            headers=headers,
            json=_link_body(application_id=application_id),
        )
        assert refused.status_code == 404, refused.text
        assert refused.json()["detail"] == f"{message} on this docket."
    assert _link_count(company_id) == 0

    accepted = client.post(
        f"/api/ip/dockets/{aster['id']}/registry-links",
        headers=headers,
        json=_link_body(application_id=aster_application["id"]),
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["docket_id"] == aster["id"]
    assert _link_count(company_id) == 1
    assert pine["id"] != aster["id"]


def test_record_type_filter_stays_inside_the_caller_tenant(client: TestClient) -> None:
    first_headers = auth_headers(str(bootstrap_company(client)["access_token"]))
    second_headers = auth_headers(str(_bootstrap_second_company(client)["access_token"]))
    ours, _ = _national(client, first_headers, "SHARED MARK")
    theirs, _ = _national(client, second_headers, "SHARED MARK")

    first_view = _list(client, first_headers, record_type="trademark")
    assert [row["id"] for row in first_view["dockets"]] == [ours["id"]]
    assert first_view["total_count"] == 1
    second_view = _list(client, second_headers, record_type="trademark", query="shared")
    assert [row["id"] for row in second_view["dockets"]] == [theirs["id"]]
