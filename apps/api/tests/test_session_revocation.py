from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company

STRONG = "FoundersPass123!"


def _create_member(client: TestClient, owner_token: str) -> dict[str, object]:
    return client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Temp Member",
            "email": "temp@asterlegal.in",
            "password": "TempAccess123!",
            "role": "member",
        },
    ).json()


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "company_slug": "aster-legal"},
    )
    return response.json()["access_token"]


def test_active_member_token_grants_access(client: TestClient) -> None:
    owner = bootstrap_company(client)
    _create_member(client, str(owner["access_token"]))
    member_token = _login(client, "temp@asterlegal.in", "TempAccess123!")
    response = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert response.status_code == 200


def test_suspended_member_token_is_rejected(client: TestClient) -> None:
    owner = bootstrap_company(client)
    owner_token = str(owner["access_token"])
    member = _create_member(client, owner_token)
    membership_id = member["membership_id"]

    member_token = _login(client, "temp@asterlegal.in", "TempAccess123!")
    assert client.get("/api/auth/me", headers=auth_headers(member_token)).status_code == 200

    # Suspend the membership
    update = client.patch(
        f"/api/companies/current/users/{membership_id}",
        headers=auth_headers(owner_token),
        json={"is_active": False},
    )
    assert update.status_code == 200

    denied = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert denied.status_code in {401, 403}


def test_token_predating_sessions_valid_after_is_revoked(client: TestClient) -> None:
    owner = bootstrap_company(client)
    owner_token = str(owner["access_token"])
    member = _create_member(client, owner_token)
    membership_id = member["membership_id"]
    member_token = _login(client, "temp@asterlegal.in", "TempAccess123!")
    assert client.get("/api/auth/me", headers=auth_headers(member_token)).status_code == 200

    # Simulate an administrative bump of sessions_valid_after (e.g., on password change).
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select, update

    from caseops_api.db.models import CompanyMembership
    from caseops_api.db.session import get_session_factory

    factory = get_session_factory()
    future = datetime.now(UTC) + timedelta(seconds=1)
    with factory() as session:
        session.execute(
            update(CompanyMembership)
            .where(CompanyMembership.id == membership_id)
            .values(sessions_valid_after=future)
        )
        session.commit()
        row = session.scalar(
            select(CompanyMembership).where(CompanyMembership.id == membership_id)
        )
        assert row is not None and row.sessions_valid_after is not None

    # Wait for the cutoff and verify existing token is no longer accepted.
    time.sleep(2)
    denied = client.get("/api/auth/me", headers=auth_headers(member_token))
    assert denied.status_code == 401


def test_suspension_bumps_sessions_valid_after(client: TestClient) -> None:
    owner = bootstrap_company(client)
    owner_token = str(owner["access_token"])
    member = _create_member(client, owner_token)
    membership_id = member["membership_id"]

    update_response = client.patch(
        f"/api/companies/current/users/{membership_id}",
        headers=auth_headers(owner_token),
        json={"is_active": False},
    )
    assert update_response.status_code == 200

    from sqlalchemy import select

    from caseops_api.db.models import CompanyMembership
    from caseops_api.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.id == membership_id)
        )
        assert membership is not None
        assert membership.sessions_valid_after is not None
