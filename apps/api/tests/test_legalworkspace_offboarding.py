from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    CalendarEventSync,
    CalendarEventSyncStatus,
    CompanyMembership,
    Contract,
    ContractObligation,
    Draft,
    DraftReview,
    EthicalWall,
    HearingPack,
    HearingReminder,
    IpDeadlineCoverage,
    IpDocketQueue,
    IpDocketRecord,
    IpRelatedRightObligation,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    Team,
    TeamMembership,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers


def _bootstrap(
    client: TestClient,
    *,
    slug: str = "lw-s8-firm",
    email: str = "owner@lws8.example",
) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Owner S8",
            "owner_email": email,
            "owner_password": "OwnerPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_employee(
    client: TestClient,
    token: str,
    *,
    email: str,
    full_name: str,
    role: str = "member",
) -> dict[str, object]:
    response = client.post(
        "/api/companies/current/employees",
        headers=auth_headers(token),
        json={
            "full_name": full_name,
            "email": email,
            "role": role,
            "department": "Litigation",
            "designation": "Associate",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _complete_setup(
    client: TestClient,
    setup_token: str,
    *,
    password: str,
) -> str:
    response = client.post(
        "/api/auth/account-setup/complete",
        json={"token": setup_token, "password": password},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _employee_import_csv(rows: list[dict[str, str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "Name",
            "Email",
            "Role",
            "Mobile",
            "Designation",
            "Department",
            "EmployeeCode",
            "ManagerEmail",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _bulk_import_employee(
    client: TestClient,
    token: str,
    *,
    full_name: str,
    email: str,
    role: str = "member",
) -> dict[str, object]:
    preview = client.post(
        "/api/companies/current/employees/imports/preview",
        headers=auth_headers(token),
        files={
            "file": (
                "employees.csv",
                _employee_import_csv(
                    [
                        {
                            "Name": full_name,
                            "Email": email,
                            "Role": role,
                            "Department": "Litigation",
                        }
                    ]
                ),
                "text/csv",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    job = preview.json()
    assert job["valid_rows"] == 1
    commit = client.post(
        f"/api/companies/current/employees/imports/{job['id']}/commit",
        headers=auth_headers(token),
    )
    assert commit.status_code == 200, commit.text
    return commit.json()["created_employees"][0]


def _seed_owned_objects(
    *,
    company_id: str,
    target_membership_id: str,
    replacement_membership_id: str | None = None,
) -> dict[str, str]:
    factory = get_session_factory()
    with factory() as session:
        matter = Matter(
            company_id=company_id,
            assignee_membership_id=target_membership_id,
            title="Offboarding Matter",
            matter_code="LW8-001",
            practice_area="Commercial",
            forum_level="high_court",
            court_name="Delhi High Court",
            restricted_access=True,
        )
        team = Team(
            company_id=company_id,
            name="Disputes Team",
            slug="disputes-team",
        )
        contract = Contract(
            company_id=company_id,
            owner_membership_id=target_membership_id,
            title="Master Services Agreement",
            contract_code="CTR-LW8-001",
            contract_type="msa",
        )
        session.add_all([matter, team, contract])
        session.flush()
        grant = MatterAccessGrant(
            matter_id=matter.id,
            membership_id=target_membership_id,
            reason="restricted matter owner",
            granted_by_membership_id=target_membership_id,
        )
        replacement_grant = (
            MatterAccessGrant(
                matter_id=matter.id,
                membership_id=replacement_membership_id,
                reason="offboarding replacement access",
                granted_by_membership_id=target_membership_id,
            )
            if replacement_membership_id is not None
            else None
        )
        team_membership = TeamMembership(
            team_id=team.id,
            membership_id=target_membership_id,
            is_lead=True,
        )
        obligation = ContractObligation(
            contract_id=contract.id,
            owner_membership_id=target_membership_id,
            title="Quarterly renewal review",
        )
        task = MatterTask(
            matter_id=matter.id,
            created_by_membership_id=target_membership_id,
            owner_membership_id=target_membership_id,
            title="Prepare offboarding transfer note",
        )
        deadline = MatterDeadline(
            company_id=company_id,
            matter_id=matter.id,
            source="manual",
            kind="filing",
            title="File written submissions",
            due_on=date(2026, 5, 20),
            assignee_membership_id=target_membership_id,
            created_by_membership_id=target_membership_id,
        )
        session.add(deadline)
        session.flush()
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Offboarding trademark",
            status="active",
            created_by_membership_id=target_membership_id,
        )
        session.add(docket)
        session.flush()
        ip_coverage = IpDeadlineCoverage(
            company_id=company_id,
            docket_id=docket.id,
            matter_deadline_id=deadline.id,
            responsible_membership_id=target_membership_id,
            coverage_status="accepted",
        )
        personal_queue = IpDocketQueue(
            company_id=company_id,
            name="Departing lawyer daily docket",
            filters_json={"critical_only": True},
            owner_membership_id=target_membership_id,
            created_by_membership_id=target_membership_id,
        )
        hearing = MatterHearing(
            matter_id=matter.id,
            hearing_on=date(2026, 5, 22),
            forum_name="Delhi High Court",
            purpose="Directions",
        )
        session.add(hearing)
        session.flush()
        reminder = HearingReminder(
            company_id=company_id,
            matter_id=matter.id,
            hearing_id=hearing.id,
            recipient_membership_id=target_membership_id,
            recipient_email="target@lws8.example",
            channel="email",
            scheduled_for=datetime(2026, 5, 21, 4, 0, tzinfo=UTC),
        )
        draft = Draft(
            matter_id=matter.id,
            created_by_membership_id=target_membership_id,
            title="Draft written submissions",
        )
        session.add(draft)
        session.flush()
        draft_review = DraftReview(
            draft_id=draft.id,
            actor_membership_id=target_membership_id,
            action="approve",
        )
        hearing_pack = HearingPack(
            matter_id=matter.id,
            generated_by_membership_id=target_membership_id,
            summary="Hearing pack summary",
        )
        session.add_all(
            [
                grant,
                *([replacement_grant] if replacement_grant is not None else []),
                team_membership,
                obligation,
                task,
                deadline,
                ip_coverage,
                personal_queue,
                reminder,
                draft_review,
                hearing_pack,
            ]
        )
        session.commit()
        return {
            "matter_id": matter.id,
            "grant_id": grant.id,
            "team_membership_id": team_membership.id,
            "contract_id": contract.id,
            "obligation_id": obligation.id,
            "task_id": task.id,
            "deadline_id": deadline.id,
            "ip_coverage_id": ip_coverage.id,
            "ip_docket_queue_id": personal_queue.id,
            "reminder_id": reminder.id,
            "draft_id": draft.id,
            "draft_review_id": draft_review.id,
            "hearing_pack_id": hearing_pack.id,
        }


def _seed_standalone_ip_owned_objects(
    *,
    company_id: str,
    target_membership_id: str,
    replacement_membership_id: str,
    identifier_suffix: str = "",
) -> dict[str, str]:
    identifier_suffix_text = f"-{identifier_suffix}" if identifier_suffix else ""
    factory = get_session_factory()
    with factory() as session:
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Standalone offboarding trademark",
            primary_identifier=f"TM-OFFBOARD-STANDALONE{identifier_suffix_text}",
            status="active",
            created_by_membership_id=target_membership_id,
        )
        session.add(docket)
        session.flush()
        deadline = MatterDeadline(
            company_id=company_id,
            ip_docket_id=docket.id,
            source="manual",
            kind="renewal",
            title="Renew standalone trademark",
            due_on=date(2026, 9, 30),
            assignee_membership_id=target_membership_id,
            created_by_membership_id=target_membership_id,
        )
        session.add(deadline)
        session.flush()
        coverage = IpDeadlineCoverage(
            company_id=company_id,
            docket_id=docket.id,
            matter_deadline_id=deadline.id,
            responsible_membership_id=target_membership_id,
            coverage_status="accepted",
        )
        no_coverage_docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Standalone docket without coverage",
            primary_identifier=f"TM-OFFBOARD-NO-COVERAGE{identifier_suffix_text}",
            status="active",
            created_by_membership_id=target_membership_id,
        )
        session.add(no_coverage_docket)
        session.flush()
        no_coverage_deadline = MatterDeadline(
            company_id=company_id,
            ip_docket_id=no_coverage_docket.id,
            source="manual",
            kind="response",
            title="Respond on uncovered standalone docket",
            due_on=date(2026, 10, 15),
            assignee_membership_id=target_membership_id,
            created_by_membership_id=target_membership_id,
        )
        session.add(no_coverage_deadline)
        historical_docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Historical standalone offboarding trademark",
            primary_identifier=f"TM-OFFBOARD-HISTORY{identifier_suffix_text}",
            status="closed",
            is_active=False,
            restricted=True,
            created_by_membership_id=target_membership_id,
        )
        session.add(historical_docket)
        session.flush()
        historical_deadline = MatterDeadline(
            company_id=company_id,
            ip_docket_id=historical_docket.id,
            source="manual",
            kind="renewal",
            title="Historical trademark renewal",
            due_on=date(2025, 9, 30),
            status="done",
            assignee_membership_id=target_membership_id,
            created_by_membership_id=target_membership_id,
        )
        session.add(historical_deadline)
        session.flush()
        historical_coverage = IpDeadlineCoverage(
            company_id=company_id,
            docket_id=historical_docket.id,
            matter_deadline_id=historical_deadline.id,
            responsible_membership_id=target_membership_id,
            backup_membership_id=replacement_membership_id,
            coverage_status="completed",
            pending_replacement_membership_id=target_membership_id,
            replacement_decision="pending",
            emergency_escalation_membership_id=target_membership_id,
        )
        session.add_all([coverage, historical_coverage])
        session.commit()
        return {
            "docket_id": docket.id,
            "deadline_id": deadline.id,
            "coverage_id": coverage.id,
            "no_coverage_docket_id": no_coverage_docket.id,
            "no_coverage_deadline_id": no_coverage_deadline.id,
            "historical_docket_id": historical_docket.id,
            "historical_deadline_id": historical_deadline.id,
            "historical_coverage_id": historical_coverage.id,
        }


def test_offboarding_preview_commit_reassigns_supported_objects_and_revokes_sessions(
    client: TestClient,
) -> None:
    boot = _bootstrap(client)
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@lws8.example",
        full_name="Target Employee",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@lws8.example",
        full_name="Replacement Employee",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    _complete_setup(
        client,
        str(target["setup"]["debug_token"]),
        password="TargetPass123!",
    )
    replacement_token = _complete_setup(
        client,
        str(replacement["setup"]["debug_token"]),
        password="ReplacementPass123!",
    )
    active_login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "lw-s8-firm",
            "email": "target@lws8.example",
            "password": "TargetPass123!",
        },
    )
    assert active_login.status_code == 200, active_login.text
    target_token = str(active_login.json()["access_token"])
    seeded = _seed_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=replacement_id,
    )

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id, "notes": "Exit"},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["can_commit"] is True
    assert preview_body["supported_counts"]["matters"] == 1
    assert preview_body["supported_counts"]["restricted_access_grants"] == 1
    assert preview_body["supported_counts"]["team_memberships"] == 1
    assert preview_body["supported_counts"]["contracts"] == 1
    assert preview_body["supported_counts"]["contract_obligations"] == 1
    assert preview_body["supported_counts"]["matter_tasks"] == 1
    assert preview_body["supported_counts"]["matter_deadlines"] == 1
    assert preview_body["supported_counts"]["ip_deadline_coverages"] == 1
    assert preview_body["supported_counts"]["ip_docket_queues"] == 1
    assert preview_body["supported_counts"]["hearing_reminders"] == 0
    assert preview_body["unsupported_counts"]["drafts"] == 1
    assert preview_body["unsupported_counts"]["draft_reviews"] == 1
    assert preview_body["unsupported_counts"]["hearing_packs"] == 1

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id, "notes": "Exit"},
    )
    assert commit.status_code == 200, commit.text
    commit_body = commit.json()
    assert commit_body["deactivated"] is True
    assert commit_body["sessions_revoked"] is True
    assert commit_body["employee"]["employment_status"] == "inactive"
    assert commit_body["employee"]["membership_active"] is False
    assert commit_body["employee"]["user_active"] is False

    replacement_queues = client.get(
        "/api/ip/docket-queues",
        headers=auth_headers(replacement_token),
    )
    assert replacement_queues.status_code == 200, replacement_queues.text
    assert [row["name"] for row in replacement_queues.json()["queues"]] == [
        "Departing lawyer daily docket"
    ]

    stale = client.get("/api/auth/me", headers=auth_headers(target_token))
    assert stale.status_code in {401, 403}
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "lw-s8-firm",
            "email": "target@lws8.example",
            "password": "TargetPass123!",
        },
    )
    assert login.status_code != 200

    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, seeded["matter_id"])
        grant = session.scalar(
            select(MatterAccessGrant).where(
                MatterAccessGrant.matter_id == seeded["matter_id"],
                MatterAccessGrant.membership_id == replacement_id,
            )
        )
        team_membership = session.get(TeamMembership, seeded["team_membership_id"])
        contract = session.get(Contract, seeded["contract_id"])
        obligation = session.get(ContractObligation, seeded["obligation_id"])
        task = session.get(MatterTask, seeded["task_id"])
        deadline = session.get(MatterDeadline, seeded["deadline_id"])
        ip_coverage = session.get(IpDeadlineCoverage, seeded["ip_coverage_id"])
        personal_queue = session.get(IpDocketQueue, seeded["ip_docket_queue_id"])
        reminder = session.get(HearingReminder, seeded["reminder_id"])
        draft = session.get(Draft, seeded["draft_id"])
        assert matter is not None and matter.assignee_membership_id == replacement_id
        assert grant is not None and grant.membership_id == replacement_id
        assert team_membership is not None and team_membership.membership_id == replacement_id
        assert contract is not None and contract.owner_membership_id == replacement_id
        assert obligation is not None and obligation.owner_membership_id == replacement_id
        assert task is not None and task.owner_membership_id == replacement_id
        assert deadline is not None and deadline.assignee_membership_id == replacement_id
        assert ip_coverage is not None
        assert ip_coverage.responsible_membership_id == replacement_id
        assert ip_coverage.reassignment_version == 2
        # IPLF-UJ-57-RECON-04 (2026-08-15): offboarding transfers immediately
        # because the departing person cannot be waited on, but it must not
        # record an acceptance the replacement never gave, and a decline needs
        # somewhere to go. Coverage was seeded `accepted` by the leaver, so the
        # test is that the transfer did not re-stamp acceptance onto the new
        # owner and left the acknowledgement outstanding.
        assert ip_coverage.replacement_decision == "pending"
        assert ip_coverage.pending_replacement_membership_id == replacement_id
        assert ip_coverage.emergency_escalation_membership_id is not None
        assert ip_coverage.coverage_status == "reassigned"
        assert personal_queue is not None
        assert personal_queue.owner_membership_id == replacement_id
        # Destination snapshots are immutable evidence. The bounded IP guard
        # never rewrites a historical/non-IP reminder in place.
        assert reminder is not None and reminder.recipient_membership_id == target_id
        assert reminder.recipient_email == "target@lws8.example"
        assert draft is not None and draft.created_by_membership_id == target_id

    audit = client.get(
        f"/api/companies/current/employees/{target_id}/audit",
        headers=auth_headers(owner_token),
    )
    assert audit.status_code == 200, audit.text
    actions = {event["action"] for event in audit.json()["events"]}
    assert "employee.offboarding.previewed" in actions
    assert "employee.offboarding.committed" in actions
    assert "employee.deactivated" in actions
    assert "employee.session_revoked" in actions
    assert "employee.account_setup.completed" in actions
    assert "employee.login" in actions


