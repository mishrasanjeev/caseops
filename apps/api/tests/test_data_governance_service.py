from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Company, CompanyMembership, LegalHold, User
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
from caseops_api.services.data_governance import (
    FOUNDATION_DATA_CLASS_IDS,
    create_dry_run_manifest,
    reject_data_operation_execution,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company


def _context_for_bootstrap(bootstrap: dict) -> SessionContext:
    with get_session_factory()() as session:
        company = session.get(Company, str(bootstrap["company"]["id"]))
        membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert company is not None
        assert membership is not None
        user = session.get(User, membership.user_id)
        assert user is not None
        session.expunge_all()
    return SessionContext(company=company, user=user, membership=membership)


def _payload(*, data_class_id: str = "legal_holds") -> TenantDataOperationDryRunRequest:
    return TenantDataOperationDryRunRequest.model_validate(
        {
            "operation_type": "tenant_export",
            "request_evidence_ref": "fixture://data-governance-dry-run",
            "items": [
                {
                    "data_class_id": data_class_id,
                    "target_type": "tenant",
                    "target_reference_hash": "a" * 64,
                    "candidate_record_count": 3,
                    "estimated_bytes": 128,
                    "detail_redacted": "synthetic fixture only",
                }
            ],
        }
    )


def test_dry_run_records_an_opaque_non_executable_manifest_and_audit_event(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    context = _context_for_bootstrap(bootstrap)

    with get_session_factory()() as session:
        record = create_dry_run_manifest(
            session,
            context=context,
            payload=_payload(),
        )
        assert record.execution_mode == "dry_run"
        assert record.status == "dry_run_complete"
        assert record.approval_status == "not_requested"
        assert record.items[0].item_status == "eligible"
        assert record.items[0].safe_to_execute is False
        assert len(record.manifest_hash) == 64
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == context.company.id,
                AuditEvent.target_id == record.id,
            )
        )
        assert audit is not None
        assert audit.action == "data_governance.operation.dry_run_completed"
        assert '"execute_authorized": false' in (audit.metadata_json or "")


def test_active_hold_conservatively_marks_every_foundation_target_held(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    context = _context_for_bootstrap(bootstrap)
    now = datetime.now(UTC)

    with get_session_factory()() as session:
        approver_user = User(
            email="hold-approver@fixture.example",
            full_name="Hold Approver",
            password_hash="fixture-only",
        )
        session.add(approver_user)
        session.flush()
        approver_membership = CompanyMembership(
            company_id=context.company.id,
            user_id=approver_user.id,
            role="admin",
        )
        session.add(approver_membership)
        session.flush()
        session.add(
            LegalHold(
                company_id=context.company.id,
                key="fixture-active-hold",
                title="Fixture active hold",
                authority_reference="fixture://active-hold",
                status="active",
                created_by_membership_id=context.membership.id,
                created_by_membership_company_id=context.company.id,
                creator_label_snapshot=context.user.email,
                approved_by_membership_id=approver_membership.id,
                approved_by_membership_company_id=context.company.id,
                approver_label_snapshot=approver_user.email,
                activated_at=now,
            )
        )
        session.commit()
        record = create_dry_run_manifest(
            session,
            context=context,
            payload=_payload(data_class_id="tenant_data_operations"),
        )
        assert record.items[0].item_status == "held"
        assert record.items[0].legal_hold_id is not None
        assert record.items[0].safe_to_execute is False


def test_unknown_class_and_execute_request_fail_closed_without_an_operation(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    context = _context_for_bootstrap(bootstrap)

    with get_session_factory()() as session:
        with pytest.raises(HTTPException) as rejected_class:
            create_dry_run_manifest(
                session,
                context=context,
                payload=_payload(data_class_id="unregistered_customer_payloads"),
            )
        assert rejected_class.value.status_code == 409
        assert rejected_class.value.detail["type"] == "data_class_not_registered_for_dry_run"

    with pytest.raises(HTTPException) as execution:
        reject_data_operation_execution(operation_id="fixture-operation")
    assert execution.value.status_code == 503
    assert execution.value.detail["type"] == "data_operation_execution_unavailable"
    assert "tenant_data_operations" in FOUNDATION_DATA_CLASS_IDS
