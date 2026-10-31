"""BUG-002: the WIPO Nice class catalogue (NCL 13-2026) and its read API.

The catalogue is the one predicate shared by the class picker and the
trademark particulars validator (see test_ip_trademark_class_rows_20261031).
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from caseops_api.services import ip_nice_classes as catalogue
from tests.test_auth_company import auth_headers, bootstrap_company

ROUTE = "/api/ip/nice-classes"


def _tenant(client: TestClient, *, slug: str, email: str) -> dict[str, str]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": slug.replace("-", " ").title(),
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Nice Catalogue Owner",
            "owner_email": email,
            "owner_password": "FixturePass123!",
        },
    )
    assert response.status_code == 200, response.text
    return auth_headers(str(response.json()["access_token"]))


def _owner(client: TestClient) -> dict[str, str]:
    return auth_headers(str(bootstrap_company(client)["access_token"]))


def _member_without_ip_read(client: TestClient, owner: dict[str, str]) -> dict[str, str]:
    """A colleague whose custom role grants matter work but not IP reads.

    Built through the product's own role and employee APIs, so the refusal is
    the one a firm configures, not a database shortcut.
    """
    role = client.post(
        "/api/companies/current/roles",
        headers=owner,
        json={"name": "Matter clerk", "permissions": ["matters:create"]},
    )
    assert role.status_code == 200, role.text
    user = client.post(
        "/api/companies/current/users",
        headers=owner,
        json={
            "full_name": "Matter Clerk",
            "email": "clerk@asterlegal.in",
            "role": "member",
            "password": "ClerkPass123!",
        },
    )
    assert user.status_code == 200, user.text
    assigned = client.post(
        f"/api/companies/current/employees/{user.json()['membership_id']}/role",
        headers=owner,
        json={"custom_role_id": role.json()["id"]},
    )
    assert assigned.status_code == 200, assigned.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "aster-legal",
            "email": "clerk@asterlegal.in",
            "password": "ClerkPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return auth_headers(str(login.json()["access_token"]))


# --- Catalogue ------------------------------------------------------------


def test_catalogue_holds_exactly_45_contiguous_classes_with_official_kinds() -> None:
    rows = catalogue.NICE_CLASSES
    assert [row.number for row in rows] == list(range(1, 46))
    assert all(row.kind == "goods" for row in rows if row.number <= 34)
    assert all(row.kind == "services" for row in rows if row.number >= 35)
    for row in rows:
        assert row.heading.strip() == row.heading and row.heading.endswith(".")
        assert len(row.heading) > 10
        assert row.note.startswith(f"Class {row.number} includes")
    assert catalogue.nice_class(0) is None
    assert catalogue.nice_class(46) is None
    assert catalogue.nice_class(True) is None  # type: ignore[arg-type]
    assert not catalogue.is_nice_class("35")


def test_catalogue_text_is_pinned_to_the_recorded_wipo_source() -> None:
    assert catalogue.NICE_EDITION == "NCL 13-2026"
    assert catalogue.NICE_IN_FORCE_FROM == date(2026, 1, 1)
    assert catalogue.NICE_RETRIEVED_ON == date(2026, 10, 31)
    assert catalogue.NICE_SOURCE_URL.startswith("https://nclpub.wipo.int/")
    assert "version=20260101" in catalogue.NICE_SOURCE_URL
    assert catalogue.NICE_SOURCE_DATA_URL.startswith("https://www.wipo.int/classifications/")
    assert "/20260101/" in catalogue.NICE_SOURCE_DATA_URL
    assert "WIPO" in catalogue.NICE_ATTRIBUTION
    # A hand edit to any heading or note changes the digest and fails here.
    assert (
        catalogue.sha256_text(catalogue.normalized_headings()) == catalogue.NICE_HEADINGS_SHA256
    )
    assert catalogue.sha256_text(catalogue.normalized_notes()) == catalogue.NICE_NOTES_SHA256
    # Spot checks against the WIPO NCL publication (version 20260101).
    assert catalogue.nice_class(35).heading == (
        "Advertising; business management, organization and administration; office functions."
    )
    assert catalogue.nice_class(45).heading == (
        "Legal services; security services for the physical protection of tangible property "
        "and individuals; dating services, online social networking services; funerary "
        "services; babysitting."
    )


# --- Read route -------------------------------------------------------------


def test_route_serves_the_catalogue_to_an_ip_reader(client: TestClient) -> None:
    response = client.get(ROUTE, headers=_owner(client))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["edition"] == "NCL 13-2026"
    assert body["in_force_from"] == "2026-01-01"
    assert body["retrieved_on"] == "2026-10-31"
    assert body["source_url"] == catalogue.NICE_SOURCE_URL
    assert body["source_data_url"] == catalogue.NICE_SOURCE_DATA_URL
    assert body["headings_sha256"] == catalogue.NICE_HEADINGS_SHA256
    assert body["attribution"] == catalogue.NICE_ATTRIBUTION
    assert [row["number"] for row in body["classes"]] == list(range(1, 46))
    assert body["classes"][34] == {
        "number": 35,
        "kind": "services",
        "heading": catalogue.nice_class(35).heading,
        "note": catalogue.nice_class(35).note,
    }
    assert {row["kind"] for row in body["classes"][:34]} == {"goods"}
    assert {row["kind"] for row in body["classes"][34:]} == {"services"}
    assert all(row["heading"] for row in body["classes"])


def test_route_refuses_anonymous_callers(client: TestClient) -> None:
    response = client.get(ROUTE)

    assert response.status_code == 401


def test_route_refuses_a_member_without_ip_read(client: TestClient) -> None:
    owner = _owner(client)
    clerk = _member_without_ip_read(client, owner)

    response = client.get(ROUTE, headers=clerk)

    assert response.status_code == 403
    assert "ip:read" in response.json()["detail"]
    assert "Advertising" not in response.text


def test_route_is_identical_for_every_tenant_and_carries_no_tenant_data(
    client: TestClient,
) -> None:
    first = client.get(ROUTE, headers=_tenant(client, slug="nice-one", email="a@nice-one.in"))
    second = client.get(ROUTE, headers=_tenant(client, slug="nice-two", email="b@nice-two.in"))

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert "company" not in first.text
    assert "nice-one" not in first.text


def test_route_is_read_only(client: TestClient) -> None:
    headers = _owner(client)

    assert client.post(ROUTE, headers=headers, json={}).status_code == 405
    assert set(client.get("/openapi.json").json()["paths"][ROUTE]) == {"get"}