def test_offboarding_reassigns_standalone_ip_deadline_and_coverage(
    client: TestClient,
) -> None:
    """A Matter-less IP deadline cannot remain owned by an inactive employee."""

    boot = _bootstrap(
        client,
        slug="lw-s8-standalone-ip-offboarding",
        email="owner@standalone-ip-offboarding.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@standalone-ip-offboarding.example",
        full_name="Standalone IP Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@standalone-ip-offboarding.example",
        full_name="Standalone IP Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    seeded = _seed_standalone_ip_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=replacement_id,
    )

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["can_commit"] is True
    assert preview_body["blockers"] == []
    assert preview_body["supported_counts"]["matter_deadlines"] == 2
    assert preview_body["supported_counts"]["ip_deadline_coverages"] == 1
    supported_by_key = {
        (row["object_type"], row["id"]): row for row in preview_body["supported_objects"]
    }
    assert ("matter_deadlines", seeded["historical_deadline_id"]) not in supported_by_key
    assert (
        "ip_deadline_coverages",
        seeded["historical_coverage_id"],
    ) not in supported_by_key
    deadline_object = supported_by_key[("matter_deadlines", seeded["deadline_id"])]
    assert deadline_object == {
        "object_type": "matter_deadlines",
        "id": seeded["deadline_id"],
        "label": "TM-OFFBOARD-STANDALONE - Renew standalone trademark",
        "relation": "assignee",
        "supported": True,
        "matter_id": None,
    }
    no_coverage_deadline_object = supported_by_key[
        ("matter_deadlines", seeded["no_coverage_deadline_id"])
    ]
    assert no_coverage_deadline_object["matter_id"] is None
    assert no_coverage_deadline_object["relation"] == "assignee"
    coverage_object = supported_by_key[("ip_deadline_coverages", seeded["coverage_id"])]
    assert coverage_object["matter_id"] is None
    assert coverage_object["relation"] == "IP deadline responsible"

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 200, commit.text
    commit_body = commit.json()
    assert commit_body["employee"]["membership_active"] is False
    assert commit_body["employee"]["user_active"] is False
    assert commit_body["preview"]["supported_counts"]["matter_deadlines"] == 2
    assert commit_body["preview"]["supported_counts"]["ip_deadline_coverages"] == 1

    audit = client.get(
        f"/api/companies/current/employees/{target_id}/audit",
        headers=auth_headers(owner_token),
    )
    assert audit.status_code == 200, audit.text
    committed_event = next(
        event
        for event in audit.json()["events"]
        if event["action"] == "employee.offboarding.committed"
    )
    assert committed_event["metadata"]["reassigned_counts"]["matter_deadlines"] == 2
    assert committed_event["metadata"]["reassigned_counts"]["ip_deadline_coverages"] == 1

    # A new session proves the final assignments and deactivation survived the
    # commit rather than only changing objects in the request identity map.
    factory = get_session_factory()
    with factory() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        persisted_deadline = session.get(MatterDeadline, seeded["deadline_id"])
        no_coverage_deadline = session.get(MatterDeadline, seeded["no_coverage_deadline_id"])
        persisted_coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        historical_deadline = session.get(MatterDeadline, seeded["historical_deadline_id"])
        historical_coverage = session.get(IpDeadlineCoverage, seeded["historical_coverage_id"])
        assert persisted_target is not None
        assert persisted_target.is_active is False
        assert persisted_target.user.is_active is False
        assert persisted_deadline is not None
        assert persisted_deadline.ip_docket_id == seeded["docket_id"]
        assert persisted_deadline.matter_id is None
        assert persisted_deadline.assignee_membership_id == replacement_id
        assert no_coverage_deadline is not None
        assert no_coverage_deadline.ip_docket_id == seeded["no_coverage_docket_id"]
        assert no_coverage_deadline.assignee_membership_id == replacement_id
        assert persisted_coverage is not None
        assert persisted_coverage.responsible_membership_id == replacement_id
        assert persisted_coverage.pending_replacement_membership_id == replacement_id
        assert persisted_coverage.coverage_status == "reassigned"
        assert persisted_coverage.reassignment_version == 2
        assert historical_deadline is not None
        assert historical_deadline.assignee_membership_id == target_id
        assert historical_deadline.status == "done"
        assert historical_coverage is not None
        assert historical_coverage.responsible_membership_id == target_id
        assert historical_coverage.backup_membership_id == replacement_id
        assert historical_coverage.coverage_status == "completed"
        assert historical_coverage.pending_replacement_membership_id == target_id
        assert historical_coverage.emergency_escalation_membership_id == target_id


