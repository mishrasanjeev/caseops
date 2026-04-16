from fastapi.testclient import TestClient

from caseops_api.main import app

client = TestClient(app)


def test_healthcheck_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_meta_exposes_service_identity() -> None:
    response = client.get("/api/meta")

    assert response.status_code == 200
    payload = response.json()

    assert payload["name"] == "CaseOps API"
    assert payload["version"] == "0.1.0"
    assert payload["environment"] == "local"
