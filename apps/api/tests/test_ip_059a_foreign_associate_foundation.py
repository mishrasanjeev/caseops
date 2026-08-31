from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    AuditEvent,
    Communication,
    CompanyMembership,
    IpCostItem,
    IpDocketEvent,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpForeignAssociateInstruction,
    Matter,
    MatterOutsideCounselAssignment,
    MembershipRole,
    OutsideCounsel,
    OutsideCounselSpendRecord,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _particulars


def _lifecycle_version(client: TestClient, headers: dict[str, str], docket_id: str) -> int:
    response = client.get(f"/api/ip/dockets/{docket_id}", headers=headers)
    assert response.status_code == 200, response.text
    return int(response.json()["lifecycle_version"])


def _matter_and_docket(
    client: TestClient,
    *,
    headers: dict[str, str],
    company_id: str,
    membership_id: str,
) -> tuple[Matter, dict]:
    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            assignee_membership_id=membership_id,
            responsible_lawyer_membership_id=membership_id,
            title="ASTER US filing",
            matter_code="IP-US-0001",
            matter_type="Trademark filing",
            practice_area="Intellectual Property",
            forum_level="Foreign Registry",
        )
        session.add(matter)
        session.commit()
        session.refresh(matter)
        session.expunge(matter)
    response = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "ASTER US filing",
            "matter_id": matter.id,
            "restricted": False,
            "particulars": _particulars("ASTER"),
        },
    )
    assert response.status_code == 201, response.text
    return matter, response.json()


