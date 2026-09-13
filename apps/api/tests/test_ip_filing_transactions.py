"""IPLF-039I filing transactions: durable evidence gates the filed phase."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingSubscription, IpFilingTransaction
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.ip_filing import IpFilingConfirmationTransactionRequest
from tests.test_auth_company import auth_headers, bootstrap_company

_TRANSACTION_PATHS = {
    "preparation": "/api/ip/applications/{application_id}/filing-transactions/preparation",
    "confirmation": "/api/ip/applications/{application_id}/filing-transactions/confirmation",
}


def _enable_filing(company_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_FILING_OPERATIONS_ENABLED", "true")
    monkeypatch.setenv(
        "CASEOPS_IP_FILING_OPERATIONS_ROLLOUT_EXPIRES_AT", "2030-01-01T00:00:00Z"
    )
    get_settings.cache_clear()
    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription).where(BillingSubscription.company_id == company_id)
        )
        if subscription is None:
            session.add(
                BillingSubscription(
                    company_id=company_id,
                    status="manual_active",
                    segment="law_firm",
                    source="iplf-039g-fixture",
                    externally_billable=False,
                    entitlement_overrides_json={"ip_filing_operations": True},
                )
            )
        else:
            subscription.entitlement_overrides_json = {
                **(subscription.entitlement_overrides_json or {}),
                "ip_filing_operations": True,
            }
        session.commit()


def _application(client, headers: dict[str, str]) -> dict:
    particulars = {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {"text": "ASTER", "evidence_reference": "document:aster"},
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": "Aster Applicant LLP"}],
        "agent": None,
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": "document:aster",
            }
        ],
    }
    docket_response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": "ASTER filing", "restricted": False, "particulars": particulars},
    )
    assert docket_response.status_code == 201, docket_response.text
    docket = docket_response.json()
    asset_response = client.post(
        f"/api/ip/dockets/{docket['id']}/assets",
        headers=headers,
        json={"asset_kind": "trademark", "jurisdiction": "IN", "title": "ASTER"},
    )
    assert asset_response.status_code == 201, asset_response.text
    application_response = client.post(
        f"/api/ip/dockets/{docket['id']}/applications",
        headers=headers,
        json={
            "asset_id": asset_response.json()["id"],
            "office": "Trade Marks Registry Mumbai",
            "jurisdiction": "IN",
            "filing_phase": "pre_filing",
            "source_pending_identifier_allocation": False,
            "application_number": {
                "raw_value": "TM/039G/2026",
                "source": "fixture",
                "effective_from": "2026-09-13",
                "is_primary": True,
            },
        },
    )
    assert application_response.status_code == 201, application_response.text
    return docket, application_response.json()["application"]


def _tx(client, headers, application_id: str, endpoint: str, **body):
    payload = {
        "expected_lifecycle_version": 0,
        "expected_application_version": 1,
        "attempt_key": "attempt-1",
        "idempotency_key": body.pop("idempotency_key"),
        "external_reference": "registry:fixture",
        "evidence_reference": "document:fixture",
        "occurred_at": body.pop("occurred_at"),
        **body,
    }
    return client.post(
        _TRANSACTION_PATHS[endpoint].format(application_id=application_id),
        headers=headers,
        json=payload,
    )


def test_acceptance_requires_complete_immutable_evidence() -> None:
    with pytest.raises(ValidationError, match="immutable filing evidence"):
        IpFilingConfirmationTransactionRequest.model_validate(
            {
                "expected_lifecycle_version": 0,
                "expected_application_version": 1,
                "attempt_key": "attempt-1",
                "idempotency_key": "acceptance-1",
                "related_transaction_id": "submission-1",
                "external_reference": "registry:1",
                "evidence_reference": "document:1",
                "occurred_at": "2026-09-13T09:00:00Z",
                "transaction_kind": "accepted",
                "authorized_confirmation": "Attorney confirmed",
                "form_refs": ["form:TM-A:2026.1"],
                "fee_evidence_refs": ["receipt:1"],
                "approval_reference": "approval:1",
            }
        )


def test_filing_chain_keeps_pre_filing_until_accepted_and_is_idempotent(client, monkeypatch):
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    _enable_filing(str(bootstrap["company"]["id"]), monkeypatch)
    docket, application = _application(client, headers)

    direct_phase = client.patch(
        f"/api/ip/applications/{application['id']}/filing-phase",
        headers=headers,
        json={"expected_version": 1, "filing_phase": "filed"},
    )
    assert direct_phase.status_code == 409
    assert direct_phase.json()["code"] == "ip_filing_transaction_required"

    direct = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "expected_application_version": 1,
            "application_id": application["id"],
            "event_kind": "filing",
            "source": "manual",
            "effective_at": "2026-09-13T09:00:00Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Direct filing must be rejected.",
        },
    )
    assert direct.status_code == 409
    assert direct.json()["code"] == "ip_filing_transaction_required"

    submitted = _tx(
        client,
        headers,
        application["id"],
        "preparation",
        transaction_kind="submitted",
        idempotency_key="submit-1",
        occurred_at="2026-09-13T09:01:00Z",
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["transaction"]["id"]
    paid = _tx(
        client,
        headers,
        application["id"],
        "preparation",
        transaction_kind="fee_paid",
        idempotency_key="paid-0001",
        related_transaction_id=submission_id,
        occurred_at="2026-09-13T09:02:00Z",
    )
    assert paid.status_code == 201, paid.text
    ack = _tx(
        client,
        headers,
        application["id"],
        "confirmation",
        transaction_kind="acknowledgement_received",
        idempotency_key="ack-0001",
        related_transaction_id=submission_id,
        occurred_at="2026-09-13T09:03:00Z",
    )
    assert ack.status_code == 201, ack.text
    defect = _tx(
        client,
        headers,
        application["id"],
        "confirmation",
        transaction_kind="defect_recorded",
        idempotency_key="defect-0001",
        related_transaction_id=ack.json()["transaction"]["id"],
        occurred_at="2026-09-13T09:04:00Z",
    )
    assert defect.status_code == 201, defect.text
    blocked_acceptance = _tx(
        client,
        headers,
        application["id"],
        "confirmation",
        transaction_kind="accepted",
        idempotency_key="accept-0001",
        related_transaction_id=ack.json()["transaction"]["id"],
        occurred_at="2026-09-13T09:05:00Z",
        authorized_confirmation="Attorney confirmed the official acknowledgement.",
        document_refs=["document:filing-package", "document:registry-receipt"],
        form_refs=["form:TM-A:2026.1"],
        fee_evidence_refs=["receipt:official-fee"],
        approval_reference="approval:attorney-1",
    )
    assert blocked_acceptance.status_code == 409, blocked_acceptance.text
    assert blocked_acceptance.json()["code"] == "ip_filing_attempt_has_unresolved_defect"
    resubmitted = _tx(
        client,
        headers,
        application["id"],
        "preparation",
        transaction_kind="resubmitted",
        attempt_key="attempt-2",
        idempotency_key="resubmit-0001",
        related_transaction_id=defect.json()["transaction"]["id"],
        occurred_at="2026-09-13T09:06:00Z",
    )
    assert resubmitted.status_code == 201, resubmitted.text
    second_ack = _tx(
        client,
        headers,
        application["id"],
        "confirmation",
        transaction_kind="acknowledgement_received",
        attempt_key="attempt-2",
        idempotency_key="ack-0002",
        related_transaction_id=resubmitted.json()["transaction"]["id"],
        occurred_at="2026-09-13T09:07:00Z",
    )
    assert second_ack.status_code == 201, second_ack.text
    accepted = _tx(
        client,
        headers,
        application["id"],
        "confirmation",
        transaction_kind="accepted",
        attempt_key="attempt-2",
        idempotency_key="accept-0002",
        related_transaction_id=second_ack.json()["transaction"]["id"],
        occurred_at="2026-09-13T09:08:00Z",
        authorized_confirmation="Attorney confirmed the official acknowledgement.",
        document_refs=["document:filing-package", "document:registry-receipt"],
        form_refs=["form:TM-A:2026.1"],
        fee_evidence_refs=["receipt:official-fee"],
        approval_reference="approval:attorney-1",
    )
    assert accepted.status_code == 201, accepted.text
    body = accepted.json()
    assert body["application"]["filing_phase"] == "filed"
    assert body["event"]["event_kind"] == "filing"
    replay = _tx(
        client,
        headers,
        application["id"],
        "confirmation",
        transaction_kind="accepted",
        attempt_key="attempt-2",
        idempotency_key="accept-0002",
        related_transaction_id=second_ack.json()["transaction"]["id"],
        occurred_at="2026-09-13T09:08:00Z",
        authorized_confirmation="Attorney confirmed the official acknowledgement.",
        document_refs=["document:filing-package", "document:registry-receipt"],
        form_refs=["form:TM-A:2026.1"],
        fee_evidence_refs=["receipt:official-fee"],
        approval_reference="approval:attorney-1",
    )
    assert replay.status_code == 201
    assert replay.json()["idempotent_replay"] is True
    listing = client.get(
        f"/api/ip/applications/{application['id']}/filing-transactions", headers=headers
    )
    assert listing.status_code == 200
    assert [row["transaction_kind"] for row in listing.json()["transactions"]] == [
        "submitted",
        "fee_paid",
        "acknowledgement_received",
        "defect_recorded",
        "resubmitted",
        "acknowledgement_received",
        "accepted",
    ]
    with get_session_factory()() as session:
        stored = session.scalar(select(IpFilingTransaction))
        assert stored is not None
        with pytest.raises(DatabaseError, match="append-only"):
            session.execute(
                text(
                    "UPDATE ip_filing_transactions SET external_reference = "
                    "'tampered' WHERE id = :transaction_id"
                ),
                {"transaction_id": stored.id},
            )
            session.commit()
        session.rollback()


def test_filing_writer_enforces_entitlement_and_rollout(client, monkeypatch) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    _docket, application = _application(client, headers)
    request = {
        "expected_lifecycle_version": 0,
        "expected_application_version": 1,
        "transaction_kind": "submitted",
        "attempt_key": "attempt-gated",
        "idempotency_key": "submit-gated",
        "external_reference": "registry:gated",
        "evidence_reference": "document:gated",
        "occurred_at": "2026-09-13T10:00:00Z",
    }
    missing_entitlement = client.post(
        f"/api/ip/applications/{application['id']}/filing-transactions/preparation",
        headers=headers,
        json=request,
    )
    assert missing_entitlement.status_code == 403
    assert missing_entitlement.json()["reason"] == "missing_entitlement"

    _enable_filing(str(bootstrap["company"]["id"]), monkeypatch)
    monkeypatch.setenv("CASEOPS_IP_FILING_OPERATIONS_ENABLED", "false")
    get_settings.cache_clear()
    disabled = client.post(
        f"/api/ip/applications/{application['id']}/filing-transactions/preparation",
        headers=headers,
        json=request,
    )
    assert disabled.status_code == 503
    assert disabled.json()["reason"] == "rollout_disabled"
