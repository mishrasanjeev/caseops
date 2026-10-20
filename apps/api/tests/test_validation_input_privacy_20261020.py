from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from caseops_api.core.problem_details import register_problem_handlers


class CredentialInput(BaseModel):
    password: str = Field(max_length=10)
    token: str = Field(max_length=10)


class NestedInput(BaseModel):
    credential: CredentialInput


def _client() -> TestClient:
    app = FastAPI()
    register_problem_handlers(app)

    @app.post("/credential-validation")
    def validate(payload: NestedInput) -> dict[str, bool]:
        assert payload.credential is not None
        return {"accepted": True}

    return TestClient(app)


def test_nested_validation_response_never_reflects_submitted_credentials() -> None:
    password = "not-a-real-password-for-validation"
    token = "not-a-real-one-use-token-for-validation"
    with _client() as client:
        response = client.post(
            "/credential-validation",
            json={"credential": {"password": password, "token": token}},
        )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert password not in response.text
    assert token not in response.text
    errors = response.json()["errors"]
    assert len(errors) == 2
    assert {tuple(error["loc"]) for error in errors} == {
        ("body", "credential", "password"),
        ("body", "credential", "token"),
    }
    assert all(set(error) == {"loc", "msg", "type"} for error in errors)
    assert all("at most 10 characters" in error["msg"] for error in errors)


def test_valid_nested_input_keeps_its_success_contract() -> None:
    with _client() as client:
        response = client.post(
            "/credential-validation",
            json={"credential": {"password": "example", "token": "example"}},
        )
    assert response.status_code == 200
    assert response.json() == {"accepted": True}