def _foundation_records(
    client: TestClient,
    *,
    headers: dict[str, str],
    company_id: str,
    membership_id: str,
    matter: Matter,
    docket_id: str,
) -> dict[str, str]:
    seeded = client.post("/api/ip/document-taxonomy/seed", headers=headers)
    assert seeded.status_code == 200, seeded.text
    with get_session_factory()() as session:
        taxonomy = session.scalar(
            select(IpDocumentTaxonomyEntry).where(
                IpDocumentTaxonomyEntry.company_id == company_id,
                IpDocumentTaxonomyEntry.key == "evidence",
            )
        )
        assert taxonomy is not None
        documents: list[IpDocument] = []
        for suffix, privileged in (("filing", False), ("strategy", True)):
            document = IpDocument(
                company_id=company_id,
                taxonomy_entry_id=taxonomy.id,
                title=f"ASTER {suffix}",
                is_privileged=privileged,
                created_by_membership_id=membership_id,
            )
            session.add(document)
            session.flush()
            version = IpDocumentVersion(
                company_id=company_id,
                document_id=document.id,
                version=1,
                original_filename=f"{suffix}.pdf",
                display_name=f"ASTER_{suffix}.pdf",
                storage_key=f"ip/{company_id}/{document.id}/1",
                content_type="application/pdf",
                size_bytes=256,
                sha256_hex=("a" if privileged else "b") * 64,
                uploaded_by_membership_id=membership_id,
            )
            session.add(version)
            session.flush()
            session.add(
                IpDocumentLink(
                    company_id=company_id,
                    document_id=document.id,
                    version_id=version.id,
                    target_type="docket",
                    target_id=docket_id,
                    docket_id=docket_id,
                    created_by_membership_id=membership_id,
                )
            )
            documents.append(document)

        counsel = OutsideCounsel(
            company_id=company_id,
            name="Liberty IP LLP",
            primary_contact_email="filings@liberty-ip.example",
            jurisdictions_json='["US"]',
            practice_areas_json='["Trademark"]',
            panel_status="preferred",
        )
        replacement = OutsideCounsel(
            company_id=company_id,
            name="Hudson Marks LLP",
            primary_contact_email="docket@hudson-marks.example",
            jurisdictions_json='["US"]',
            practice_areas_json='["Trademark"]',
            panel_status="active",
        )
        session.add_all([counsel, replacement])
        session.flush()
        assignment = MatterOutsideCounselAssignment(
            company_id=company_id,
            matter_id=matter.id,
            counsel_id=counsel.id,
            assigned_by_membership_id=membership_id,
            role_summary="US trademark filing associate",
            budget_amount_minor=250000,
            currency="USD",
            status="approved",
        )
        replacement_assignment = MatterOutsideCounselAssignment(
            company_id=company_id,
            matter_id=matter.id,
            counsel_id=replacement.id,
            assigned_by_membership_id=membership_id,
            role_summary="Replacement US filing associate",
            budget_amount_minor=250000,
            currency="USD",
            status="approved",
        )
        estimate = IpCostItem(
            company_id=company_id,
            docket_id=docket_id,
            matter_id=matter.id,
            category="associate_fee",
            description="US filing estimate",
            amount_minor=250000,
            currency="USD",
            billable=True,
            cost_nature="estimate",
            evidence_reference="Liberty estimate dated 25 August 2026",
            reconciliation_status="estimate",
            created_by_membership_id=membership_id,
        )
        revised_estimate = IpCostItem(
            company_id=company_id,
            docket_id=docket_id,
            matter_id=matter.id,
            category="associate_fee",
            description="Revised US filing estimate",
            amount_minor=265000,
            currency="USD",
            billable=True,
            cost_nature="estimate",
            evidence_reference="Revised Liberty estimate dated 26 August 2026",
            reconciliation_status="estimate",
            created_by_membership_id=membership_id,
        )
        actual = IpCostItem(
            company_id=company_id,
            docket_id=docket_id,
            matter_id=matter.id,
            category="associate_fee",
            description="US filing actual",
            amount_minor=265000,
            currency="USD",
            billable=True,
            cost_nature="actual",
            evidence_reference="Liberty invoice INV-101",
            billing_link_type="invoice",
            billing_link_id="client-invoice-101",
            reconciliation_status="unlinked",
            created_by_membership_id=membership_id,
        )
        communication = Communication(
            company_id=company_id,
            matter_id=matter.id,
            direction="outbound",
            channel="email",
            subject="ASTER US filing instruction",
            body="Approved filing instruction and selected documents.",
            recipient_email="filings@liberty-ip.example",
            status="delivered",
            occurred_at=datetime.now(UTC),
            delivered_at=datetime.now(UTC),
            external_message_id="associate-dispatch-101",
            created_by_membership_id=membership_id,
        )
        wrong_recipient_communication = Communication(
            company_id=company_id,
            matter_id=matter.id,
            direction="outbound",
            channel="email",
            subject="ASTER US filing instruction",
            body="Misdirected test instruction.",
            recipient_email="wrong-recipient@example.com",
            status="delivered",
            occurred_at=datetime.now(UTC),
            delivered_at=datetime.now(UTC),
            external_message_id="associate-dispatch-wrong-recipient",
            created_by_membership_id=membership_id,
        )
        pending_communication = Communication(
            company_id=company_id,
            matter_id=matter.id,
            direction="outbound",
            channel="email",
            subject="ASTER US filing instruction",
            body="Instruction awaiting dispatch.",
            recipient_email="filings@liberty-ip.example",
            status="queued",
            occurred_at=datetime.now(UTC),
            created_by_membership_id=membership_id,
        )
        session.add_all(
            [
                assignment,
                replacement_assignment,
                estimate,
                revised_estimate,
                actual,
                communication,
                wrong_recipient_communication,
            ]
        )
        session.flush()
        spend = OutsideCounselSpendRecord(
            company_id=company_id,
            matter_id=matter.id,
            counsel_id=counsel.id,
            assignment_id=assignment.id,
            recorded_by_membership_id=membership_id,
            invoice_reference="INV-101",
            description="ASTER US filing",
            currency="USD",
            amount_minor=265000,
            status="submitted",
        )
        session.add_all([spend, pending_communication])
        session.commit()
        return {
            "filing_document_id": documents[0].id,
            "privileged_document_id": documents[1].id,
            "counsel_id": counsel.id,
            "replacement_counsel_id": replacement.id,
            "assignment_id": assignment.id,
            "replacement_assignment_id": replacement_assignment.id,
            "estimate_id": estimate.id,
            "revised_estimate_id": revised_estimate.id,
            "actual_id": actual.id,
            "communication_id": communication.id,
            "wrong_recipient_communication_id": wrong_recipient_communication.id,
            "pending_communication_id": pending_communication.id,
            "spend_id": spend.id,
        }