def test_offboarding_transfers_only_operational_ip_tasks_and_obligations(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-ip-work-offboarding",
        email="owner@ip-work-offboarding.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@ip-work-offboarding.example",
        full_name="IP Work Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@ip-work-offboarding.example",
        full_name="IP Work Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])

    factory = get_session_factory()
    with factory() as session:
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Operational IP work",
            primary_identifier="TM-IP-WORK-OFFBOARD",
            status="active",
            created_by_membership_id=target_id,
        )
        session.add(docket)
        session.flush()
        open_task = MatterTask(
            company_id=company_id,
            ip_docket_id=docket.id,
            created_by_membership_id=target_id,
            owner_membership_id=target_id,
            title="Prepare renewal evidence",
            status="in_progress",
        )
        completed_task = MatterTask(
            company_id=company_id,
            ip_docket_id=docket.id,
            created_by_membership_id=target_id,
            owner_membership_id=target_id,
            title="Historical task",
            status="completed",
        )
        open_obligation = IpRelatedRightObligation(
            company_id=company_id,
            docket_id=docket.id,
            obligation_type="renewal",
            title="Maintain related registration",
            owner_membership_id=target_id,
            status="open",
            evidence_reference="evidence://open-obligation",
        )
        completed_obligation = IpRelatedRightObligation(
            company_id=company_id,
            docket_id=docket.id,
            obligation_type="renewal",
            title="Historical obligation",
            owner_membership_id=target_id,
            status="completed",
            evidence_reference="evidence://completed-obligation",
        )
        session.add_all(
            [open_task, completed_task, open_obligation, completed_obligation]
        )
        session.commit()
        ids = {
            "open_task": open_task.id,
            "completed_task": completed_task.id,
            "open_obligation": open_obligation.id,
            "completed_obligation": completed_obligation.id,
        }

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_commit"] is True
    assert body["supported_counts"]["matter_tasks"] == 1
    assert body["supported_counts"]["ip_related_right_obligations"] == 1
    object_keys = {(row["object_type"], row["id"]) for row in body["supported_objects"]}
    assert ("matter_tasks", ids["open_task"]) in object_keys
    assert ("matter_tasks", ids["completed_task"]) not in object_keys
    assert ("ip_related_right_obligations", ids["open_obligation"]) in object_keys
    assert ("ip_related_right_obligations", ids["completed_obligation"]) not in object_keys

    committed = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert committed.status_code == 200, committed.text
    with factory() as session:
        assert session.get(MatterTask, ids["open_task"]).owner_membership_id == replacement_id
        assert session.get(MatterTask, ids["completed_task"]).owner_membership_id == target_id
        assert (
            session.get(
                IpRelatedRightObligation, ids["open_obligation"]
            ).owner_membership_id
            == replacement_id
        )
        assert (
            session.get(
                IpRelatedRightObligation, ids["completed_obligation"]
            ).owner_membership_id
            == target_id
        )


def test_linked_ip_matter_task_requires_and_supports_offboarding_handoff(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-linked-ip-task-offboarding",
        email="owner@linked-ip-task-offboarding.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@linked-ip-task-offboarding.example",
        full_name="Linked IP Task Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@linked-ip-task-offboarding.example",
        full_name="Linked IP Task Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])

    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            title="Matter-owned task with linked IP work",
            matter_code="LINKED-IP-TASK-001",
            practice_area="Intellectual Property",
            forum_level="high_court",
            status="active",
        )
        session.add(matter)
        session.flush()
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Linked task docket",
            primary_identifier="TM-LINKED-TASK",
            status="active",
            created_by_membership_id=target_id,
        )
        task = MatterTask(
            company_id=company_id,
            matter_id=matter.id,
            owner_membership_id=target_id,
            created_by_membership_id=target_id,
            title="Prepare linked-IP response evidence",
            status="todo",
        )
        session.add_all([docket, task])
        session.commit()
        task_id = task.id

    generic = client.patch(
        f"/api/companies/current/users/{target_id}",
        headers=auth_headers(owner_token),
        json={"is_active": False},
    )
    assert generic.status_code == 409, generic.text
    assert generic.json()["code"] == "employee_offboarding_required"
    assert generic.json()["live_reference_counts"]["ip_docket_tasks"] == 1

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is True
    assert preview.json()["supported_counts"]["matter_tasks"] == 1
    assert [
        row["id"]
        for row in preview.json()["supported_objects"]
        if row["object_type"] == "matter_tasks"
    ] == [task_id]

    committed = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert committed.status_code == 200, committed.text
    with get_session_factory()() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        persisted_task = session.get(MatterTask, task_id)
        assert persisted_target is not None and persisted_target.is_active is False
        assert persisted_task is not None
        assert persisted_task.owner_membership_id == replacement_id


