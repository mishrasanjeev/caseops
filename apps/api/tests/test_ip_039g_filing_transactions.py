"""IPLF-039G: filing evidence is transactional, ordered, and fail closed."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, BillingSubscription, IpFilingTransaction
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def _particulars() -> dict:
    return {
        "form_key": "TM-A",
        "form_version": "2026.1",
        "mark_kind": "word",
        "representation": {
            "text": "ASTER",
            "evidence_reference": "document:mark-aster-v1",
        },
        "classes": [{"class_number": 9, "specification": "Downloadable software"}],
        "use_priority": None,
        "parties": [{"role": "applicant", "name": "Aster Applicant LLP"}],
        "agent": None,
        "filing_manifest": [
            {
                "key": "representation",
                "label": "Mark representation",
                "required": True,
                "evidence_reference": "document:mark-aster-v1",
            }
        ],
    }


def _enable_filing(company_id: str, monkeypatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_FILING_OPERATIONS_ENABLED", "true")
    monkeypatch.setenv(
        "CASEOPS_IP_FILING_OPERATIONS_ROLLOUT_EXPIRES_AT",
        "2030-01-01T00:00:00Z",
    )
    get_settings.cache_clear()
    with get_session_factory()() as session:
        subscription = session.scalar(
            select(BillingSubscription)
            .where(BillingSubscription.company_id == company_id)
            .order_by(BillingSubscription.created_at.desc())
        )
        if subscription is None:
            subscription = BillingSubscription(
                company_id=company_id,
                status="manual_active",
                segment="law_firm",
                source="iplf-039g-fixture",
                externally_billable=False,
                entitlement_overrides_json={"ip_filing_operations": True},
            )
            session.add(subscription)
        else:
            overrides = dict(subscription.entitlement_overrides_json or {})
            overrides["ip_filing_operations"] = True
            subscription.entitlement_overrides_json = overrides
        session.commit()


def _application(client, headers: dict[str, str]) -> tuple[dict, dict]:
    docket_response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "ASTER filing transaction",
            "restricted": False,
            "particulars": _particulars(),
        },
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
                "source": "registry acknowledgement fixture",
                "effective_from": "2026-08-30",
                "is_primary": True,
            },
        },
    )
    assert application_response.status_code == 201, application_response.text
    return docket, application_response.json()["application"]


def _transaction(
    client,
    headers: dict[str, str],
    application_id: str,
    *,
    endpoint: str,
    kind: str,
    attempt: str,
    idempotency: str,
    occurred_at: str,
    related: str | None = None,
    **extra,
):
    body = {
        "expected_lifecycle_version": 0,
        "expected_application_version": 1,
        "transaction_kind": kind,
        "attempt_key": attempt,
        "idempotency_key": idempotency,
        "related_transaction_id": related,
        "external_reference": f"registry:{idempotency}",
        "evidence_reference": f"document:{idempotency}",
        "occurred_at": occurred_at,
        "details": {"fixture": "IPLF-UJ-32"},
        **extra,
    }
    return client.post(
        f"/api/ip/applications/{application_id}/filing-transactions/{endpoint}",
        headers=headers,
        json=body,
    )


def test_uj32_transaction_chain_keeps_payment_and_defect_pending_until_acceptance(
    client,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    _enable_filing(company_id, monkeypatch)
    docket, application = _application(client, headers)

    direct_phase = client.patch(
        f"/api/ip/applications/{application['id']}/filing-phase",
        headers=headers,
        json={"expected_version": 1, "filing_phase": "filed"},
    )
    assert direct_phase.status_code == 409
    assert direct_phase.json()["code"] == "ip_filing_transaction_required"

    direct_event = client.post(
        f"/api/ip/dockets/{docket['id']}/events",
        headers=headers,
        json={
            "expected_lifecycle_version": 0,
            "expected_application_version": 1,
            "application_id": application["id"],
            "event_kind": "filing",
            "source": "manual",
            "effective_at": "2026-08-30T09:00:00Z",
            "responsible_membership_id": bootstrap["membership"]["id"],
            "reason": "Recorded by the filing operator.",
            "evidence_refs": ["document:receipt"],
            "document_refs": ["document:package"],
            "payload": {
                "form_refs": ["form:TM-A:2026.1"],
                "fee_evidence_refs": ["cost:official-fee"],
                "approval_refs": ["approval:attorney"],
            },
        },
    )
    assert direct_event.status_code == 409
    assert direct_event.json()["code"] == "ip_filing_transaction_required"

    submitted = _transaction(
        client,
        headers,
        application["id"],
        endpoint="preparation",
        kind="submitted",
        attempt="attempt-1",
        idempotency="submit-attempt-1",
        occurred_at="2026-08-30T09:05:00Z",
    )
    assert submitted.status_code == 201, submitted.text
    submission_id = submitted.json()["transaction"]["id"]

    duplicate_submission = _transaction(
        client,
        headers,
        application["id"],
        endpoint="preparation",
        kind="submitted",
        attempt="attempt-1",
        idempotency="submit-attempt-1-duplicate",
        occurred_at="2026-08-30T09:05:30Z",
    )
    assert duplicate_submission.status_code == 409
    assert duplicate_submission.json()["code"] == "ip_filing_attempt_already_submitted"

    paid = _transaction(
        client,
        headers,
        application["id"],
        endpoint="preparation",
        kind="fee_paid",
        attempt="attempt-1",
        idempotency="payment-attempt-1",
        occurred_at="2026-08-30T09:06:00Z",
        related=submission_id,
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["application"]["filing_phase"] == "pre_filing"
    assert paid.json()["event"] is None

    acknowledged = _transaction(
        client,
        headers,
        application["id"],
        endpoint="confirmation",
        kind="acknowledgement_received",
        attempt="attempt-1",
        idempotency="ack-attempt-1",
        occurred_at="2026-08-30T09:07:00Z",
        related=submission_id,
    )
    assert acknowledged.status_code == 201, acknowledged.text
    acknowledgement_id = acknowledged.json()["transaction"]["id"]
    assert acknowledged.json()["application"]["filing_phase"] == "pre_filing"

    defect = _transaction(
        client,
        headers,
        application["id"],
        endpoint="confirmation",
        kind="defect_recorded",
        attempt="attempt-1",
        idempotency="defect-attempt-1",
        occurred_at="2026-08-30T09:08:00Z",
        related=acknowledgement_id,
    )
    assert defect.status_code == 201, defect.text
    defect_id = defect.json()["transaction"]["id"]

    blocked_acceptance = _transaction(
        client,
        headers,
        application["id"],
        endpoint="confirmation",
        kind="accepted",
        attempt="attempt-1",
        idempotency="accept-attempt-1",
        occurred_at="2026-08-30T09:09:00Z",
        related=acknowledgement_id,
        authorized_confirmation="Attorney confirmed the official acknowledgement.",
        document_refs=["document:filing-package", "document:registry-ack"],
        form_refs=["form:TM-A:2026.1"],
        fee_evidence_refs=["cost:official-fee"],
        approval_reference="approval:attorney-039g",
    )
    assert blocked_acceptance.status_code == 409
    assert blocked_acceptance.json()["code"] == "ip_filing_attempt_has_unresolved_defect"

    resubmitted = _transaction(
        client,
        headers,
        application["id"],
        endpoint="preparation",
        kind="resubmitted",
        attempt="attempt-2",
        idempotency="submit-attempt-2",
        occurred_at="2026-08-30T09:10:00Z",
        related=defect_id,
    )
    assert resubmitted.status_code == 201, resubmitted.text
    resubmission_id = resubmitted.json()["transaction"]["id"]
    second_ack = _transaction(
        client,
        headers,
        application["id"],
        endpoint="confirmation",
        kind="acknowledgement_received",
        attempt="attempt-2",
        idempotency="ack-attempt-2",
        occurred_at="2026-08-30T09:11:00Z",
        related=resubmission_id,
    )
    assert second_ack.status_code == 201, second_ack.text
    second_ack_id = second_ack.json()["transaction"]["id"]
    acceptance_arguments = {
        "endpoint": "confirmation",
        "kind": "accepted",
        "attempt": "attempt-2",
        "idempotency": "accept-attempt-2",
        "occurred_at": "2026-08-30T09:12:00Z",
        "related": second_ack_id,
        "authorized_confirmation": "Attorney confirmed the official acknowledgement.",
        "document_refs": ["document:filing-package-v2", "document:registry-ack-v2"],
        "form_refs": ["form:TM-A:2026.1"],
        "fee_evidence_refs": ["cost:official-fee-v2"],
        "approval_reference": "approval:attorney-039g-v2",
    }
    accepted = _transaction(
        client,
        headers,
        application["id"],
        **acceptance_arguments,
    )
    assert accepted.status_code == 201, accepted.text
    accepted_body = accepted.json()
    assert accepted_body["application"]["filing_phase"] == "filed"
    assert accepted_body["application"]["version"] == 2
    assert accepted_body["event"]["event_kind"] == "filing"
    assert accepted_body["transaction"]["filing_event_id"] == accepted_body["event"]["id"]
    assert (
        accepted_body["event"]["payload_json"]["filing_transaction_id"]
        == (accepted_body["transaction"]["id"])
    )

    replay = _transaction(
        client,
        headers,
        application["id"],
        **acceptance_arguments,
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["transaction"]["id"] == accepted_body["transaction"]["id"]

    conflicting_replay = _transaction(
        client,
        headers,
        application["id"],
        **acceptance_arguments,
        external_reference="registry:conflicting-acceptance",
    )
    assert conflicting_replay.status_code == 409
    assert conflicting_replay.json()["code"] == "ip_filing_idempotency_conflict"

    listing = client.get(
        f"/api/ip/applications/{application['id']}/filing-transactions",
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
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
        actions = set(
            session.scalars(select(AuditEvent.action).where(AuditEvent.company_id == company_id))
        )
        assert {"ip_filing.transaction_recorded", "ip_docket.event_appended"}.issubset(actions)
        stored = session.get(IpFilingTransaction, accepted_body["transaction"]["id"])
        assert stored is not None
        try:
            session.execute(
                text(
                    "UPDATE ip_filing_transactions SET external_reference = "
                    "'tampered' WHERE id = :transaction_id"
                ),
                {"transaction_id": stored.id},
            )
            session.commit()
            raise AssertionError("append-only filing evidence accepted an update")
        except DatabaseError as exc:
            session.rollback()
            assert "append-only" in str(exc).lower()


def test_filing_writer_enforces_entitlement_and_rollout(client, monkeypatch) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    _docket, application = _application(client, headers)
    request = {
        "expected_lifecycle_version": 0,
        "expected_application_version": 1,
        "transaction_kind": "submitted",
        "attempt_key": "attempt-gated",
        "idempotency_key": "submit-attempt-gated",
        "external_reference": "registry:gated",
        "evidence_reference": "document:gated",
        "occurred_at": "2026-08-30T10:00:00Z",
    }
    missing_entitlement = client.post(
        f"/api/ip/applications/{application['id']}/filing-transactions/preparation",
        headers=headers,
        json=request,
    )
    assert missing_entitlement.status_code == 403
    assert missing_entitlement.json()["reason"] == "missing_entitlement"

    _enable_filing(company_id, monkeypatch)
    monkeypatch.setenv("CASEOPS_IP_FILING_OPERATIONS_ENABLED", "false")
    get_settings.cache_clear()
    disabled = client.post(
        f"/api/ip/applications/{application['id']}/filing-transactions/preparation",
        headers=headers,
        json=request,
    )
    assert disabled.status_code == 503
    assert disabled.json()["reason"] == "rollout_disabled"