def _create_payload(
    *, docket_id: str, membership_id: str, records: dict[str, str], thread: str
) -> dict:
    return {
        "docket_id": docket_id,
        "expected_lifecycle_version": 0,
        "instruction_thread_key": thread,
        "client_authority_reference": "Client email authority CLIENT-AUTH-101",
        "target_jurisdiction": "US",
        "outside_counsel_id": records["counsel_id"],
        "assignment_id": records["assignment_id"],
        "responsible_membership_id": membership_id,
        "scope": {
            "source_kind": "application",
            "source_reference": "TM-US-DRAFT-101",
            "filing_kind": "national trademark application",
            "scoped_fields": {"classes": [9, 42], "mark": "ASTER"},
        },
        "selected_document_refs": [
            records["filing_document_id"],
            records["privileged_document_id"],
        ],
        "include_privileged_documents": True,
        "estimate_cost_item_id": records["estimate_id"],
        "estimate_terms": {
            "tax_type": "sales_tax",
            "tax_rate_percent": 8.25,
            "tax_inclusive": False,
            "tax_evidence_reference": "Associate estimate tax schedule",
            "assumptions": ["One class included; additional classes charged separately"],
        },
        "budget_policy_reference": "Foreign filing budget policy BP-2026-04",
        "response_due_at": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
        "reason": "Create the approved-scope foreign filing instruction.",
    }


def _transaction(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket_id: str,
    instruction_id: str,
    version: int,
    membership_id: str,
    kind: str,
    extra: dict | None = None,
):
    payload = {
        "expected_version": version,
        "expected_lifecycle_version": _lifecycle_version(client, headers, docket_id),
        "transaction_kind": kind,
        "effective_at": datetime.now(UTC).isoformat(),
        "responsible_membership_id": membership_id,
        "reason": f"Record the {kind.replace('_', ' ')} transaction.",
    }
    payload.update(extra or {})
    return client.post(
        f"/api/ip/foreign-associate-instructions/{instruction_id}/transactions",
        headers=headers,
        json=payload,
    )


def _supersede_cost_item(
    client: TestClient,
    *,
    headers: dict[str, str],
    docket_id: str,
    source_cost_item_id: str,
    replacement: dict[str, object],
    reason: str,
    evidence_reference: str,
) -> str:
    """Replace immutable evidence through the supported correction contract."""

    response = client.post(
        f"/api/ip/dockets/{docket_id}/cost-items/{source_cost_item_id}/corrections",
        headers=headers,
        json={
            "action": "supersede",
            "reason": reason,
            "evidence_reference": evidence_reference,
            "replacement": replacement,
        },
    )
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["cost_items"]}
    source = rows[source_cost_item_id]
    assert source["lineage_status"] == "superseded"
    replacement_id = source["replacement_cost_item_id"]
    assert replacement_id is not None
    assert rows[replacement_id]["lineage_status"] == "active"
    assert rows[replacement_id]["corrects_cost_item_id"] == source_cost_item_id
    return str(replacement_id)