def test_generic_linked_ip_deadline_blocks_deactivation_once_and_offboards(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-linked-ip-generic-deadline",
        email="owner@linked-ip-generic-deadline.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@linked-ip-generic-deadline.example",
        full_name="Linked IP Generic Deadline Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@linked-ip-generic-deadline.example",
        full_name="Linked IP Generic Deadline Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])

    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            title="Matter with a generic deadline and two linked IP records",
            matter_code="LINKED-IP-GENERIC-DEADLINE-001",
            practice_area="Intellectual Property",
            forum_level="high_court",
            status="active",
        )
        session.add(matter)
        session.flush()
        session.add_all(
            [
                IpDocketRecord(
                    company_id=company_id,
                    matter_id=matter.id,
                    record_type="trademark",
                    title="First linked generic-deadline docket",
                    primary_identifier="TM-LINKED-GENERIC-ONE",
                    status="active",
                    created_by_membership_id=target_id,
                ),
                IpDocketRecord(
                    company_id=company_id,
                    matter_id=matter.id,
                    record_type="trademark",
                    title="Second linked generic-deadline docket",
                    primary_identifier="TM-LINKED-GENERIC-TWO",
                    status="active",
                    created_by_membership_id=target_id,
                ),
            ]
        )
        live_deadline = MatterDeadline(
            company_id=company_id,
            matter_id=matter.id,
            source="custom",
            kind="response",
            title="Live generic linked-IP deadline",
            due_on=date(2026, 12, 10),
            status="missed",
            assignee_membership_id=target_id,
            created_by_membership_id=target_id,
        )
        historical_deadline = MatterDeadline(
            company_id=company_id,
            matter_id=matter.id,
            source="custom",
            kind="response",
            title="Completed generic linked-IP deadline",
            due_on=date(2025, 12, 10),
            status="done",
            assignee_membership_id=target_id,
            created_by_membership_id=target_id,
        )
        session.add_all([live_deadline, historical_deadline])
        session.commit()
        live_deadline_id = live_deadline.id
        historical_deadline_id = historical_deadline.id

    generic = client.patch(
        f"/api/companies/current/users/{target_id}",
        headers=auth_headers(owner_token),
        json={"is_active": False},
    )
    assert generic.status_code == 409, generic.text
    assert generic.json()["code"] == "employee_offboarding_required"
    # One generic deadline is linked to two active dockets but remains one
    # responsibility object; terminal history is excluded.
    assert generic.json()["live_reference_counts"]["ip_docket_deadlines"] == 1

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_commit"] is True
    assert body["supported_counts"]["matter_deadlines"] == 1
    assert [
        row["id"]
        for row in body["supported_objects"]
        if row["object_type"] == "matter_deadlines"
    ] == [live_deadline_id]

    committed = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert committed.status_code == 200, committed.text
    with get_session_factory()() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        persisted_live = session.get(MatterDeadline, live_deadline_id)
        persisted_history = session.get(MatterDeadline, historical_deadline_id)
        assert persisted_target is not None and persisted_target.is_active is False
        assert persisted_live is not None
        assert persisted_live.assignee_membership_id == replacement_id
        assert persisted_history is not None
        assert persisted_history.assignee_membership_id == target_id


def test_generic_linked_deadline_offboarding_checks_every_sibling_docket(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-generic-deadline-sibling-access",
        email="owner@generic-deadline-sibling-access.example",
    )
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@generic-deadline-sibling-access.example",
        full_name="Sibling Docket Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@generic-deadline-sibling-access.example",
        full_name="Sibling Docket Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])

    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            title="Generic deadline with one restricted sibling",
            matter_code="LINKED-IP-SIBLING-ACCESS-001",
            practice_area="Intellectual Property",
            forum_level="high_court",
            status="active",
        )
        session.add(matter)
        session.flush()
        unrestricted = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Unrestricted sibling",
            primary_identifier="TM-SIBLING-ACCESS-ONE",
            status="active",
            is_active=True,
            restricted=False,
            created_by_membership_id=owner_id,
        )
        restricted = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Restricted sibling",
            primary_identifier="TM-SIBLING-ACCESS-TWO",
            status="active",
            is_active=True,
            restricted=True,
            created_by_membership_id=owner_id,
        )
        deadline = MatterDeadline(
            company_id=company_id,
            matter_id=matter.id,
            source="custom",
            kind="response",
            title="Sibling-bound generic deadline",
            due_on=date(2026, 12, 11),
            status="open",
            assignee_membership_id=target_id,
            created_by_membership_id=owner_id,
        )
        session.add_all([unrestricted, restricted, deadline])
        session.flush()
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=restricted.id,
                membership_id=target_id,
                reason="Existing target has durable restricted-docket access.",
                granted_by_membership_id=owner_id,
            )
        )
        session.commit()
        deadline_id = deadline.id
        restricted_id = restricted.id

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "cannot access every affected ip docket" in " ".join(
        preview.json()["blockers"]
    ).lower()

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 400, commit.text
    with get_session_factory()() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        persisted_deadline = session.get(MatterDeadline, deadline_id)
        assert persisted_target is not None and persisted_target.is_active is True
        assert persisted_deadline is not None
        assert persisted_deadline.assignee_membership_id == target_id
        assert session.scalar(
            select(MatterAccessGrant.id).where(
                MatterAccessGrant.ip_docket_id == restricted_id,
                MatterAccessGrant.membership_id == replacement_id,
            )
        ) is None


@pytest.mark.parametrize(
    "hearing_role",
    ["responsible", "attendee", "reminder_recipient", "reminder_escalation"],
)
def test_linked_ip_matter_hearing_roles_block_deactivation_and_offboarding(
    client: TestClient,
    hearing_role: str,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-linked-ip-hearing-offboarding",
        email="owner@linked-ip-hearing-offboarding.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@linked-ip-hearing-offboarding.example",
        full_name="Linked IP Hearing Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@linked-ip-hearing-offboarding.example",
        full_name="Linked IP Hearing Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])

    active_roles: dict[str, object] = {
        "responsible_membership_id": None,
        "attendee_membership_ids_json": [],
        "reminder_policy_json": {
            "recipient_membership_ids": [],
            "escalation_membership_id": None,
        },
    }
    if hearing_role == "responsible":
        active_roles["responsible_membership_id"] = target_id
    elif hearing_role == "attendee":
        active_roles["attendee_membership_ids_json"] = [target_id]
    elif hearing_role == "reminder_recipient":
        active_roles["reminder_policy_json"] = {
            "recipient_membership_ids": [target_id],
            "escalation_membership_id": None,
        }
    else:
        active_roles["reminder_policy_json"] = {
            "recipient_membership_ids": [],
            "escalation_membership_id": target_id,
        }

    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            title="Matter-owned hearing with linked IP work",
            matter_code="LINKED-IP-HEARING-001",
            practice_area="Intellectual Property",
            forum_level="high_court",
            status="active",
        )
        session.add(matter)
        session.flush()
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Linked hearing docket",
            primary_identifier="TM-LINKED-HEARING",
            status="active",
            created_by_membership_id=target_id,
        )
        active_hearing = MatterHearing(
            company_id=company_id,
            matter_id=matter.id,
            hearing_on=date(2026, 11, 2),
            forum_name="Trade Marks Registry",
            purpose=f"Active {hearing_role} proof",
            status="scheduled",
            **active_roles,
        )
        historical_hearing = MatterHearing(
            company_id=company_id,
            matter_id=matter.id,
            hearing_on=date(2025, 11, 2),
            forum_name="Trade Marks Registry",
            purpose="Completed historical role proof",
            status="completed",
            responsible_membership_id=target_id,
            attendee_membership_ids_json=[target_id],
            reminder_policy_json={
                "recipient_membership_ids": [target_id],
                "escalation_membership_id": target_id,
            },
        )
        session.add_all([docket, active_hearing, historical_hearing])
        session.commit()
        active_hearing_id = active_hearing.id
        historical_hearing_id = historical_hearing.id

    generic = client.patch(
        f"/api/companies/current/users/{target_id}",
        headers=auth_headers(owner_token),
        json={"is_active": False},
    )
    assert generic.status_code == 409, generic.text
    assert generic.json()["code"] == "employee_offboarding_required"
    assert generic.json()["live_reference_counts"]["ip_docket_hearings"] == 1

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["can_commit"] is False
    assert body["unsupported_counts"]["ip_docket_hearings"] == 1
    assert [
        row["id"]
        for row in body["unsupported_objects"]
        if row["object_type"] == "ip_docket_hearings"
    ] == [active_hearing_id]
    assert historical_hearing_id not in {
        row["id"] for row in body["unsupported_objects"]
    }

    committed = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert committed.status_code == 400, committed.text
    with get_session_factory()() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        active_hearing = session.get(MatterHearing, active_hearing_id)
        historical_hearing = session.get(MatterHearing, historical_hearing_id)
        assert persisted_target is not None and persisted_target.is_active is True
        assert active_hearing is not None
        assert historical_hearing is not None
        assert active_hearing.status == "scheduled"
        assert historical_hearing.status == "completed"


