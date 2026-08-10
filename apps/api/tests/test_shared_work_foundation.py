from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, ForeignKeyConstraint

from caseops_api.db.base import Base
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpDocketRecord,
    Matter,
    MatterTask,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.notification_delivery import enqueue_notification_delivery_intent
from caseops_api.services.session_context import SessionContext
from caseops_api.services.shared_work import (
    MIGRATION_HEADS,
    resolve_shared_work_target,
    shared_work_foundation_contract,
)
from tests.test_auth_company import auth_headers, bootstrap_company

TARGET_TABLES = {
    "matter_tasks",
    "matter_hearings",
    "hearing_reminders",
    "matter_next_hearing_history",
    "matter_next_hearing_suggestions",
    "matter_deadlines",
}


def test_shared_work_extends_canonical_owners_without_duplicate_tables() -> None:
    assert TARGET_TABLES <= set(Base.metadata.tables)
    assert not {
        "ip_tasks",
        "ip_hearings",
        "ip_operational_deadlines",
        "ip_calendar_events",
        "ip_notification_intents",
    }.intersection(Base.metadata.tables)

    for table_name in TARGET_TABLES:
        table = Base.metadata.tables[table_name]
        assert "ip_docket_id" in table.columns
        checks = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        assert any(name and name.endswith("exactly_one_target") for name in checks)
        composite_targets = {
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        assert ("matter_id", "company_id") in composite_targets
        assert ("ip_docket_id", "company_id") in composite_targets


def test_foundation_contract_names_mixed_revision_and_one_writer_switch() -> None:
    contract = shared_work_foundation_contract()

    assert contract.migration_heads == MIGRATION_HEADS
    assert "nullable" in contract.mixed_revision_policy
    assert "ip_deadlines alone" in contract.one_writer_policy
    assert {owner.owner for owner in contract.owners} == {
        "tasks",
        "hearings",
        "next_hearing_provenance",
        "operational_deadlines",
        "calendar",
        "notifications",
    }
    assert "ip_tasks" in contract.forbidden_duplicates
    assert "ip_hearings" in contract.forbidden_duplicates


def test_target_resolver_rejects_ambiguous_or_missing_target_before_query() -> None:
    with pytest.raises(ValueError, match="Exactly one"):
        resolve_shared_work_target(None, context=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Exactly one"):
        resolve_shared_work_target(
            None,
            context=None,  # type: ignore[arg-type]
            matter_id="matter-1",
            ip_docket_id="docket-1",
        )


def test_notification_owner_accepts_one_ip_target_and_preserves_snapshots() -> None:
    table = Base.metadata.tables["notification_delivery_intents"]
    assert "ip_docket_id" in table.columns
    assert "recipient_snapshot_json" in table.columns
    checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_notification_delivery_at_most_one_work_target" in checks


def test_hearing_owner_carries_precision_provenance_mode_and_responsibility() -> None:
    columns = Base.metadata.tables["matter_hearings"].columns
    assert {
        "hearing_on",
        "time_status",
        "hearing_time",
        "session_label",
        "timezone",
        "hearing_mode",
        "source",
        "source_ref_type",
        "source_ref_id",
        "responsible_membership_id",
    } <= set(columns.keys())


def test_ip_contract_and_reconciliation_use_shared_rows_and_one_notification_owner(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    headers = auth_headers(str(bootstrap["access_token"]))

    contract_response = client.get(
        "/api/ip/shared-work/foundation-contract", headers=headers
    )
    assert contract_response.status_code == 200, contract_response.text
    assert contract_response.json()["contract_version"] == "IPLF-025A/2026-08-10"

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        company = session.get(Company, company_id)
        assert membership is not None and company is not None
        user = session.get(User, membership.user_id)
        assert user is not None
        context = SessionContext(company=company, membership=membership, user=user)
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Shared-work target",
            status="draft",
            restricted=False,
            created_by_membership_id=membership_id,
        )
        session.add(docket)
        session.commit()
        docket_id = docket.id

    task_response = client.post(
        "/api/ip/tasks",
        headers=headers,
        json={
            "docket_id": docket_id,
            "title": "Review registry evidence",
            "owner_membership_id": membership_id,
            "status": "todo",
            "priority": "high",
        },
    )
    assert task_response.status_code == 201, task_response.text
    task_id = str(task_response.json()["id"])
    completed = client.patch(
        f"/api/ip/tasks/{task_id}",
        headers=headers,
        json={"docket_id": docket_id, "status": "completed"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["completed_at"] is not None
    null_title = client.patch(
        f"/api/ip/tasks/{task_id}",
        headers=headers,
        json={"docket_id": docket_id, "title": None},
    )
    assert null_title.status_code == 422, null_title.text
    task_list = client.get(
        f"/api/ip/tasks?docket_id={docket_id}&include_completed=true", headers=headers
    )
    assert task_list.status_code == 200, task_list.text
    assert [row["id"] for row in task_list.json()["tasks"]] == [task_id]

    hearing_response = client.post(
        "/api/ip/hearings",
        headers=headers,
        json={
            "docket_id": docket_id,
            "hearing_on": "2026-09-01",
            "forum_name": "Trade Marks Registry, Delhi",
            "purpose": "Show-cause hearing",
            "time_status": "session",
            "session_label": "Morning board",
            "hearing_mode": "hybrid",
            "responsible_membership_id": membership_id,
        },
    )
    assert hearing_response.status_code == 201, hearing_response.text
    hearing_id = str(hearing_response.json()["id"])
    rescheduled = client.patch(
        f"/api/ip/hearings/{hearing_id}",
        headers=headers,
        json={"docket_id": docket_id, "hearing_on": "2026-09-02"},
    )
    assert rescheduled.status_code == 200, rescheduled.text
    assert rescheduled.json()["hearing_on"] == "2026-09-02"

    deadline_response = client.post(
        "/api/ip/operational-deadlines",
        headers=headers,
        json={
            "docket_id": docket_id,
            "source": "followup",
            "kind": "hearing_note",
            "title": "File hearing note",
            "due_on": "2026-09-03",
            "assignee_membership_id": membership_id,
        },
    )
    assert deadline_response.status_code == 201, deadline_response.text
    deadline_id = str(deadline_response.json()["id"])
    deadline_done = client.patch(
        f"/api/ip/operational-deadlines/{deadline_id}",
        headers=headers,
        json={"docket_id": docket_id, "status": "done"},
    )
    assert deadline_done.status_code == 200, deadline_done.text
    assert deadline_done.json()["completed_at"] is not None

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        company = session.get(Company, company_id)
        docket = session.get(IpDocketRecord, docket_id)
        assert membership is not None and company is not None and docket is not None
        user = session.get(User, membership.user_id)
        assert user is not None
        context = SessionContext(company=company, membership=membership, user=user)
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=membership,
            channel="in_app",
            event_type="ip_work_assigned",
            source_type="matter_task",
            source_id=task_id,
            ip_docket=docket,
            title="IP work assigned",
            body="Open the IP docket to review assigned work.",
        )
        assert intent is not None
        assert intent.matter_id is None
        assert intent.ip_docket_id == docket.id
        session.commit()

    report_response = client.get("/api/ip/shared-work/reconciliation", headers=headers)
    assert report_response.status_code == 200, report_response.text
    report = report_response.json()
    assert report["ready"] is True
    tasks = next(row for row in report["owners"] if row["owner"] == "tasks")
    assert tasks["ip_target_rows"] == 1
    assert tasks["legacy_tail_rows"] == 0
    assert tasks["tenant_mismatch_rows"] == 0
    assert report["notification_ip_target_rows"] == 1
    hearings = next(row for row in report["owners"] if row["owner"] == "hearings")
    assert hearings["ip_target_rows"] == 1
    history = next(
        row for row in report["owners"] if row["owner"] == "next_hearing_history"
    )
    assert history["ip_target_rows"] == 2
    deadlines = next(
        row for row in report["owners"] if row["owner"] == "operational_deadlines"
    )
    assert deadlines["ip_target_rows"] == 1

    other_response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Birch Legal LLP",
            "company_slug": "birch-legal",
            "company_type": "law_firm",
            "owner_full_name": "Beena Rao",
            "owner_email": "owner@birchlegal.in",
            "owner_password": "FoundersPass123!",
        },
    )
    assert other_response.status_code == 200, other_response.text
    other_bootstrap = other_response.json()
    other_headers = auth_headers(str(other_bootstrap["access_token"]))
    with get_session_factory()() as session:
        other_matter = Matter(
            company_id=str(other_bootstrap["company"]["id"]),
            title="Other tenant legacy tail",
            matter_code="OTHER-LEGACY-001",
            practice_area="Litigation",
            forum_level="district",
        )
        session.add(other_matter)
        session.flush()
        session.add(
            MatterTask(
                company_id=None,
                matter_id=other_matter.id,
                title="Other tenant nullable legacy task",
            )
        )
        session.commit()

    cross_tenant = client.get(
        f"/api/ip/tasks?docket_id={docket_id}", headers=other_headers
    )
    assert cross_tenant.status_code == 404, cross_tenant.text
    first_tenant_report = client.get(
        "/api/ip/shared-work/reconciliation", headers=headers
    )
    assert first_tenant_report.status_code == 200, first_tenant_report.text
    first_tenant_tasks = next(
        row
        for row in first_tenant_report.json()["owners"]
        if row["owner"] == "tasks"
    )
    assert first_tenant_tasks["row_count"] == 1
    assert first_tenant_tasks["legacy_tail_rows"] == 0
