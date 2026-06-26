from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company


def _valid_matter_payload(code: str) -> dict[str, object]:
    return {
        "title": "Matter code validation",
        "matter_code": code,
        "practice_area": "Commercial",
        "forum_level": "high_court",
        "status": "intake",
    }


@pytest.mark.parametrize("code", ["BAD CODE", "BAD_CODE", "BAD/1", "-BAD", "BAD-"])
def test_create_matter_rejects_invalid_matter_code(
    client: TestClient,
    code: str,
) -> None:
    token = str(bootstrap_company(client)["access_token"])

    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json=_valid_matter_payload(code),
    )

    assert response.status_code == 422
    assert "matter_code" in response.text
    assert "letters, numbers, and hyphens" in response.text


def test_create_matter_normalizes_valid_code_before_persisting(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])

    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json=_valid_matter_payload("  cr-2026-014  "),
    )

    assert response.status_code == 200, response.text
    assert response.json()["matter_code"] == "CR-2026-014"


def test_matter_code_availability_rejects_invalid_code(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])

    response = client.get(
        "/api/matters/code-available?code=BAD_CODE",
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["suggestion"] is None
    assert "letters, numbers, and hyphens" in body["reason"]


def test_intake_promote_rejects_invalid_matter_code(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    intake = client.post(
        "/api/intake/requests",
        headers=auth_headers(token),
        json={
            "title": "Cheque bounce request",
            "category": "litigation_support",
            "requester_name": "Hari",
            "description": "Open a matter for cheque dishonour notice timing.",
        },
    )
    assert intake.status_code == 200, intake.text

    response = client.post(
        f"/api/intake/requests/{intake.json()['id']}/promote",
        headers=auth_headers(token),
        json={"matter_code": "INT_BAD/1"},
    )

    assert response.status_code == 422
    assert "letters, numbers, and hyphens" in response.text