def test_privileged_offboarding_repairs_legacy_inactive_ip_ownership(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-legacy-inactive-ip-repair",
        email="owner@legacy-inactive-ip-repair.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@legacy-inactive-ip-repair.example",
        full_name="Legacy Inactive IP Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@legacy-inactive-ip-repair.example",
        full_name="Legacy Inactive IP Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    seeded = _seed_standalone_ip_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=replacement_id,
    )
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, target_id)
        assert membership is not None and membership.employee_profile is not None
        membership.is_active = False
        membership.user.is_active = False
        membership.employee_profile.employment_status = "inactive"
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is True
    assert "Employee is already inactive." not in preview.json()["blockers"]

    committed = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={
            "reassign_to_membership_id": replacement_id,
            "notes": "Repair responsibility left by a pre-guard deactivation.",
        },
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["employee"]["membership_active"] is False

    audit = client.get(
        f"/api/companies/current/employees/{target_id}/audit",
        headers=auth_headers(owner_token),
    )
    assert audit.status_code == 200, audit.text
    event = next(
        row
        for row in audit.json()["events"]
        if row["action"] == "employee.offboarding.committed"
    )
    assert event["metadata"]["legacy_inactive_ip_repair"] is True

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, target_id)
        deadline = session.get(MatterDeadline, seeded["deadline_id"])
        uncovered = session.get(MatterDeadline, seeded["no_coverage_deadline_id"])
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert membership is not None and membership.is_active is False
        assert membership.user.is_active is False
        assert deadline is not None
        assert deadline.assignee_membership_id == replacement_id
        assert uncovered is not None
        assert uncovered.assignee_membership_id == replacement_id
        assert coverage is not None
        assert coverage.responsible_membership_id == replacement_id


def test_offboarding_reassigns_uncovered_docket_owned_deadline_on_linked_matter(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-linked-docket-deadline",
        email="owner@linked-docket-deadline.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@linked-docket-deadline.example",
        full_name="Linked Docket Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@linked-docket-deadline.example",
        full_name="Linked Docket Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])

    with get_session_factory()() as session:
        matter = Matter(
            company_id=company_id,
            title="Linked docket-owned deadline matter",
            matter_code="LINKED-IP-001",
            practice_area="Commercial",
            forum_level="high_court",
            restricted_access=False,
        )
        session.add(matter)
        session.flush()
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter.id,
            record_type="trademark",
            title="Linked docket record",
            primary_identifier="TM-LINKED-DOCKET",
            status="active",
            created_by_membership_id=target_id,
        )
        session.add(docket)
        session.flush()
        deadline = MatterDeadline(
            company_id=company_id,
            matter_id=None,
            ip_docket_id=docket.id,
            source="custom",
            kind="response",
            title="Respond on linked docket",
            due_on=date(2026, 11, 1),
            assignee_membership_id=target_id,
            created_by_membership_id=target_id,
        )
        session.add(deadline)
        session.commit()
        matter_id = matter.id
        deadline_id = deadline.id

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is True
    assert preview.json()["supported_counts"]["matter_deadlines"] == 1
    deadline_object = next(
        row
        for row in preview.json()["supported_objects"]
        if row["object_type"] == "matter_deadlines"
    )
    assert deadline_object["id"] == deadline_id
    assert deadline_object["matter_id"] == matter_id

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 200, commit.text
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, target_id)
        deadline = session.get(MatterDeadline, deadline_id)
        assert membership is not None and membership.is_active is False
        assert deadline is not None
        assert deadline.matter_id is None
        assert deadline.assignee_membership_id == replacement_id


@pytest.mark.parametrize("auxiliary_role", ["pending", "escalation"])
def test_offboarding_blocks_each_operational_auxiliary_coverage_role(
    client: TestClient,
    auxiliary_role: str,
) -> None:
    """Auxiliary accountability must be resolved, while history stays inert."""

    boot = _bootstrap(
        client,
        slug="lw-s8-ip-auxiliary-offboarding",
        email="owner@ip-auxiliary-offboarding.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@ip-auxiliary-offboarding.example",
        full_name="IP Auxiliary Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@ip-auxiliary-offboarding.example",
        full_name="IP Auxiliary Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    seeded = _seed_standalone_ip_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=replacement_id,
    )

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert coverage is not None
        coverage.responsible_membership_id = replacement_id
        coverage.pending_replacement_membership_id = (
            target_id if auxiliary_role == "pending" else replacement_id
        )
        coverage.replacement_decision = "pending"
        coverage.emergency_escalation_membership_id = (
            target_id if auxiliary_role == "escalation" else None
        )
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["can_commit"] is False
    blocker_text = " ".join(preview_body["blockers"]).lower()
    expected_blocker = (
        "pending ip coverage replacement"
        if auxiliary_role == "pending"
        else "decline-escalation"
    )
    unexpected_blocker = (
        "decline-escalation"
        if auxiliary_role == "pending"
        else "pending ip coverage replacement"
    )
    assert expected_blocker in blocker_text
    assert unexpected_blocker not in blocker_text
    assert preview_body["supported_counts"]["ip_deadline_coverages"] == 0
    auxiliary_type = (
        "ip_coverage_pending_replacements"
        if auxiliary_role == "pending"
        else "ip_coverage_emergency_escalations"
    )
    assert preview_body["unsupported_counts"][auxiliary_type] == 1
    auxiliary_objects = [
        row
        for row in preview_body["unsupported_objects"]
        if row["object_type"] == auxiliary_type
    ]
    assert auxiliary_objects == [
        {
            "object_type": auxiliary_type,
            "id": seeded["coverage_id"],
            "label": "TM-OFFBOARD-STANDALONE - Renew standalone trademark",
            "relation": (
                "pending replacement; resolve before offboarding"
                if auxiliary_role == "pending"
                else "decline escalation; reassign before offboarding"
            ),
            "supported": False,
            "matter_id": None,
        }
    ]

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 400, commit.text

    with get_session_factory()() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        historical = session.get(IpDeadlineCoverage, seeded["historical_coverage_id"])
        assert persisted_target is not None and persisted_target.is_active is True
        assert coverage is not None
        assert coverage.responsible_membership_id == replacement_id
        assert coverage.pending_replacement_membership_id == (
            target_id if auxiliary_role == "pending" else replacement_id
        )
        assert coverage.emergency_escalation_membership_id == (
            target_id if auxiliary_role == "escalation" else None
        )
        assert coverage.reassignment_version == 1
        assert historical is not None
        assert historical.coverage_status == "completed"
        assert historical.pending_replacement_membership_id == target_id
        assert historical.emergency_escalation_membership_id == target_id


def test_offboarding_preview_predicts_restricted_standalone_ip_refusal(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-restricted-ip-offboarding",
        email="owner@restricted-ip-offboarding.example",
    )
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@restricted-ip-offboarding.example",
        full_name="Restricted IP Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@restricted-ip-offboarding.example",
        full_name="Restricted IP Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    seeded = _seed_standalone_ip_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=replacement_id,
    )

    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, seeded["docket_id"])
        assert docket is not None
        docket.restricted = True
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=docket.id,
                membership_id=target_id,
                reason="Departing responsible member retained access.",
                granted_by_membership_id=owner_id,
            )
        )
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "cannot access every affected ip docket" in " ".join(preview.json()["blockers"]).lower()

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 400, commit.text

    with get_session_factory()() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        persisted_deadline = session.get(MatterDeadline, seeded["deadline_id"])
        persisted_coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert persisted_target is not None and persisted_target.is_active is True
        assert persisted_deadline is not None
        assert persisted_deadline.assignee_membership_id == target_id
        assert persisted_coverage is not None
        assert persisted_coverage.responsible_membership_id == target_id
        assert persisted_coverage.reassignment_version == 1


