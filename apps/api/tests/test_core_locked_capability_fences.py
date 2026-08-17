from __future__ import annotations

import inspect
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AuditEvent,
    Communication,
    Company,
    CompanyMembership,
    CompanyNotice,
    CompanyNoticeMatterLink,
    CustomRole,
    IpDocketQueue,
    MatterDeadline,
    MembershipRole,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.employees import EmployeeOffboardingRequest
from caseops_api.schemas.ip_operations import IpDocketQueueSaveRequest
from caseops_api.services import (
    deadlines,
    employee_imports,
    employees,
    ip_deadline_workflow,
    ip_operations,
    ip_workspace,
    shared_work,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _particulars


def _create_matter(client: TestClient, token: str) -> dict:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Immutable deadline history",
            "matter_code": "CORE-DEADLINE-HISTORY",
            "practice_area": "litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "client_name": "History Client",
            "opposing_party": "History Counterparty",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _lifecycle(
    client: TestClient,
    token: str,
    matter: dict,
    *,
    to_status: str,
) -> dict:
    response = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": to_status,
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": "Lifecycle history regression requires an authoritative transition",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_disposal_neutralized_deadline_rejects_every_patch_and_transition(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _create_matter(client, token)
    created = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=auth_headers(token),
        json={
            "title": "Historical filing",
            "notes": "Original evidence",
            "due_on": (date.today() + timedelta(days=20)).isoformat(),
            "assignee_membership_id": membership_id,
        },
    )
    assert created.status_code == 200, created.text
    deadline_id = str(created.json()["id"])

    disposed = _lifecycle(client, token, matter, to_status="disposed")
    _lifecycle(client, token, disposed, to_status="intake")

    with get_session_factory()() as session:
        row = session.get(MatterDeadline, deadline_id)
        assert row is not None
        before = (
            row.title,
            row.notes,
            row.due_on,
            row.status,
            row.assignee_membership_id,
            row.completed_at,
            row.cancelled_by_matter_disposal,
            row.neutralized_at,
            row.updated_at,
        )

    for payload in (
        {"title": "Mutated historical title"},
        {"notes": "Mutated historical notes"},
        {"due_on": (date.today() + timedelta(days=40)).isoformat()},
        {"assignee_membership_id": membership_id},
        {"status": "cancelled"},
    ):
        denied = client.patch(
            f"/api/matters/{matter['id']}/deadlines/{deadline_id}",
            headers=auth_headers(token),
            json=payload,
        )
        assert denied.status_code == 409, denied.text
        assert denied.json()["code"] == "deadline_lifecycle_history_immutable"

    with get_session_factory()() as session:
        company = session.scalar(select(Company))
        membership = session.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None
        context = SessionContext(
            company=company,
            membership=membership,
            user=session.get(User, membership.user_id),
        )
        with pytest.raises(HTTPException) as exc_info:
            deadlines.transition_deadline(
                session,
                context=context,
                deadline_id=deadline_id,
                action="cancel",
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "deadline_lifecycle_history_immutable"
        session.rollback()

    with get_session_factory()() as session:
        row = session.get(MatterDeadline, deadline_id)
        assert row is not None
        after = (
            row.title,
            row.notes,
            row.due_on,
            row.status,
            row.assignee_membership_id,
            row.completed_at,
            row.cancelled_by_matter_disposal,
            row.neutralized_at,
            row.updated_at,
        )
        assert after == before


def test_locked_capability_seam_requires_current_fence_and_never_locks_custom_role(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    membership_id = str(bootstrap["membership"]["id"])
    with get_session_factory()() as session:
        membership = session.get(CompanyMembership, membership_id)
        assert membership is not None
        with pytest.raises(RuntimeError, match="Membership/User fence"):
            require_locked_membership_capability(
                session,
                membership,
                "ip:write",
            )
        fenced = lock_company_memberships_for_assignment(
            session,
            company_id=str(bootstrap["company"]["id"]),
            membership_ids={membership_id},
        )[membership_id]
        assert (
            require_locked_membership_capability(session, fenced, "ip:write")
            is fenced
        )

    source = inspect.getsource(require_locked_membership_capability)
    assert "membership_has_capability" in source
    assert "with_for_update" not in source
    assert "populate_existing" in source


@pytest.mark.parametrize(
    "revocation",
    ("fixed_role", "custom_role", "membership_inactive", "user_inactive"),
)
def test_ip_writer_refreshes_actor_and_leaves_no_queue_or_audit_after_revocation(
    client: TestClient,
    revocation: str,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    custom_role_id: str | None = None

    if revocation == "custom_role":
        with get_session_factory()() as setup:
            membership = setup.get(CompanyMembership, membership_id)
            assert membership is not None
            role = CustomRole(
                company_id=company_id,
                name="Temporary IP queue writer",
                slug="temporary-ip-queue-writer",
                base_role=MembershipRole.MEMBER,
                permissions_json=["ip:write"],
                is_system=False,
                is_active=True,
                created_by_membership_id=membership_id,
                updated_by_membership_id=membership_id,
            )
            setup.add(role)
            setup.flush()
            membership.role = MembershipRole.MEMBER
            membership.custom_role_id = role.id
            setup.commit()
            custom_role_id = role.id

    with get_session_factory()() as writer:
        company = writer.get(Company, company_id)
        membership = writer.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None
        user = writer.get(User, membership.user_id)
        assert user is not None
        stale_context = SessionContext(
            company=company,
            membership=membership,
            user=user,
        )
        # Release the read transaction while deliberately retaining stale ORM
        # state. The production helper must refresh it after taking its fence.
        writer.commit()

        with get_session_factory()() as revoker:
            revoked_membership = revoker.get(CompanyMembership, membership_id)
            assert revoked_membership is not None
            revoked_user = revoker.get(User, revoked_membership.user_id)
            assert revoked_user is not None
            if revocation == "fixed_role":
                revoked_membership.role = MembershipRole.VIEWER
            elif revocation == "custom_role":
                role = revoker.get(CustomRole, custom_role_id)
                assert role is not None
                role.permissions_json = ["ip:read"]
            elif revocation == "membership_inactive":
                revoked_membership.is_active = False
            else:
                revoked_user.is_active = False
            revoker.commit()

        with pytest.raises(HTTPException) as exc_info:
            ip_operations.save_ip_docket_queue(
                writer,
                context=stale_context,
                payload=IpDocketQueueSaveRequest(
                    name=f"Denied queue {revocation}",
                    filters={"critical_only": True},
                ),
            )
        assert exc_info.value.status_code == 403
        writer.rollback()

    with get_session_factory()() as verify:
        assert (
            verify.scalar(
                select(func.count(IpDocketQueue.id)).where(
                    IpDocketQueue.company_id == company_id
                )
            )
            == 0
        )
        assert (
            verify.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "ip_docket_queue.saved",
                )
            )
            == 0
        )


def test_offboarding_preview_checks_locked_capability_before_missing_target(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    with get_session_factory()() as writer:
        company = writer.get(Company, company_id)
        membership = writer.get(CompanyMembership, membership_id)
        assert company is not None and membership is not None
        user = writer.get(User, membership.user_id)
        assert user is not None
        stale_context = SessionContext(
            company=company,
            membership=membership,
            user=user,
        )
        writer.commit()

        with get_session_factory()() as revoker:
            revoked_membership = revoker.get(CompanyMembership, membership_id)
            assert revoked_membership is not None
            revoked_membership.role = MembershipRole.VIEWER
            revoker.commit()

        with pytest.raises(HTTPException) as exc_info:
            employees.preview_employee_offboarding(
                writer,
                context=stale_context,
                membership_id="missing-target",
                payload=EmployeeOffboardingRequest(),
            )
        assert exc_info.value.status_code == 403
        writer.rollback()

    with get_session_factory()() as verify:
        assert (
            verify.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.company_id == company_id,
                    AuditEvent.action == "employee.offboarding.previewed",
                )
            )
            == 0
        )