def test_foreign_associate_contract_separates_delivery_ack_and_evidence(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter, docket = _matter_and_docket(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
    )
    records = _foundation_records(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        matter=matter,
        docket_id=docket["id"],
    )
    payload = _create_payload(
        docket_id=docket["id"],
        membership_id=membership_id,
        records=records,
        thread="ASTER-US-2026",
    )

    without_explicit_privilege = {**payload, "include_privileged_documents": False}
    excluded = client.post(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        json=without_explicit_privilege,
    )
    assert excluded.status_code == 422
    assert "explicitly selected" in excluded.text

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = MembershipRole.MEMBER
        session.commit()
    writer_cannot_include_privileged = client.post(
        "/api/ip/foreign-associate-instructions", headers=headers, json=payload
    )
    assert writer_cannot_include_privileged.status_code == 403
    assert "ip:approve" in writer_cannot_include_privileged.text
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        membership.role = MembershipRole.OWNER
        estimate = session.get(IpCostItem, records["estimate_id"])
        assignment = session.get(
            MatterOutsideCounselAssignment, records["assignment_id"]
        )
        assert estimate is not None and assignment is not None
        assignment.budget_amount_minor = None
        session.commit()

    missing_assignment_budget = client.post(
        "/api/ip/foreign-associate-instructions", headers=headers, json=payload
    )
    assert missing_assignment_budget.status_code == 422
    assert "budget ceiling" in missing_assignment_budget.text
    with get_session_factory()() as session:
        assignment = session.get(
            MatterOutsideCounselAssignment, records["assignment_id"]
        )
        assert assignment is not None
        assignment.budget_amount_minor = 250000
        session.commit()

    over_budget_estimate_id = _supersede_cost_item(
        client,
        headers=headers,
        docket_id=docket["id"],
        source_cost_item_id=records["estimate_id"],
        reason="The associate supplied a revised amount above the approved budget.",
        evidence_reference="correction:associate-estimate-over-budget",
        replacement={
            "category": "associate_fee",
            "description": "US filing estimate above the approved budget",
            "amount_minor": 250001,
            "currency": "USD",
            "billable": True,
            "cost_nature": "estimate",
            "evidence_reference": "Liberty over-budget estimate dated 25 August 2026",
        },
    )
    over_budget_payload = {
        **payload,
        "estimate_cost_item_id": over_budget_estimate_id,
    }

    over_budget = client.post(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        json=over_budget_payload,
    )
    assert over_budget.status_code == 422
    assert "budget" in over_budget.text

    corrected_estimate_id = _supersede_cost_item(
        client,
        headers=headers,
        docket_id=docket["id"],
        source_cost_item_id=over_budget_estimate_id,
        reason="The associate corrected the estimate back to the approved amount.",
        evidence_reference="correction:associate-estimate-approved-amount",
        replacement={
            "category": "associate_fee",
            "description": "Corrected US filing estimate",
            "amount_minor": 250000,
            "currency": "USD",
            "billable": True,
            "cost_nature": "estimate",
            "evidence_reference": "Corrected Liberty estimate dated 25 August 2026",
        },
    )
    payload = {**payload, "estimate_cost_item_id": corrected_estimate_id}

    created = client.post(
        "/api/ip/foreign-associate-instructions", headers=headers, json=payload
    )
    assert created.status_code == 201, created.text
    instruction = created.json()
    assert instruction["status"] == "draft"
    assert instruction["privileged_document_refs_json"] == [
        records["privileged_document_id"]
    ]

    with get_session_factory()() as session:
        counsel = session.get(OutsideCounsel, records["counsel_id"])
        assert counsel is not None
        counsel.panel_status = "inactive"
        session.commit()
    stale_panel_approval = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=1,
        membership_id=membership_id,
        kind="approve",
    )
    assert stale_panel_approval.status_code == 422
    assert "active panel" in stale_panel_approval.text
    with get_session_factory()() as session:
        counsel = session.get(OutsideCounsel, records["counsel_id"])
        assert counsel is not None
        counsel.panel_status = "preferred"
        session.commit()

    approved = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=1,
        membership_id=membership_id,
        kind="approve",
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["instruction"]["status"] == "approved"

    active_dispatch_estimate_id = _supersede_cost_item(
        client,
        headers=headers,
        docket_id=docket["id"],
        source_cost_item_id=corrected_estimate_id,
        reason="The associate corrected its approved estimate before dispatch.",
        evidence_reference="correction:associate-estimate-pre-dispatch",
        replacement={
            "category": "associate_fee",
            "description": "Current US filing estimate for dispatch",
            "amount_minor": 250000,
            "currency": "USD",
            "billable": True,
            "cost_nature": "estimate",
            "evidence_reference": "Liberty estimate dated 27 August 2026",
        },
    )
    stale_estimate_dispatch = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=2,
        membership_id=membership_id,
        kind="dispatch",
        extra={"dispatch_communication_id": records["communication_id"]},
    )
    assert stale_estimate_dispatch.status_code == 422
    assert "estimate cost item is missing, inactive" in stale_estimate_dispatch.text
    current_estimate = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=2,
        membership_id=membership_id,
        kind="approve_fee_change",
        extra={
            "replacement_estimate_cost_item_id": active_dispatch_estimate_id,
            "replacement_estimate_terms": {
                "tax_type": "sales_tax",
                "tax_rate_percent": 8.25,
                "tax_inclusive": False,
                "tax_evidence_reference": "Current associate tax schedule",
                "assumptions": ["One class included"],
            },
            "evidence_refs": ["Corrected estimate email"],
        },
    )
    assert current_estimate.status_code == 201, current_estimate.text
    assert current_estimate.json()["instruction"]["estimate_cost_item_id"] == (
        active_dispatch_estimate_id
    )

    stale = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=1,
        membership_id=membership_id,
        kind="dispatch",
        extra={"dispatch_communication_id": records["communication_id"]},
    )
    assert stale.status_code == 409
    assert "version changed" in stale.text

    pending_dispatch = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=3,
        membership_id=membership_id,
        kind="dispatch",
        extra={"dispatch_communication_id": records["pending_communication_id"]},
    )
    assert pending_dispatch.status_code == 422
    assert "sent or manual-dispatch state" in pending_dispatch.text
    with get_session_factory()() as session:
        pending = session.get(Communication, records["pending_communication_id"])
        assert pending is not None
        pending.status = "failed"
        session.commit()
    failed_dispatch = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=3,
        membership_id=membership_id,
        kind="dispatch",
        extra={"dispatch_communication_id": records["pending_communication_id"]},
    )
    assert failed_dispatch.status_code == 422
    assert "sent or manual-dispatch state" in failed_dispatch.text

    wrong_recipient = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=3,
        membership_id=membership_id,
        kind="dispatch",
        extra={
            "dispatch_communication_id": records["wrong_recipient_communication_id"]
        },
    )
    assert wrong_recipient.status_code == 422
    assert "recipient" in wrong_recipient.text

    dispatched = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=3,
        membership_id=membership_id,
        kind="dispatch",
        extra={"dispatch_communication_id": records["communication_id"]},
    )
    assert dispatched.status_code == 201, dispatched.text
    workspace = client.get(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_body = workspace.json()
    assert workspace_body["delivery_status"] == "delivered"
    assert workspace_body["acknowledgement_status"] == "outstanding"
    assert workspace_body["docket"]["id"] == docket["id"]
    assert {document["id"] for document in workspace_body["documents"]} == {
        records["filing_document_id"],
        records["privileged_document_id"],
    }

    outstanding = client.get(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        params={"outstanding_response": True},
    )
    assert outstanding.status_code == 200
    assert [row["id"] for row in outstanding.json()["items"]] == [instruction["id"]]

    acknowledged = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=4,
        membership_id=membership_id,
        kind="acknowledge",
        extra={
            "acknowledgement_reference": "Associate reply ACK-101",
            "evidence_refs": ["Associate reply ACK-101"],
        },
    )
    assert acknowledged.status_code == 201, acknowledged.text
    assert acknowledged.json()["event"]["payload_json"]["delivery_is_acknowledgement"] is False

    fee_change = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=5,
        membership_id=membership_id,
        kind="approve_fee_change",
        extra={
            "replacement_estimate_cost_item_id": records["revised_estimate_id"],
            "replacement_estimate_terms": {
                "tax_type": "sales_tax",
                "tax_rate_percent": 9,
                "tax_inclusive": False,
                "tax_evidence_reference": "Revised associate tax schedule",
                "assumptions": ["Two classes included"],
            },
            "evidence_refs": ["Revised estimate email"],
        },
    )
    assert fee_change.status_code == 201, fee_change.text
    assert fee_change.json()["instruction"]["estimate_cost_item_id"] == records[
        "revised_estimate_id"
    ]
    assert fee_change.json()["instruction"]["estimate_terms_json"]["tax_rate_percent"] == 9

    filed = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=6,
        membership_id=membership_id,
        kind="report_filing",
        extra={
            "filing_identifier": "USPTO-97865432",
            "evidence_refs": ["Associate filing report FR-101"],
            "document_refs": [records["filing_document_id"]],
        },
    )
    assert filed.status_code == 201, filed.text
    missing = client.get(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        params={"missing_filing_evidence": True},
    )
    assert missing.status_code == 200
    assert missing.json()["total"] == 1

    same_evidence = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=7,
        membership_id=membership_id,
        kind="verify_filing_evidence",
        extra={"evidence_refs": ["Associate filing report FR-101"]},
    )
    assert same_evidence.status_code == 422
    assert "independent" in same_evidence.text
    verified = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=7,
        membership_id=membership_id,
        kind="verify_filing_evidence",
        extra={"evidence_refs": ["USPTO TSDR receipt snapshot TS-101"]},
    )
    assert verified.status_code == 201, verified.text

    mismatched_actual_id = _supersede_cost_item(
        client,
        headers=headers,
        docket_id=docket["id"],
        source_cost_item_id=records["actual_id"],
        reason="The first invoice transcription contained an incorrect amount.",
        evidence_reference="correction:associate-invoice-mismatch",
        replacement={
            "category": "associate_fee",
            "description": "US filing actual with transcribed mismatch",
            "amount_minor": 1,
            "currency": "USD",
            "billable": True,
            "cost_nature": "actual",
            "evidence_reference": "Liberty invoice INV-101 mismatched transcription",
            "billing_link_type": "invoice",
            "billing_link_id": "client-invoice-101",
        },
    )
    mismatched_invoice = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=8,
        membership_id=membership_id,
        kind="link_invoice",
        extra={
            "actual_cost_item_id": mismatched_actual_id,
            "spend_record_id": records["spend_id"],
            "evidence_refs": ["Associate invoice INV-101"],
        },
    )
    assert mismatched_invoice.status_code == 422
    assert "reconcile" in mismatched_invoice.text

    corrected_actual_id = _supersede_cost_item(
        client,
        headers=headers,
        docket_id=docket["id"],
        source_cost_item_id=mismatched_actual_id,
        reason="The associate invoice was re-entered from the retained original.",
        evidence_reference="correction:associate-invoice-restored",
        replacement={
            "category": "associate_fee",
            "description": "Corrected US filing actual",
            "amount_minor": 265000,
            "currency": "USD",
            "billable": True,
            "cost_nature": "actual",
            "evidence_reference": "Liberty invoice INV-101 corrected transcription",
            "billing_link_type": "invoice",
            "billing_link_id": "client-invoice-101",
        },
    )
    records["actual_id"] = corrected_actual_id

    invoiced = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=8,
        membership_id=membership_id,
        kind="link_invoice",
        extra={
            "actual_cost_item_id": records["actual_id"],
            "spend_record_id": records["spend_id"],
            "evidence_refs": ["Associate invoice INV-101"],
        },
    )
    assert invoiced.status_code == 201, invoiced.text
    unpaid = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=9,
        membership_id=membership_id,
        kind="complete",
    )
    assert unpaid.status_code == 422
    assert "not paid" in unpaid.text
    with get_session_factory()() as session:
        spend = session.get(OutsideCounselSpendRecord, records["spend_id"])
        actual = session.get(IpCostItem, records["actual_id"])
        assert spend is not None and actual is not None
        spend.status = "paid"
        spend.approved_amount_minor = spend.amount_minor
        spend.paid_on = datetime.now(UTC).date()
        actual.reconciliation_status = "matched"
        session.commit()
    active_actual_id = _supersede_cost_item(
        client,
        headers=headers,
        docket_id=docket["id"],
        source_cost_item_id=records["actual_id"],
        reason="The linked invoice actual was corrected before completion.",
        evidence_reference="correction:associate-invoice-pre-completion",
        replacement={
            "category": "associate_fee",
            "description": "Current US filing actual",
            "amount_minor": 265000,
            "currency": "USD",
            "billable": True,
            "cost_nature": "actual",
            "evidence_reference": "Liberty corrected invoice INV-101",
            "billing_link_type": "invoice",
            "billing_link_id": "client-invoice-101",
        },
    )
    stale_actual_completion = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=9,
        membership_id=membership_id,
        kind="complete",
    )
    assert stale_actual_completion.status_code == 422
    assert "actual cost item is missing, inactive" in stale_actual_completion.text
    relinked_actual = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=9,
        membership_id=membership_id,
        kind="link_invoice",
        extra={
            "actual_cost_item_id": active_actual_id,
            "spend_record_id": records["spend_id"],
            "evidence_refs": ["Corrected associate invoice INV-101"],
        },
    )
    assert relinked_actual.status_code == 201, relinked_actual.text
    with get_session_factory()() as session:
        active_actual = session.get(IpCostItem, active_actual_id)
        assert active_actual is not None
        active_actual.reconciliation_status = "matched"
        session.commit()
    completed = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=10,
        membership_id=membership_id,
        kind="complete",
    )
    assert completed.status_code == 201, completed.text
    assert completed.json()["instruction"]["status"] == "completed"

    other_bootstrap = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Beacon Legal LLP",
            "company_slug": "beacon-legal",
            "company_type": "law_firm",
            "owner_full_name": "Beacon Owner",
            "owner_email": "owner@beaconlegal.example",
            "owner_password": "FoundersPass123!",
        },
    )
    assert other_bootstrap.status_code == 200, other_bootstrap.text
    other_headers = auth_headers(str(other_bootstrap.json()["access_token"]))
    cross_tenant_detail = client.get(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}",
        headers=other_headers,
    )
    assert cross_tenant_detail.status_code == 404
    cross_tenant_list = client.get(
        "/api/ip/foreign-associate-instructions",
        headers=other_headers,
    )
    assert cross_tenant_list.status_code == 200
    assert cross_tenant_list.json()["items"] == []

    with get_session_factory()() as session:
        stored = session.get(IpForeignAssociateInstruction, instruction["id"])
        assert stored is not None and stored.row_version == 11
        events = list(
            session.scalars(
                select(IpDocketEvent).where(
                    IpDocketEvent.foreign_associate_instruction_id == instruction["id"]
                )
            )
        )
        assert len(events) == 11
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.target_id == instruction["id"],
                )
            )
        )
        assert {event.action for event in audits} == {
            "ip_foreign_associate_instruction.created",
            "ip_foreign_associate_instruction.transaction_recorded",
        }


