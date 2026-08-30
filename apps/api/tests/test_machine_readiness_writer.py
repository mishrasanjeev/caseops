from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.machine_readiness_auth import machine_readiness_signature
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    PineLabsUATRun,
    PineLabsUATScenarioEvidence,
    PlatformOperationalReadinessEvidence,
    ProductionBillingSignoff,
    ProductionBillingSignoffEvidence,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.production_safety import list_operational_readiness_evidence
from tests.test_auth_company import auth_headers, bootstrap_company

_RELEASE_SHA = "7" * 40
_WRITER_PATH = "/api/internal/machine-readiness/evidence"


def _machine_request(
    client: TestClient,
    payload: dict[str, object],
    *,
    timestamp: int | None = None,
    signature: str | None = None,
):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signed_at = str(timestamp if timestamp is not None else int(time.time()))
    secret = get_settings().machine_readiness_evidence_secret
    assert secret is not None
    request_signature = signature or machine_readiness_signature(
        secret=secret,
        timestamp=signed_at,
        body=body,
    )
    return client.post(
        _WRITER_PATH,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-CaseOps-Machine-Timestamp": signed_at,
            "X-CaseOps-Machine-Signature": request_signature,
        },
    )


def _payload(
    *,
    producer: str = "github-actions/prod-verify",
    release_sha: str = _RELEASE_SHA,
    items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema": "caseops.machine-readiness-write/v1",
        "producer": producer,
        "release_sha": release_sha,
        "run_id": "github-actions:403:1",
        "items": items
        or [
            {
                "kind": "billing_check",
                "subject": "platform_admin",
                "conclusion": "pass",
                "evidence_ref": "https://github.example/actions/runs/403",
            },
            {
                "kind": "operational_gate",
                "subject": "public_claims_reviewed",
                "conclusion": "pass",
                "evidence_ref": "https://github.example/actions/runs/403",
            },
        ],
    }


def test_machine_writer_is_hidden_machine_only_idempotent_and_tamper_evident(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", _RELEASE_SHA)
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    token = str(bootstrap_company(client)["access_token"])

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert _WRITER_PATH not in openapi.json()["paths"]

    # A fully authenticated platform founder has no authority at this boundary.
    browser_attempt = client.post(
        _WRITER_PATH,
        headers=auth_headers(token),
        json=_payload(),
    )
    assert browser_attempt.status_code == 401

    payload = _payload()
    recorded = _machine_request(client, payload)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["release_sha"] == _RELEASE_SHA
    assert recorded.json()["run_id"] == "github-actions:403:1"
    assert recorded.json()["recorded_count"] == 2

    replayed = _machine_request(client, payload)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["evidence_digest"] == recorded.json()["evidence_digest"]

    with get_session_factory()() as session:
        assert session.scalar(select(func.count(ProductionBillingSignoff.id))) == 1
        assert session.scalar(select(func.count(ProductionBillingSignoffEvidence.id))) == 1
        assert session.scalar(select(func.count(PlatformOperationalReadinessEvidence.id))) == 1
        operational = list_operational_readiness_evidence(session)
        claims = next(row for row in operational if row.gate_code == "public_claims_reviewed")
        assert claims.status == "pass"
        assert claims.owner_label == "automation:github-actions/prod-verify"

        # A direct database edit invalidates the stored HMAC proof and fails closed.
        row = session.scalar(select(PlatformOperationalReadinessEvidence))
        assert row is not None
        row.evidence_ref = "https://github.example/actions/runs/forged"
        session.commit()

    with get_session_factory()() as session:
        operational = list_operational_readiness_evidence(session)
        claims = next(row for row in operational if row.gate_code == "public_claims_reviewed")
        assert claims.status == "pending"
        assert claims.evidence_ref is None


def test_machine_writer_rejects_stale_wrong_release_and_mixed_authority_atomically(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", _RELEASE_SHA)
    get_settings.cache_clear()

    stale = _machine_request(client, _payload(), timestamp=int(time.time()) - 301)
    assert stale.status_code == 401

    wrong_release = _machine_request(client, _payload(release_sha="8" * 40))
    assert wrong_release.status_code == 409

    wrong_signature = _machine_request(client, _payload(), signature="sha256=" + "0" * 64)
    assert wrong_signature.status_code == 401

    # config-probe owns operational checks, not billing. The whole batch is rejected.
    mixed = _machine_request(
        client,
        _payload(
            producer="caseops/config-probe",
            items=[
                {
                    "kind": "operational_gate",
                    "subject": "public_claims_reviewed",
                    "conclusion": "pass",
                    "evidence_ref": "probe://config/403",
                },
                {
                    "kind": "billing_check",
                    "subject": "platform_admin",
                    "conclusion": "pass",
                    "evidence_ref": "probe://config/403",
                },
            ],
        ),
    )
    assert mixed.status_code == 403

    # A Pine write must target the latest real UAT run; preceding batch writes roll back.
    invalid_pine = _machine_request(
        client,
        _payload(
            producer="caseops/production-probe",
            items=[
                {
                    "kind": "billing_check",
                    "subject": "platform_admin",
                    "conclusion": "pass",
                    "evidence_ref": "probe://production/403",
                },
                {
                    "kind": "pine_labs_uat",
                    "subject": "plan_payment_success",
                    "conclusion": "pass",
                    "evidence_ref": "probe://production/403/pine",
                    "target_run_id": "not-the-current-run",
                },
            ],
        ),
    )
    assert invalid_pine.status_code == 409

    with get_session_factory()() as session:
        assert session.scalar(select(func.count(ProductionBillingSignoff.id))) == 0
        assert session.scalar(select(func.count(PlatformOperationalReadinessEvidence.id))) == 0


def test_production_probe_can_write_only_the_current_pine_run(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", _RELEASE_SHA)
    get_settings.cache_clear()
    with get_session_factory()() as session:
        run = PineLabsUATRun(environment="uat", provider_mode="live", status="in_progress")
        session.add(run)
        session.commit()
        run_id = run.id

    evidence_ref = f"probe://production/403/pine/{run_id}"
    recorded = _machine_request(
        client,
        _payload(
            producer="caseops/production-probe",
            items=[
                {
                    "kind": "pine_labs_uat",
                    "subject": "plan_payment_success",
                    "conclusion": "pass",
                    "evidence_ref": evidence_ref,
                    "target_run_id": run_id,
                }
            ],
        ),
    )
    assert recorded.status_code == 200, recorded.text

    with get_session_factory()() as session:
        row = session.scalar(select(PineLabsUATScenarioEvidence))
        assert row is not None
        assert row.run_id == run_id
        assert row.created_by_platform_admin_id is None
        assert row.attachment_refs_json == [evidence_ref]
        assert row.redacted_payload_json is not None
        envelope = row.redacted_payload_json["machine_evidence"]
        assert envelope["producer"] == "caseops/production-probe"
        assert envelope["release_sha"] == _RELEASE_SHA
        assert envelope["subject"] == "pine_labs_uat:plan_payment_success"
