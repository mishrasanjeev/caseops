from pathlib import Path

import pytest

from caseops_api.api.routes import private_retrieval as routes
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_private_retrieval_workflow import _other_company


@pytest.mark.parametrize("pending", [False, True])
def test_integrity_reads_current_api_session_and_authorized_tenant_only(
    client, monkeypatch, pending
):
    owner = bootstrap_company(client)
    other = _other_company(client)
    observed = []
    with get_session_factory()() as session:
        expected_url = session.get_bind().url

    def read(session, ids):
        assert session.get_bind().url == expected_url
        observed.append(ids)
        return pending

    monkeypatch.setattr(routes, "pending_document_jobs", read)
    response = client.get(
        "/api/private-retrieval/integrity",
        params={"company_id": str(other["company"]["id"])},
        headers=auth_headers(str(owner["access_token"])),
    )
    assert response.status_code == 200, response.text
    assert response.json()["document_processing_pending"] is pending
    assert observed == [(str(owner["company"]["id"]),)]
    assert str(other["company"]["id"]) not in response.text


def test_integrity_queue_readiness_does_not_bypass_authentication(client, monkeypatch):
    monkeypatch.setattr(
        routes, "pending_document_jobs", lambda *_: pytest.fail("Unauthorized queue read")
    )
    response = client.get("/api/private-retrieval/integrity")
    assert response.status_code in {401, 403}
    assert "document_processing_pending" not in response.json()


def test_review_gate_reads_actual_serving_api_before_each_creation_without_extra_retries():
    root = Path(__file__).resolve().parents[3]
    source = (root / "tests/e2e/iplf-063b-intelligent-review-2026-08-28-prod.spec.ts").read_text()
    body = source.split("async function queueReviewWithOneGenerationRetry(", 1)[1]
    gate = body.index("/api/private-retrieval/integrity")
    contract = body.index('typeof readiness.document_processing_pending !== "boolean"')
    idle = body.index('"The serving tenant document queue must settle before review creation."')
    create = body.index("/api/research/reviews`")
    assert gate < contract < idle < create
    assert "attempt <= 2" in body
    assert "test.setTimeout(420_000)" in body
    assert "Date.now() + 300_000" in body