def test_foreign_associate_refusal_reassignment_preserves_versioned_history(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter, docket = _matter_and_docket(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
    )
    records = _foundation_records(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        matter=matter,
        docket_id=docket["id"],
    )
    payload = _create_payload(
        docket_id=docket["id"],
        membership_id=membership_id,
        records=records,
        thread="ASTER-US-REFUSAL-2026",
    )
    created = client.post(
        "/api/ip/foreign-associate-instructions", headers=headers, json=payload
    )
    assert created.status_code == 201, created.text
    instruction_id = created.json()["id"]
    for version, kind, extra in (
        (1, "approve", {}),
        (2, "dispatch", {"dispatch_communication_id": records["communication_id"]}),
        (3, "refuse", {"evidence_refs": ["Conflict refusal email REF-101"]}),
    ):
        response = _transaction(
            client,
            headers=headers,
            docket_id=docket["id"],
            instruction_id=instruction_id,
            version=version,
            membership_id=membership_id,
            kind=kind,
            extra=extra,
        )
        assert response.status_code == 201, response.text
    reassigned = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction_id,
        version=4,
        membership_id=membership_id,
        kind="reassign",
        extra={
            "replacement_outside_counsel_id": records["replacement_counsel_id"],
            "replacement_assignment_id": records["replacement_assignment_id"],
            "replacement_estimate_cost_item_id": records["revised_estimate_id"],
            "replacement_estimate_terms": {
                "tax_type": "sales_tax",
                "tax_rate_percent": 9,
                "tax_inclusive": False,
                "tax_evidence_reference": "Hudson estimate tax schedule",
                "assumptions": ["Replacement counsel estimate"],
            },
            "replacement_response_due_at": (
                datetime.now(UTC) + timedelta(days=2)
            ).isoformat(),
            "evidence_refs": ["Conflict refusal email REF-101"],
        },
    )
    assert reassigned.status_code == 201, reassigned.text
    body = reassigned.json()
    assert body["instruction"]["status"] == "superseded"
    assert body["successor"]["status"] == "approved"
    assert body["successor"]["instruction_version"] == 2
    assert body["successor"]["supersedes_instruction_id"] == instruction_id
    assert body["successor"]["outside_counsel_id"] == records["replacement_counsel_id"]
    assert body["successor"]["selected_document_refs_json"] == sorted(
        [records["filing_document_id"], records["privileged_document_id"]]
    )


