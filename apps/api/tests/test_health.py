from fastapi.testclient import TestClient

from caseops_api.main import app

client = TestClient(app)


def test_healthcheck_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ingest_returns_global_aggregates_unauthenticated(client: TestClient) -> None:
    """The ingest-VM watchdog (Cloud Run Job) calls this without auth.

    Returns global aggregates (no tenant data, no per-document data).
    Used to decide whether to reset the ingest VM when last_ingested_at
    falls more than INGEST_STALE_HOURS behind wall clock. The ``client``
    fixture wires a sqlite-backed app so this exercises the real DB
    query, not a mock.
    """
    response = client.get("/api/health/ingest")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"document_count", "chunk_count", "last_ingested_at"}
    assert isinstance(payload["document_count"], int)
    assert isinstance(payload["chunk_count"], int)
    assert payload["last_ingested_at"] is None or isinstance(payload["last_ingested_at"], str)


def test_meta_exposes_service_identity() -> None:
    response = client.get("/api/meta")

    assert response.status_code == 200
    payload = response.json()

    assert payload["name"] == "CaseOps API"
    assert payload["version"] == "0.1.0"
    assert payload["environment"] == "local"