def test_offboarding_refuses_admin_as_coverage_replacement_and_escalation(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-admin-replacement-escalation",
        email="owner@admin-replacement-escalation.example",
    )
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@admin-replacement-escalation.example",
        full_name="Admin Replacement Target",
    )
    target_id = str(target["employee"]["membership_id"])
    seeded = _seed_standalone_ip_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=owner_id,
    )

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": owner_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "decline-escalation owner" in " ".join(preview.json()["blockers"]).lower()

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": owner_id},
    )
    assert commit.status_code == 400, commit.text
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert membership is not None and membership.is_active is True
        assert coverage is not None
        assert coverage.responsible_membership_id == target_id
        assert coverage.reassignment_version == 1


@pytest.mark.parametrize(
    "active_role",
    ["responsible", "backup", "pending", "escalation", "standalone_assignee"],
)
def test_generic_deactivation_requires_offboarding_for_each_active_ip_role(
    client: TestClient,
    active_role: str,
) -> None:
    role_slug = active_role.replace("_", "-")
    boot = _bootstrap(
        client,
        slug=f"lw-s8-generic-deactivate-{role_slug}",
        email=f"owner@generic-deactivate-{role_slug}.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email=f"target@generic-deactivate-{role_slug}.example",
        full_name="Generic Deactivation Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email=f"replacement@generic-deactivate-{role_slug}.example",
        full_name="Generic Deactivation Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    seeded = _seed_standalone_ip_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=replacement_id,
    )

    with get_session_factory()() as session:
        covered_deadline = session.get(MatterDeadline, seeded["deadline_id"])
        uncovered_deadline = session.get(MatterDeadline, seeded["no_coverage_deadline_id"])
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert covered_deadline is not None
        assert uncovered_deadline is not None
        assert coverage is not None
        covered_deadline.assignee_membership_id = replacement_id
        uncovered_deadline.assignee_membership_id = replacement_id
        coverage.responsible_membership_id = replacement_id
        coverage.backup_membership_id = None
        coverage.pending_replacement_membership_id = None
        coverage.replacement_decision = "none"
        coverage.emergency_escalation_membership_id = None
        if active_role == "responsible":
            coverage.responsible_membership_id = target_id
        elif active_role == "backup":
            coverage.backup_membership_id = target_id
        elif active_role == "pending":
            coverage.pending_replacement_membership_id = target_id
            coverage.replacement_decision = "pending"
        elif active_role == "escalation":
            coverage.pending_replacement_membership_id = replacement_id
            coverage.replacement_decision = "pending"
            coverage.emergency_escalation_membership_id = target_id
        else:
            uncovered_deadline.assignee_membership_id = target_id
        session.commit()

    responses = [
        client.patch(
            f"/api/companies/current/employees/{target_id}",
            headers=auth_headers(owner_token),
            json={"employment_status": "inactive"},
        ),
        client.patch(
            f"/api/companies/current/users/{target_id}",
            headers=auth_headers(owner_token),
            json={"is_active": False},
        ),
    ]
    for response in responses:
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "employee_offboarding_required"

    with get_session_factory()() as session:
        persisted_target = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        uncovered_deadline = session.get(MatterDeadline, seeded["no_coverage_deadline_id"])
        assert persisted_target is not None
        assert persisted_target.is_active is True
        assert persisted_target.user.is_active is True
        assert coverage is not None
        assert coverage.responsible_membership_id == (
            target_id if active_role == "responsible" else replacement_id
        )
        assert coverage.backup_membership_id == (
            target_id if active_role == "backup" else None
        )
        assert coverage.pending_replacement_membership_id == (
            target_id
            if active_role == "pending"
            else replacement_id
            if active_role == "escalation"
            else None
        )
        assert coverage.emergency_escalation_membership_id == (
            target_id if active_role == "escalation" else None
        )
        assert coverage.reassignment_version == 1
        assert uncovered_deadline is not None
        assert uncovered_deadline.assignee_membership_id == (
            target_id if active_role == "standalone_assignee" else replacement_id
        )


def test_generic_deactivation_allows_only_terminal_ip_history(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-generic-terminal-history",
        email="owner@generic-terminal-history.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@generic-terminal-history.example",
        full_name="Terminal History Replacement",
    )
    replacement_id = str(replacement["employee"]["membership_id"])
    cases: list[tuple[str, str, dict[str, str]]] = []
    for endpoint_kind in ("employee", "company_user"):
        target = _create_employee(
            client,
            owner_token,
            email=f"target-{endpoint_kind}@generic-terminal-history.example",
            full_name=f"Terminal History {endpoint_kind}",
        )
        target_id = str(target["employee"]["membership_id"])
        seeded = _seed_standalone_ip_owned_objects(
            company_id=company_id,
            target_membership_id=target_id,
            replacement_membership_id=replacement_id,
            identifier_suffix=endpoint_kind,
        )
        cases.append((endpoint_kind, target_id, seeded))

    with get_session_factory()() as session:
        for _endpoint_kind, _target_id, seeded in cases:
            for docket_key in ("docket_id", "no_coverage_docket_id"):
                docket = session.get(IpDocketRecord, seeded[docket_key])
                assert docket is not None
                docket.status = "closed"
                docket.is_active = False
            for deadline_key in ("deadline_id", "no_coverage_deadline_id"):
                deadline = session.get(MatterDeadline, seeded[deadline_key])
                assert deadline is not None
                deadline.status = "done"
            coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
            assert coverage is not None
            coverage.coverage_status = "completed"
        session.commit()

    for endpoint_kind, target_id, _seeded in cases:
        if endpoint_kind == "employee":
            response = client.patch(
                f"/api/companies/current/employees/{target_id}",
                headers=auth_headers(owner_token),
                json={"employment_status": "inactive"},
            )
        else:
            response = client.patch(
                f"/api/companies/current/users/{target_id}",
                headers=auth_headers(owner_token),
                json={"is_active": False},
            )
        assert response.status_code == 200, response.text

    with get_session_factory()() as session:
        for _endpoint_kind, target_id, seeded in cases:
            target = session.get(CompanyMembership, target_id)
            history = session.get(IpDeadlineCoverage, seeded["historical_coverage_id"])
            assert target is not None and target.is_active is False
            assert history is not None and history.coverage_status == "completed"
            assert history.pending_replacement_membership_id == target_id
            assert history.emergency_escalation_membership_id == target_id


@pytest.mark.parametrize("endpoint_kind", ["employee", "company_user", "offboarding"])
def test_generic_deactivation_tombstones_every_departing_calendar_projection(
    client: TestClient,
    endpoint_kind: str,
) -> None:
    """A stale external task/hearing/deadline copy cannot outlive its member."""

    endpoint_slug = endpoint_kind.replace("_", "-")
    boot = _bootstrap(
        client,
        slug=f"lw-s8-calendar-tombstone-{endpoint_slug}",
        email=f"owner@calendar-tombstone-{endpoint_slug}.example",
    )
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email=f"target@calendar-tombstone-{endpoint_slug}.example",
        full_name="Calendar Tombstone Target",
    )
    target_id = str(target["employee"]["membership_id"])
    with get_session_factory()() as session:
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=target_id,
            provider="outlook",
            status="connected",
            encrypted_token_ref="departing-calendar",
        )
        session.add(connection)
        session.flush()
        syncs = [
            CalendarEventSync(
                company_id=company_id,
                calendar_connection_id=connection.id,
                source_type=source_type,
                source_id=f"stale-{source_type}",
                provider_event_id=("remote-task-event" if source_type == "matter_task" else None),
                sync_status=(
                    CalendarEventSyncStatus.SYNCED
                    if source_type == "matter_task"
                    else CalendarEventSyncStatus.RETRY_SCHEDULED
                ),
            )
            for source_type in ("matter_task", "matter_hearing", "matter_deadline")
        ]
        session.add_all(syncs)
        session.commit()
        sync_ids = {row.source_type: row.id for row in syncs}

    if endpoint_kind == "employee":
        response = client.patch(
            f"/api/companies/current/employees/{target_id}",
            headers=auth_headers(owner_token),
            json={"employment_status": "inactive"},
        )
    elif endpoint_kind == "company_user":
        response = client.patch(
            f"/api/companies/current/users/{target_id}",
            headers=auth_headers(owner_token),
            json={"is_active": False},
        )
    else:
        response = client.post(
            f"/api/companies/current/employees/{target_id}/offboarding/commit",
            headers=auth_headers(owner_token),
            json={"reassign_to_membership_id": owner_id},
        )
    assert response.status_code == 200, response.text

    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, target_id)
        assert membership is not None and membership.is_active is False
        assert session.get(
            CalendarEventSync, sync_ids["matter_task"]
        ).sync_status == CalendarEventSyncStatus.DELETE_PENDING
        for source_type in ("matter_hearing", "matter_deadline"):
            row = session.get(CalendarEventSync, sync_ids[source_type])
            assert row is not None
            assert row.sync_status == CalendarEventSyncStatus.DELETED


