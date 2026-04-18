from __future__ import annotations

from fastapi.testclient import TestClient


def bootstrap_company(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
                "company_name": "Aster Legal LLP",
                "company_slug": "aster-legal",
                "company_type": "law_firm",
                "owner_full_name": "Sanjay Mishra",
                "owner_email": "owner@asterlegal.in",
                "owner_password": "FoundersPass123!",
            },
        )
    assert response.status_code == 200
    return response.json()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_company_bootstrap_creates_owner_session(client: TestClient) -> None:
    payload = bootstrap_company(client)

    assert payload["token_type"] == "bearer"
    assert payload["company"]["slug"] == "aster-legal"
    assert payload["membership"]["role"] == "owner"
    assert payload["user"]["email"] == "owner@asterlegal.in"


def test_bootstrap_accepts_solo_company_type(client: TestClient) -> None:
    """PRD §4.1.C / §8.3 calls for solo practitioners as a first-class
    persona. Bootstrapping a solo tenant must succeed without having to
    misrepresent the firm as a law_firm just to get through validation."""
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Ravi Solo Practice",
            "company_slug": "ravi-solo",
            "company_type": "solo",
            "owner_full_name": "Ravi Solo",
            "owner_email": "ravi@ravisolo.in",
            "owner_password": "SoloPass1234!",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["company"]["company_type"] == "solo"


def test_duplicate_company_slug_is_rejected(client: TestClient) -> None:
    bootstrap_company(client)

    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Aster GC",
            "company_slug": "aster-legal",
            "company_type": "corporate_legal",
            "owner_full_name": "Second Owner",
            "owner_email": "owner2@astergc.in",
            "owner_password": "SecondPass123!",
        },
    )

    assert response.status_code == 409


def test_login_returns_current_company_session(client: TestClient) -> None:
    bootstrap_company(client)

    response = client.post(
        "/api/auth/login",
        json={
            "email": "owner@asterlegal.in",
            "password": "FoundersPass123!",
            "company_slug": "aster-legal",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["company"]["name"] == "Aster Legal LLP"
    assert payload["membership"]["role"] == "owner"


def test_owner_can_create_and_list_company_users(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    create_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(token),
        json={
            "full_name": "Priya Associate",
            "email": "priya@asterlegal.in",
            "password": "AssociatePass123!",
            "role": "admin",
        },
    )

    assert create_response.status_code == 200
    assert create_response.json()["role"] == "admin"

    list_response = client.get("/api/companies/current/users", headers=auth_headers(token))
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload["users"]) == 2
    assert {user["email"] for user in payload["users"]} == {
        "owner@asterlegal.in",
        "priya@asterlegal.in",
    }


def test_non_owner_cannot_manage_memberships(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    create_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Meera Member",
            "email": "meera@asterlegal.in",
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert create_response.status_code == 200

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "meera@asterlegal.in",
            "password": "MemberPass123!",
            "company_slug": "aster-legal",
        },
    )
    member_token = str(login_response.json()["access_token"])

    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(member_token),
        json={
            "full_name": "Blocked User",
            "email": "blocked@asterlegal.in",
            "password": "BlockedPass123!",
            "role": "member",
        },
    )

    assert response.status_code == 403


def test_owner_can_deactivate_company_user(client: TestClient) -> None:
    bootstrap_payload = bootstrap_company(client)
    owner_token = str(bootstrap_payload["access_token"])

    create_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Arjun Member",
            "email": "arjun@asterlegal.in",
            "password": "ArjunPass123!",
            "role": "member",
        },
    )
    membership_id = create_response.json()["membership_id"]

    update_response = client.patch(
        f"/api/companies/current/users/{membership_id}",
        headers=auth_headers(owner_token),
        json={"is_active": False},
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["membership_active"] is False
    assert payload["user_active"] is False