def test_notice_link_and_evidence_discovery_use_fenced_success_paths(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter = _create_matter(client, token)
    created_docket = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": "Fenced evidence mark",
            "matter_id": matter["id"],
            "restricted": False,
            "particulars": _particulars("FENCED EVIDENCE MARK"),
        },
    )
    assert created_docket.status_code == 201, created_docket.text
    docket_id = str(created_docket.json()["id"])

    with get_session_factory()() as session:
        notice = CompanyNotice(
            company_id=company_id,
            created_by_membership_id=membership_id,
            direction="received",
            subject="Fenced registry notice",
        )
        session.add(notice)
        session.flush()
        session.add_all(
            [
                CompanyNoticeMatterLink(
                    company_id=company_id,
                    notice_id=notice.id,
                    matter_id=str(matter["id"]),
                ),
                Communication(
                    company_id=company_id,
                    matter_id=str(matter["id"]),
                    direction="inbound",
                    channel="email",
                    subject="Fenced evidence instruction",
                    body="Proceed with the registry response.",
                    status="logged",
                ),
            ]
        )
        session.commit()
        notice_id = notice.id

    discovered = client.post(
        f"/api/ip/dockets/{docket_id}/evidence/discover",
        headers=headers,
    )
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["discovered_count"] == 2
    assert {
        row["source_type"] for row in discovered.json()["candidates"]
    } == {"company_notice", "communication"}

    linked = client.post(
        f"/api/ip/dockets/{docket_id}/notice-links",
        headers=headers,
        json={
            "notice_id": notice_id,
            "link_kind": "official_notice",
            "accepted_effect": "deadline_candidate",
        },
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["notice_links"][0]["notice_id"] == notice_id


def test_complete_core_writer_inventory_uses_actor_first_exact_capability() -> None:
    common_helpers = (
        ip_operations._lock_assignment_memberships_or_404,
        shared_work._lock_shared_work_memberships,
        ip_deadline_workflow._lock_responsibility_memberships,
    )
    for helper in common_helpers:
        source = inspect.getsource(helper)
        assert "require_locked_membership_capability" in source, helper.__name__
        assert "required_capability" in source, helper.__name__

    docket_helper_source = inspect.getsource(ip_operations._docket_or_404)
    assert "_lock_ip_writer_context" in docket_helper_source
    assert "required_capability" in docket_helper_source

    contracts = (
        (ip_operations.create_ip_docket, "ip:write", "with_for_update"),
        (
            ip_operations.bulk_acknowledge_ip_coverage,
            "ip:write",
            "with_for_update",
        ),
        (
            ip_workspace.upsert_ip_workspace_configuration,
            "ip:taxonomy_admin",
            "for_update=True",
        ),
        (
            ip_workspace.run_ip_workspace_test,
            "ip:taxonomy_admin",
            "for_update=True",
        ),
        (
            ip_workspace.enable_ip_workspace,
            "ip:taxonomy_admin",
            "for_update=True",
        ),
        (
            ip_deadline_workflow.propose_rule_version,
            "ip:rules_propose",
            "with_for_update",
        ),
        (
            ip_deadline_workflow.activate_rule_version,
            "ip:rules_activate",
            "with_for_update",
        ),
        (
            ip_deadline_workflow.transition_rule_version,
            "ip:rules_activate",
            "with_for_update",
        ),
        (
            ip_deadline_workflow.select_company_rule_version,
            "ip:rules_activate",
            "with_for_update",
        ),
        (
            ip_deadline_workflow.propose_calendar_version,
            "ip:rules_propose",
            "with_for_update",
        ),
        (
            ip_deadline_workflow.activate_calendar_version,
            "ip:rules_activate",
            "with_for_update",
        ),
    )
    for writer, capability, parent_lock in contracts:
        source = inspect.getsource(writer)
        assert capability in source, writer.__name__
        fence = (
            "lock_company_memberships_for_assignment"
            if writer
            in {
                ip_operations.create_ip_docket,
                ip_operations.bulk_acknowledge_ip_coverage,
            }
            else "_lock_governance_memberships"
            if writer.__module__.endswith("ip_deadline_workflow")
            else "lock_company_memberships_for_assignment"
        )
        assert source.index(fence) < source.index(parent_lock), writer.__name__

    ip_writer_contracts = (
        (ip_operations.add_ip_notice_link, "ip:write", "_docket_or_404"),
        (
            ip_operations.discover_ip_evidence_candidates,
            "ip:approve",
            "_docket_or_404",
        ),
        (
            ip_operations.add_ip_deadline_incident,
            "ip:approve",
            "_docket_or_404",
        ),
        (
            ip_operations.verify_ip_deadline_incident,
            "ip:approve",
            "_docket_or_404",
        ),
        (
            ip_operations.add_ip_title_interest,
            "ip:approve",
            "_lock_ip_dockets_in_stable_order",
        ),
        (ip_operations.add_ip_cost_item, "ip:fees_manage", "_docket_or_404"),
        (
            ip_operations.create_ip_control_review,
            "ip:write",
            "list_ip_dockets",
        ),
        (
            ip_operations.record_ip_control_review_export,
            "ip:write",
            "_review_or_404",
        ),
        (
            ip_operations.sign_off_ip_control_review,
            "ip:approve",
            "_review_or_404",
        ),
        (ip_operations.save_ip_docket_queue, "ip:write", "session.scalar"),
        (ip_operations.delete_ip_docket_queue, "ip:write", "session.scalar"),
    )
    for writer, capability, first_parent_or_child_access in ip_writer_contracts:
        source = inspect.getsource(writer)
        assert capability in source, writer.__name__
        assert "context = _lock_ip_writer_context" in source, writer.__name__
        assert source.index("context = _lock_ip_writer_context") < source.index(
            first_parent_or_child_access
        ), writer.__name__

    cross_docket_source = inspect.getsource(
        ip_operations._lock_ip_dockets_in_stable_order
    )
    assert cross_docket_source.index("require_locked_membership_capability") < (
        cross_docket_source.index("discovered_rows")
    )
    assert cross_docket_source.index("locked_matters") < cross_docket_source.index(
        "locked_dockets"
    )
    assert ".order_by(Matter.id)" in cross_docket_source
    assert ".order_by(IpDocketRecord.id)" in cross_docket_source

    employee_contracts = (
        employees._create_employee_without_commit,
        employees.update_employee,
        employees.resend_employee_setup,
        employees.issue_employee_password_reset,
    )
    for writer in employee_contracts:
        source = inspect.getsource(writer)
        assert "_lock_employee_writer_context" in source, writer.__name__
    assert inspect.getsource(employees.update_employee).index(
        "_lock_employee_writer_context"
    ) < inspect.getsource(employees.update_employee).index("if not updates")

    for writer in (
        employee_imports.preview_employee_import,
        employee_imports.cancel_employee_import,
    ):
        source = inspect.getsource(writer)
        parent_read = (
            "_load_job"
            if writer is employee_imports.cancel_employee_import
            else "_parse_upload"
        )
        assert source.index("_lock_import_actor") < source.index(parent_read)
    assert inspect.getsource(employee_imports.commit_employee_import).count(
        "_lock_import_actor"
    ) >= 2
    assert "_lock_import_actor" in inspect.getsource(employee_imports._mark_commit_failed)

    offboarding_preview_source = inspect.getsource(
        employees.preview_employee_offboarding
    )
    assert "_lock_employee_writer_context" in offboarding_preview_source
    assert offboarding_preview_source.index("_lock_employee_writer_context") < (
        offboarding_preview_source.index("_build_offboarding_preview")
    )
    employee_fence_source = inspect.getsource(employees._lock_employee_writer_context)
    assert "company:manage_users" in employee_fence_source
    assert "SessionContext(" in employee_fence_source


def test_terminal_endpoint_openapi_and_runtime_problem_details(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    operation = client.get("/openapi.json").json()["paths"][
        "/api/ip/operational-deadlines/{deadline_id}/terminalize"
    ]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/IpOperationalDeadlineTransitionRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/IpOperationalDeadlineRecord"}

    missing = client.post(
        "/api/ip/operational-deadlines/missing-deadline/terminalize",
        headers=auth_headers(str(bootstrap["access_token"])),
        json={"docket_id": "missing-docket", "action": "complete"},
    )
    assert missing.status_code == 404, missing.text
    assert missing.headers["content-type"].startswith("application/problem+json")
    body = missing.json()
    assert body["status"] == 404
    assert body["title"]
    assert body["type"]
    assert body["detail"] == "Deadline not found."
    assert body["instance"]
