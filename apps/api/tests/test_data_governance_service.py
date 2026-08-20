from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import AuditEvent, Company, CompanyMembership, LegalHold, User
from caseops_api.db.session import get_session_factory
from caseops_api.governance.data_class_projection import admitted_data_class_ids
from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
from caseops_api.services.data_governance import (
    create_dry_run_manifest,
    reject_data_operation_execution,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company


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
        assert record.rejection_reason is None
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
    assert execution.value.detail["code"] == "data_operation_execution_unavailable"
    assert "tenant_data_operations" in (admitted_data_class_ids() or frozenset())


def test_iplf_028b_dry_run_routes_persist_reviewable_evidence_but_refuse_execution(
    client: TestClient,
) -> None:
    """UJ-28's safe half is reviewable; its effectful half is not routable."""

    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    payload = _payload().model_dump(mode="json")
    created = client.post(
        "/api/admin/data-governance/operations/dry-runs",
        headers=auth_headers(token),
        json=payload,
    )
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["execution_mode"] == "dry_run"
    assert record["status"] == "dry_run_complete"
    assert record["items"][0]["safe_to_execute"] is False

    read = client.get(
        f"/api/admin/data-governance/operations/dry-runs/{record['id']}",
        headers=auth_headers(token),
    )
    assert read.status_code == 200, read.text
    assert read.json()["manifest_hash"] == record["manifest_hash"]

    execution = client.post(
        f"/api/admin/data-governance/operations/{record['id']}/execute",
        headers=auth_headers(token),
    )
    assert execution.status_code == 503, execution.text
    assert execution.json()["code"] == "data_operation_execution_unavailable"


def test_iplf_028b_dry_run_history_is_bounded_and_tenant_scoped(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    first_token = str(first["access_token"])
    second_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Governance Firm",
            "company_slug": "second-governance-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "second-owner@governance.example",
            "owner_password": "SecondFoundersPass123!",
        },
    )
    assert second_response.status_code == 200, second_response.text
    second_token = str(second_response.json()["access_token"])

    first_created = client.post(
        "/api/admin/data-governance/operations/dry-runs",
        headers=auth_headers(first_token),
        json=_payload().model_dump(mode="json"),
    )
    assert first_created.status_code == 201, first_created.text
    second_payload = _payload().model_dump(mode="json")
    second_payload["request_evidence_ref"] = "fixture://other-tenant"
    second_created = client.post(
        "/api/admin/data-governance/operations/dry-runs",
        headers=auth_headers(second_token),
        json=second_payload,
    )
    assert second_created.status_code == 201, second_created.text

    history = client.get(
        "/api/admin/data-governance/operations/dry-runs?limit=1",
        headers=auth_headers(first_token),
    )
    assert history.status_code == 200, history.text
    operations = history.json()["operations"]
    assert [operation["id"] for operation in operations] == [first_created.json()["id"]]
    assert operations[0]["execution_mode"] == "dry_run"
    assert operations[0]["approval_status"] == "not_requested"
    assert operations[0]["rejection_reason"] is None
    assert "items" not in operations[0]

    cross_tenant = client.get(
        f"/api/admin/data-governance/operations/dry-runs/{first_created.json()['id']}",
        headers=auth_headers(second_token),
    )
    assert cross_tenant.status_code == 404, cross_tenant.text


def test_iplf_028b_integrity_route_reports_unavailable_checks_without_false_green(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    response = client.get(
        "/api/admin/data-governance/integrity",
        headers=auth_headers(str(bootstrap["access_token"])),
    )
    assert response.status_code == 200, response.text
    report = response.json()
    checks = {check["check_id"]: check for check in report["checks"]}
    assert checks["expired_unpurged"]["status"] == "unavailable"
    assert checks["expired_unpurged"]["blocked_by"] == "DATA-GOV-02"
    assert checks["purged_still_searchable"]["status"] == "unavailable"
    assert checks["provider_deletion_exceptions"]["status"] == "unavailable"
    assert report["is_complete"] is False
    assert report["unavailable_count"] >= 3