def test_generic_deactivation_ignores_resolved_auxiliary_coverage_metadata(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-resolved-coverage-metadata",
        email="owner@resolved-coverage-metadata.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="target@resolved-coverage-metadata.example",
        full_name="Resolved Metadata Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement@resolved-coverage-metadata.example",
        full_name="Resolved Metadata Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    seeded = _seed_standalone_ip_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
        replacement_membership_id=replacement_id,
    )

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        covered_deadline = session.get(MatterDeadline, seeded["deadline_id"])
        uncovered_deadline = session.get(MatterDeadline, seeded["no_coverage_deadline_id"])
        assert coverage is not None
        assert covered_deadline is not None
        assert uncovered_deadline is not None
        coverage.responsible_membership_id = replacement_id
        coverage.pending_replacement_membership_id = target_id
        coverage.replacement_decision = "accepted"
        coverage.emergency_escalation_membership_id = target_id
        covered_deadline.assignee_membership_id = replacement_id
        uncovered_deadline.assignee_membership_id = replacement_id
        session.commit()

    response = client.patch(
        f"/api/companies/current/employees/{target_id}",
        headers=auth_headers(owner_token),
        json={"employment_status": "inactive"},
    )
    assert response.status_code == 200, response.text
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, seeded["coverage_id"])
        assert membership is not None and membership.is_active is False
        assert coverage is not None
        assert coverage.pending_replacement_membership_id == target_id
        assert coverage.replacement_decision == "accepted"
        assert coverage.emergency_escalation_membership_id == target_id


def test_offboarding_refuses_to_replace_backup_with_existing_primary(
    client: TestClient,
) -> None:
    """A departure cannot silently collapse distinct IP deadline coverage."""

    boot = _bootstrap(
        client,
        slug="lw-s8-distinct-backup",
        email="owner@distinct-backup-lws8.example",
    )
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="departing-backup@lws8.example",
        full_name="Departing Backup",
    )
    target_id = str(target["employee"]["membership_id"])
    _complete_setup(
        client,
        str(target["setup"]["debug_token"]),
        password="DepartingBackup123!",
    )
    seeded = _seed_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
    )

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["ip_coverage_id"])
        assert coverage is not None
        coverage.responsible_membership_id = owner_id
        coverage.backup_membership_id = target_id
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": owner_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "distinct ip deadline backup" in " ".join(preview.json()["blockers"]).lower()

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": owner_id},
    )
    assert commit.status_code == 400, commit.text

    with get_session_factory()() as session:
        target_membership = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, seeded["ip_coverage_id"])
        assert target_membership is not None and target_membership.is_active is True
        assert coverage is not None
        assert coverage.responsible_membership_id == owner_id
        assert coverage.backup_membership_id == target_id


def test_offboarding_refuses_to_replace_primary_with_existing_backup(
    client: TestClient,
) -> None:
    """Preview and commit agree when the replacement is already the backup."""

    boot = _bootstrap(
        client,
        slug="lw-s8-distinct-primary",
        email="owner@distinct-primary-lws8.example",
    )
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="departing-primary@lws8.example",
        full_name="Departing Primary",
    )
    target_id = str(target["employee"]["membership_id"])
    _complete_setup(
        client,
        str(target["setup"]["debug_token"]),
        password="DepartingPrimary123!",
    )
    seeded = _seed_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
    )

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["ip_coverage_id"])
        assert coverage is not None
        assert coverage.responsible_membership_id == target_id
        coverage.backup_membership_id = owner_id
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": owner_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "distinct ip deadline backup" in " ".join(preview.json()["blockers"]).lower()

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": owner_id},
    )
    assert commit.status_code == 400, commit.text

    with get_session_factory()() as session:
        target_membership = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, seeded["ip_coverage_id"])
        assert target_membership is not None and target_membership.is_active is True
        assert coverage is not None
        assert coverage.responsible_membership_id == target_id
        assert coverage.backup_membership_id == owner_id


def test_offboarding_preview_blocks_backup_as_decline_escalation(
    client: TestClient,
) -> None:
    """Preview mirrors the commit's admin fallback for an immediate transfer."""

    boot = _bootstrap(
        client,
        slug="lw-s8-distinct-escalation",
        email="owner@distinct-escalation-lws8.example",
    )
    owner_token = str(boot["access_token"])
    owner_id = str(boot["membership"]["id"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="departing-escalation@lws8.example",
        full_name="Departing Escalation",
    )
    target_id = str(target["employee"]["membership_id"])
    _complete_setup(
        client,
        str(target["setup"]["debug_token"]),
        password="DepartingEscalation123!",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="replacement-escalation@lws8.example",
        full_name="Replacement Escalation",
    )
    replacement_id = str(replacement["employee"]["membership_id"])
    _complete_setup(
        client,
        str(replacement["setup"]["debug_token"]),
        password="ReplacementEscalation123!",
    )
    seeded = _seed_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
    )

    with get_session_factory()() as session:
        coverage = session.get(IpDeadlineCoverage, seeded["ip_coverage_id"])
        assert coverage is not None
        assert coverage.responsible_membership_id == target_id
        coverage.backup_membership_id = owner_id
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "distinct ip deadline backup" in " ".join(preview.json()["blockers"]).lower()

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 400, commit.text

    with get_session_factory()() as session:
        target_membership = session.get(CompanyMembership, target_id)
        coverage = session.get(IpDeadlineCoverage, seeded["ip_coverage_id"])
        assert target_membership is not None and target_membership.is_active is True
        assert coverage is not None
        assert coverage.responsible_membership_id == target_id
        assert coverage.backup_membership_id == owner_id