def test_terminal_docket_neutralizes_instruction_without_reopen_resurrection(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter, docket = _matter_and_docket(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
    )
    records = _foundation_records(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        matter=matter,
        docket_id=docket["id"],
    )
    created = client.post(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        json=_create_payload(
            docket_id=docket["id"],
            membership_id=membership_id,
            records=records,
            thread="ASTER-US-LIFECYCLE-2026",
        ),
    )
    assert created.status_code == 201, created.text
    instruction_id = created.json()["id"]
    approved = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction_id,
        version=1,
        membership_id=membership_id,
        kind="approve",
    )
    assert approved.status_code == 201, approved.text
    dispatched = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction_id,
        version=2,
        membership_id=membership_id,
        kind="dispatch",
        extra={"dispatch_communication_id": records["communication_id"]},
    )
    assert dispatched.status_code == 201, dispatched.text

    lifecycle_payload = {
        "expected_lifecycle_version": 0,
        "to_status": "closed",
        "effective_at": datetime.now(UTC).isoformat(),
        "reason": "Client instructed the firm to close the foreign filing docket.",
        "outcome": "closed",
        "source": "client_instruction",
        "evidence_ref": "attachment:foreign-filing-closure",
        "linked_matter_handling": "reviewed",
        "client_report_handling": "retain",
    }
    closed = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle",
        headers=headers,
        json=lifecycle_payload,
    )
    assert closed.status_code == 200, closed.text
    close_event = closed.json()["event"]
    assert close_event["payload_json"]["cancelled_foreign_associate_instructions"] == 1

    with get_session_factory()() as session:
        stored = session.get(IpForeignAssociateInstruction, instruction_id)
        assert stored is not None
        assert stored.status == "cancelled"
        assert stored.row_version == 4
        assert stored.neutralized_by_ip_lifecycle_event_id == close_event["id"]
        assert stored.neutralized_by_ip_lifecycle_version == 1
        assert stored.neutralized_at is not None

    reopened = client.post(
        f"/api/ip/dockets/{docket['id']}/lifecycle",
        headers=headers,
        json={
            **lifecycle_payload,
            "expected_lifecycle_version": 1,
            "to_status": "ready",
            "reason": "Authorized lawyer approved controlled reopening.",
            "outcome": "reopened",
            "evidence_ref": "attachment:foreign-filing-reopen",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert (
        reopened.json()["event"]["payload_json"][
            "cancelled_foreign_associate_instructions"
        ]
        == 0
    )
    assert (
        client.get(
            f"/api/ip/foreign-associate-instructions/{instruction_id}",
            headers=headers,
        ).status_code
        == 404
    )
    listing = client.get(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        params={"outstanding_response": True},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"] == []
    with get_session_factory()() as session:
        stored = session.get(IpForeignAssociateInstruction, instruction_id)
        assert stored is not None
        assert stored.status == "cancelled"
        assert stored.neutralized_by_ip_lifecycle_event_id == close_event["id"]
