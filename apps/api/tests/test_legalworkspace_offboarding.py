from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
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
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    Team,
    TeamMembership,
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
    assert preview_body["supported_counts"]["hearing_reminders"] == 1
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
        grant = session.get(MatterAccessGrant, seeded["grant_id"])
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
        assert reminder is not None and reminder.recipient_membership_id == replacement_id
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
    assert "distinct ip deadline backup" in " ".join(
        preview.json()["blockers"]
    ).lower()

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
    assert "distinct ip deadline backup" in " ".join(
        preview.json()["blockers"]
    ).lower()

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
    assert "distinct ip deadline backup" in " ".join(
        preview.json()["blockers"]
    ).lower()

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
            select(CompanyMembership).where(
                CompanyMembership.id == tenant_b_membership_id
            )
        )
        assert tenant_a_membership is not None
        assert tenant_b_membership is not None
        assert tenant_a_membership.is_active is False
        assert tenant_b_membership.is_active is True
        assert tenant_b_membership.user.is_active is True


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
        owner = session.scalar(
            select(CompanyMembership).where(CompanyMembership.id == owner_id)
        )
        assert owner is not None
        assert owner.is_active is True