def test_offboarding_shared_global_user_preserves_other_tenant_access(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(
        client,
        slug="lw-s8-shared-a",
        email="owner@shared-a-lws8.example",
    )
    token_a = str(boot_a["access_token"])
    target = _create_employee(
        client,
        token_a,
        email="shared-user@lws8.example",
        full_name="Shared User",
    )
    replacement = _create_employee(
        client,
        token_a,
        email="shared-replacement@lws8.example",
        full_name="Shared Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    _complete_setup(
        client,
        str(target["setup"]["debug_token"]),
        password="SharedUser123!",
    )
    _complete_setup(
        client,
        str(replacement["setup"]["debug_token"]),
        password="SharedReplacement123!",
    )
    tenant_a_login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "lw-s8-shared-a",
            "email": "shared-user@lws8.example",
            "password": "SharedUser123!",
        },
    )
    assert tenant_a_login.status_code == 200, tenant_a_login.text
    tenant_a_token = str(tenant_a_login.json()["access_token"])

    boot_b = _bootstrap(
        client,
        slug="lw-s8-shared-b",
        email="owner@shared-b-lws8.example",
    )
    tenant_b_employee = _bulk_import_employee(
        client,
        str(boot_b["access_token"]),
        full_name="Shared User",
        email="shared-user@lws8.example",
    )
    tenant_b_membership_id = str(tenant_b_employee["employee"]["membership_id"])
    _complete_setup(
        client,
        str(tenant_b_employee["setup"]["debug_token"]),
        password="SharedUser123!",
    )
    tenant_b_login = client.post(
        "/api/auth/login",
        json={
            "company_slug": "lw-s8-shared-b",
            "email": "shared-user@lws8.example",
            "password": "SharedUser123!",
        },
    )
    assert tenant_b_login.status_code == 200, tenant_b_login.text
    tenant_b_token = str(tenant_b_login.json()["access_token"])

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(token_a),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 200, commit.text
    commit_body = commit.json()
    assert commit_body["employee"]["membership_active"] is False
    assert commit_body["employee"]["user_active"] is True

    stale_a = client.get("/api/auth/me", headers=auth_headers(tenant_a_token))
    assert stale_a.status_code in {401, 403}
    login_a = client.post(
        "/api/auth/login",
        json={
            "company_slug": "lw-s8-shared-a",
            "email": "shared-user@lws8.example",
            "password": "SharedUser123!",
        },
    )
    assert login_a.status_code != 200

    still_active_b = client.get("/api/auth/me", headers=auth_headers(tenant_b_token))
    assert still_active_b.status_code == 200, still_active_b.text
    login_b = client.post(
        "/api/auth/login",
        json={
            "company_slug": "lw-s8-shared-b",
            "email": "shared-user@lws8.example",
            "password": "SharedUser123!",
        },
    )
    assert login_b.status_code == 200, login_b.text

    factory = get_session_factory()
    with factory() as session:
        tenant_a_membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.id == target_id)
        )
        tenant_b_membership = session.scalar(
            select(CompanyMembership).where(CompanyMembership.id == tenant_b_membership_id)
        )
        assert tenant_a_membership is not None
        assert tenant_b_membership is not None
        assert tenant_a_membership.is_active is False
        assert tenant_b_membership.is_active is True
        assert tenant_b_membership.user.is_active is True


def test_company_user_deactivation_is_tenant_scoped_and_preserves_shared_user(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(
        client,
        slug="lw-s8-generic-shared-a",
        email="owner@generic-shared-a.example",
    )
    token_a = str(boot_a["access_token"])
    target_a = _create_employee(
        client,
        token_a,
        email="generic-shared-user@example.com",
        full_name="Generic Shared User",
    )
    target_a_id = str(target_a["employee"]["membership_id"])

    boot_b = _bootstrap(
        client,
        slug="lw-s8-generic-shared-b",
        email="owner@generic-shared-b.example",
    )
    token_b = str(boot_b["access_token"])
    company_b_id = str(boot_b["company"]["id"])
    target_b = _bulk_import_employee(
        client,
        token_b,
        full_name="Generic Shared User",
        email="generic-shared-user@example.com",
    )
    target_b_id = str(target_b["employee"]["membership_id"])
    replacement_b = _create_employee(
        client,
        token_b,
        email="generic-shared-replacement@example.com",
        full_name="Generic Shared Replacement",
    )
    replacement_b_id = str(replacement_b["employee"]["membership_id"])
    seeded_b = _seed_standalone_ip_owned_objects(
        company_id=company_b_id,
        target_membership_id=target_b_id,
        replacement_membership_id=replacement_b_id,
    )

    response = client.patch(
        f"/api/companies/current/users/{target_a_id}",
        headers=auth_headers(token_a),
        json={"is_active": False},
    )
    assert response.status_code == 200, response.text
    assert response.json()["membership_active"] is False
    assert response.json()["user_active"] is True

    with get_session_factory()() as session:
        membership_a = session.get(CompanyMembership, target_a_id)
        membership_b = session.get(CompanyMembership, target_b_id)
        deadline_b = session.get(MatterDeadline, seeded_b["deadline_id"])
        coverage_b = session.get(IpDeadlineCoverage, seeded_b["coverage_id"])
        assert membership_a is not None and membership_a.is_active is False
        assert membership_b is not None and membership_b.is_active is True
        assert membership_b.user_id == membership_a.user_id
        assert membership_b.user.is_active is True
        assert deadline_b is not None
        assert deadline_b.assignee_membership_id == target_b_id
        assert coverage_b is not None
        assert coverage_b.responsible_membership_id == target_b_id


def test_offboarding_preserves_ethical_walls_by_rejecting_walled_replacement(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-wall",
        email="owner@wall-lws8.example",
    )
    owner_token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    target = _create_employee(
        client,
        owner_token,
        email="wall-target@lws8.example",
        full_name="Wall Target",
    )
    replacement = _create_employee(
        client,
        owner_token,
        email="wall-replacement@lws8.example",
        full_name="Wall Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    replacement_id = str(replacement["employee"]["membership_id"])
    _complete_setup(
        client,
        str(target["setup"]["debug_token"]),
        password="WallTarget123!",
    )
    _complete_setup(
        client,
        str(replacement["setup"]["debug_token"]),
        password="WallReplacement123!",
    )
    seeded = _seed_owned_objects(
        company_id=company_id,
        target_membership_id=target_id,
    )
    factory = get_session_factory()
    with factory() as session:
        session.add(
            EthicalWall(
                matter_id=seeded["matter_id"],
                excluded_membership_id=replacement_id,
                reason="conflict",
                created_by_membership_id=str(boot["membership"]["id"]),
            )
        )
        session.commit()

    preview = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_commit"] is False
    assert "ethically walled" in " ".join(preview.json()["blockers"]).lower()

    commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement_id},
    )
    assert commit.status_code == 400, commit.text
    with factory() as session:
        matter = session.get(Matter, seeded["matter_id"])
        assert matter is not None
        assert matter.assignee_membership_id == target_id


def test_offboarding_replacement_must_be_active_and_same_tenant(
    client: TestClient,
) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-tenant-a",
        email="owner@tenant-a-lws8.example",
    )
    owner_token = str(boot["access_token"])
    target = _create_employee(
        client,
        owner_token,
        email="tenant-target@lws8.example",
        full_name="Tenant Target",
    )
    inactive = _create_employee(
        client,
        owner_token,
        email="inactive-replacement@lws8.example",
        full_name="Inactive Replacement",
    )
    target_id = str(target["employee"]["membership_id"])
    inactive_id = str(inactive["employee"]["membership_id"])
    _complete_setup(
        client,
        str(target["setup"]["debug_token"]),
        password="TenantTarget123!",
    )
    _complete_setup(
        client,
        str(inactive["setup"]["debug_token"]),
        password="InactiveReplacement123!",
    )
    deactivate = client.patch(
        f"/api/companies/current/employees/{inactive_id}",
        headers=auth_headers(owner_token),
        json={"employment_status": "inactive"},
    )
    assert deactivate.status_code == 200, deactivate.text

    inactive_commit = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": inactive_id},
    )
    assert inactive_commit.status_code == 400

    boot_b = _bootstrap(
        client,
        slug="lw-s8-tenant-b",
        email="owner@tenant-b-lws8.example",
    )
    other = _create_employee(
        client,
        str(boot_b["access_token"]),
        email="other-tenant@lws8.example",
        full_name="Other Tenant",
    )
    cross_tenant = client.post(
        f"/api/companies/current/employees/{target_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": other["employee"]["membership_id"]},
    )
    assert cross_tenant.status_code == 404


def test_last_active_owner_cannot_be_offboarded(client: TestClient) -> None:
    boot = _bootstrap(
        client,
        slug="lw-s8-last-owner",
        email="owner@last-owner-lws8.example",
    )
    owner_token = str(boot["access_token"])
    replacement = _create_employee(
        client,
        owner_token,
        email="owner-replacement@lws8.example",
        full_name="Owner Replacement",
    )
    _complete_setup(
        client,
        str(replacement["setup"]["debug_token"]),
        password="OwnerReplacement123!",
    )

    owner_id = str(boot["membership"]["id"])
    preview = client.post(
        f"/api/companies/current/employees/{owner_id}/offboarding/preview",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement["employee"]["membership_id"]},
    )
    assert preview.status_code == 200, preview.text
    blockers = " ".join(preview.json()["blockers"])
    assert "last active owner" in blockers

    commit = client.post(
        f"/api/companies/current/employees/{owner_id}/offboarding/commit",
        headers=auth_headers(owner_token),
        json={"reassign_to_membership_id": replacement["employee"]["membership_id"]},
    )
    assert commit.status_code == 400
    factory = get_session_factory()
    with factory() as session:
        owner = session.scalar(select(CompanyMembership).where(CompanyMembership.id == owner_id))
        assert owner is not None
        assert owner.is_active is True
