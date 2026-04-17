from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.password_policy import WeakPasswordError, enforce_password_policy

STRONG = "FoundersPass123!"


def test_strong_password_is_accepted() -> None:
    enforce_password_policy(STRONG)


@pytest.mark.parametrize(
    "password, fragment",
    [
        ("Short1!", "at least 12"),
        ("a" * 129 + "A1!", "at most 128"),
        ("alllowercase123!", "uppercase"),
        ("ALLUPPERCASE123!", "lowercase"),
        ("NoDigitsHere!xx", "digit"),
        ("NoSymbolsHere123", "symbol"),
        ("Has Spaces 123!", "whitespace"),
    ],
)
def test_weak_password_is_rejected(password: str, fragment: str) -> None:
    with pytest.raises(WeakPasswordError) as exc:
        enforce_password_policy(password)
    assert fragment in str(exc.value)


def _bootstrap(client: TestClient, password: str) -> int:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Policy Firm",
            "company_slug": "policy-firm",
            "company_type": "law_firm",
            "owner_full_name": "Policy Owner",
            "owner_email": "owner@policyfirm.in",
            "owner_password": password,
        },
    )
    return response.status_code


def test_bootstrap_rejects_weak_password(client: TestClient) -> None:
    status = _bootstrap(client, "alllowercase123!")
    assert status == 400


def test_bootstrap_accepts_strong_password(client: TestClient) -> None:
    status = _bootstrap(client, STRONG)
    assert status == 200


def test_create_user_rejects_weak_password(client: TestClient) -> None:
    status = _bootstrap(client, STRONG)
    assert status == 200
    login = client.post(
        "/api/auth/login",
        json={
            "email": "owner@policyfirm.in",
            "password": STRONG,
            "company_slug": "policy-firm",
        },
    )
    token = login.json()["access_token"]

    weak = client.post(
        "/api/companies/current/users",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "Weak Member",
            "email": "weak@policyfirm.in",
            "password": "weakpass1234",
            "role": "member",
        },
    )
    assert weak.status_code == 400
