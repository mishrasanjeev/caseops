from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from caseops_api.schemas.ip_foreign_associates import (
    IpForeignAssociateCreateRequest,
    IpForeignAssociateEstimateTerms,
    IpForeignAssociateTransactionRequest,
)

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)
NAIVE_NOW = datetime(2026, 8, 26, 12)


def _create_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "docket_id": "docket-1",
        "expected_lifecycle_version": 0,
        "instruction_thread_key": "ASTER-US-2026",
        "client_authority_reference": "Client authority email",
        "target_jurisdiction": "US",
        "outside_counsel_id": "counsel-1",
        "assignment_id": "assignment-1",
        "responsible_membership_id": "membership-1",
        "scope": {
            "source_kind": "application",
            "source_reference": "TM-US-101",
            "filing_kind": "national application",
        },
        "selected_document_refs": ["document-1"],
        "estimate_cost_item_id": "estimate-1",
        "estimate_terms": {},
        "budget_policy_reference": "Budget policy 2026",
        "reason": "Coordinate the foreign filing.",
    }
    payload.update(updates)
    return payload


def _transaction_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "expected_version": 1,
        "expected_lifecycle_version": 0,
        "transaction_kind": "approve",
        "effective_at": NOW,
        "responsible_membership_id": "membership-1",
        "reason": "Record the reviewed transaction.",
    }
    payload.update(updates)
    return payload


def _assert_validation_error(payload: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        IpForeignAssociateTransactionRequest.model_validate(payload)


def test_estimate_tax_terms_require_evidence() -> None:
    with pytest.raises(ValidationError, match="Tax terms require an evidence reference"):
        IpForeignAssociateEstimateTerms(tax_type="VAT", tax_rate_percent=20)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"client_authority_reference": None},
            "Link an accepted client instruction or provide its external authority evidence",
        ),
        (
            {"response_due_at": NAIVE_NOW},
            "Associate response deadline must include a timezone",
        ),
        (
            {"selected_document_refs": ["document-1", "document-1"]},
            "Selected document references must be unique",
        ),
    ],
)
def test_create_contract_rejects_incomplete_authority_deadline_and_documents(
    updates: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        IpForeignAssociateCreateRequest.model_validate(_create_payload(**updates))


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"effective_at": NAIVE_NOW},
            "Associate transaction time must include a timezone",
        ),
        (
            {
                "external_dispatch_reference": "email-1",
                "external_delivery_reference": "receipt-1",
                "external_delivered_at": NAIVE_NOW,
            },
            "External delivery time must include a timezone",
        ),
        (
            {"replacement_response_due_at": NAIVE_NOW},
            "Replacement response deadline must include a timezone",
        ),
        (
            {
                "transaction_kind": "dispatch",
                "dispatch_communication_id": "communication-1",
                "external_dispatch_reference": "email-1",
            },
            "Use a Communication or an external dispatch reference, not both",
        ),
        (
            {"transaction_kind": "dispatch"},
            "Dispatch requires a Communication or external dispatch evidence",
        ),
        (
            {"external_delivery_reference": "receipt-1"},
            "External delivery evidence requires external dispatch evidence",
        ),
        (
            {
                "external_dispatch_reference": "email-1",
                "external_delivered_at": NOW,
            },
            "External delivery time requires its evidence reference",
        ),
        (
            {"transaction_kind": "acknowledge"},
            "Associate acknowledgement requires independent evidence",
        ),
        (
            {
                "transaction_kind": "approve_fee_change",
                "evidence_refs": ["estimate-email-1"],
            },
            "Fee-change approval requires replacement estimate and tax terms",
        ),
        (
            {"transaction_kind": "report_filing"},
            "Filing report requires the foreign filing identifier",
        ),
        (
            {"transaction_kind": "report_filing", "filing_identifier": "USPTO-101"},
            "Filing report requires source and docket-document evidence",
        ),
        (
            {"transaction_kind": "verify_filing_evidence"},
            "Filing evidence verification requires independent evidence",
        ),
        (
            {"transaction_kind": "link_invoice"},
            "Invoice linkage requires canonical cost and spend records",
        ),
    ],
)
def test_transaction_contract_rejects_incomplete_evidence(
    updates: dict[str, object], message: str
) -> None:
    _assert_validation_error(_transaction_payload(**updates), message)


@pytest.mark.parametrize(
    "transaction_kind",
    [
        "record_query",
        "approve_substantive_response",
        "approve_fee_change",
        "refuse",
        "reassign",
    ],
)
def test_correspondence_transactions_require_evidence(transaction_kind: str) -> None:
    updates: dict[str, object] = {"transaction_kind": transaction_kind}
    if transaction_kind == "approve_fee_change":
        updates.update(
            replacement_estimate_cost_item_id="estimate-2",
            replacement_estimate_terms={},
        )
    _assert_validation_error(
        _transaction_payload(**updates),
        f"{transaction_kind} requires correspondence evidence",
    )


def test_reassignment_requires_replacement_associate_and_estimate() -> None:
    _assert_validation_error(
        _transaction_payload(
            transaction_kind="reassign",
            evidence_refs=["refusal-email-1"],
            replacement_estimate_cost_item_id="estimate-2",
            replacement_estimate_terms={},
        ),
        "Reassignment requires an approved associate and replacement estimate terms",
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"evidence_refs": ["evidence-1", "evidence-1"]},
        {"document_refs": ["document-1", "document-1"]},
        {"deadline_refs": ["deadline-1", "deadline-1"]},
        {"evidence_refs": [""]},
    ],
)
def test_transaction_references_must_be_non_blank_and_unique(
    updates: dict[str, object],
) -> None:
    _assert_validation_error(
        _transaction_payload(**updates),
        "references must be non-blank and unique",
    )
