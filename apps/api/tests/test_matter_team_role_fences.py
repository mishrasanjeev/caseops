from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    EthicalWall,
    HearingReminder,
    IpDocketRecord,
    Matter,
    MatterAccessGrant,
    MatterActivity,
    MatterAttachment,
    MatterCourtOrder,
    MatterCourtSyncRun,
    MatterHearing,
    MatterInvoice,
    MatterNote,
    MatterTask,
    MatterTimeEntry,
    Team,
    TeamMembership,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.matters import (
    MatterTaskCreateRequest,
    MatterTaskUpdateRequest,
)
from caseops_api.services import matters as matter_service
from caseops_api.services import teams as team_service
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_member(
    client: TestClient,
    *,
    token: str,
    email: str,
) -> str:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(token),
        json={
            "full_name": "Bounded Role Member",
            "email": email,
            "password": "RoleFencePass123!",
            "role": "member",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["membership_id"])


def _create_matter(
    client: TestClient,
    *,
    token: str,
    code: str,
) -> dict:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Role fence {code}",
            "matter_code": code,
            "practice_area": "IP",
            "forum_level": "high_court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_team(client: TestClient, *, token: str, slug: str) -> dict:
    response = client.post(
        "/api/teams/",
        headers=auth_headers(token),
        json={"name": f"Team {slug}", "slug": slug},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assign_matter_team(
    client: TestClient,
    *,
    token: str,
    matter: dict,
    team_id: str,
) -> dict:
    response = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={
            "team_id": team_id,
            "expected_updated_at": matter["updated_at"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_linked_ip_task(
    *,
    company_id: str,
    matter_id: str,
    owner_membership_id: str,
    created_by_membership_id: str,
    suffix: str,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter_id,
            record_type="trademark",
            title=f"Linked docket {suffix}",
            primary_identifier=f"TM-{suffix}",
            status="active",
            is_active=True,
            restricted=False,
            created_by_membership_id=created_by_membership_id,
        )
        session.add(docket)
        session.flush()
        session.add(
            MatterTask(
                company_id=company_id,
                ip_docket_id=docket.id,
                created_by_membership_id=created_by_membership_id,
                owner_membership_id=owner_membership_id,
                title="Live linked-IP task",
                status="todo",
                priority="high",
            )
        )
        session.commit()
        return docket.id


def _seed_unstable_linked_docket_access(
    *,
    company_id: str,
    matter_id: str,
    actor_membership_id: str,
    candidate_membership_id: str,
    access_case: str,
    suffix: str,
) -> str:
    factory = get_session_factory()
    with factory() as session:
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter_id,
            record_type="trademark",
            title=f"Restricted linked docket {suffix}",
            primary_identifier=f"TM-RESTRICTED-{suffix}",
            status="active",
            is_active=True,
            restricted=True,
            created_by_membership_id=actor_membership_id,
        )
        session.add(docket)
        session.flush()
        session.add(
            MatterAccessGrant(
                company_id=company_id,
                ip_docket_id=docket.id,
                membership_id=actor_membership_id,
                access_level="member",
                reason="Unbounded actor access for the regression fixture.",
                granted_by_membership_id=actor_membership_id,
            )
        )
        if access_case in {"future_matter_wall", "future_docket_wall"}:
            session.add(
                MatterAccessGrant(
                    company_id=company_id,
                    ip_docket_id=docket.id,
                    membership_id=candidate_membership_id,
                    access_level="member",
                    reason="Current access before a scheduled wall activates.",
                    granted_by_membership_id=actor_membership_id,
                )
            )
            session.add(
                EthicalWall(
                    company_id=company_id,
                    matter_id=(
                        matter_id if access_case == "future_matter_wall" else None
                    ),
                    ip_docket_id=(
                        docket.id if access_case == "future_docket_wall" else None
                    ),
                    excluded_membership_id=candidate_membership_id,
                    reason="Scheduled conflict activation.",
                    created_by_membership_id=actor_membership_id,
                    effective_from=datetime.now(UTC) + timedelta(days=1),
                )
            )
        elif access_case == "expiring_docket_grant":
            session.add(
                MatterAccessGrant(
                    company_id=company_id,
                    ip_docket_id=docket.id,
                    membership_id=candidate_membership_id,
                    access_level="member",
                    reason="Current access expires while responsibility remains live.",
                    granted_by_membership_id=actor_membership_id,
                    expires_at=datetime.now(UTC) + timedelta(days=2),
                )
            )
        else:
            raise AssertionError(f"Unknown access case: {access_case}")
        session.commit()
        return docket.id


def test_task_assignment_denial_is_zero_write(client: TestClient) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    member_id = _create_member(
        client,
        token=token,
        email="task-role-denied@example.com",
    )
    matter = _create_matter(client, token=token, code="ROLE-TASK-DENY")
    restricted = client.post(
        f"/api/matters/{matter['id']}/access/restricted",
        headers=auth_headers(token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text

    denied = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={
            "title": "Must not persist",
            "owner_membership_id": member_id,
            "status": "todo",
            "priority": "high",
        },
    )
    assert denied.status_code == 400, denied.text

    factory = get_session_factory()
    with factory() as session:
        count = session.scalar(
            select(func.count(MatterTask.id)).where(MatterTask.matter_id == matter["id"])
        )
    assert count == 0


def test_hearing_escalation_requires_same_durable_matter_access_as_recipient(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    blocked_member_id = _create_member(
        client,
        token=token,
        email="hearing-escalation-denied@example.com",
    )
    matter = _create_matter(client, token=token, code="ROLE-HEARING-DENY")
    restricted = client.post(
        f"/api/matters/{matter['id']}/access/restricted",
        headers=auth_headers(token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text

    denied = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": (datetime.now(UTC) + timedelta(days=30)).date().isoformat(),
            "forum_name": "Delhi High Court",
            "purpose": "Escalation access regression",
            "reminder_recipient_membership_ids": [owner_membership_id],
            "reminder_channels": ["in_app"],
            "escalation_membership_id": blocked_member_id,
            "notification_critical": True,
        },
    )
    assert denied.status_code == 400, denied.text

    factory = get_session_factory()
    with factory() as session:
        count = session.scalar(
            select(func.count(MatterHearing.id)).where(
                MatterHearing.matter_id == matter["id"]
            )
        )
    assert count == 0


def test_team_member_removal_cannot_orphan_live_linked_ip_role(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_id = _create_member(
        client,
        token=token,
        email="team-removal-role@example.com",
    )
    team = _create_team(client, token=token, slug="team-removal-role")
    add = client.post(
        f"/api/teams/{team['id']}/members",
        headers=auth_headers(token),
        json={"membership_id": member_id},
    )
    assert add.status_code == 200, add.text
    matter = _assign_matter_team(
        client,
        token=token,
        matter=_create_matter(client, token=token, code="ROLE-TEAM-REMOVE"),
        team_id=team["id"],
    )
    _seed_linked_ip_task(
        company_id=company_id,
        matter_id=matter["id"],
        owner_membership_id=member_id,
        created_by_membership_id=owner_membership_id,
        suffix="TEAM-REMOVE",
    )
    enabled = client.put(
        "/api/teams/scoping",
        headers=auth_headers(token),
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text

    denied = client.delete(
        f"/api/teams/{team['id']}/members/{member_id}",
        headers=auth_headers(token),
    )
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == (
        "ip_team_access_responsibility_handoff_required"
    )

    factory = get_session_factory()
    with factory() as session:
        membership_still_exists = session.scalar(
            select(TeamMembership.id).where(
                TeamMembership.team_id == team["id"],
                TeamMembership.membership_id == member_id,
            )
        )
    assert membership_still_exists is not None


def test_enabling_team_scoping_cannot_orphan_live_linked_ip_role(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_id = _create_member(
        client,
        token=token,
        email="team-scoping-role@example.com",
    )
    team = _create_team(client, token=token, slug="team-scoping-role")
    matter = _assign_matter_team(
        client,
        token=token,
        matter=_create_matter(client, token=token, code="ROLE-TEAM-SCOPE"),
        team_id=team["id"],
    )
    _seed_linked_ip_task(
        company_id=company_id,
        matter_id=matter["id"],
        owner_membership_id=member_id,
        created_by_membership_id=owner_membership_id,
        suffix="TEAM-SCOPE",
    )

    denied = client.put(
        "/api/teams/scoping",
        headers=auth_headers(token),
        json={"enabled": True},
    )
    assert denied.status_code == 409, denied.text
    assert denied.json()["code"] == (
        "ip_team_access_responsibility_handoff_required"
    )

    factory = get_session_factory()
    with factory() as session:
        enabled = session.scalar(
            select(Company.team_scoping_enabled).where(Company.id == company_id)
        )
        persisted_matter = session.get(Matter, matter["id"])
    assert enabled is False
    assert persisted_matter is not None and persisted_matter.team_id == team["id"]


def test_assigning_matter_team_cannot_orphan_existing_linked_ip_role(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    member_id = _create_member(
        client,
        token=token,
        email="matter-team-access-role@example.com",
    )
    matter = _create_matter(client, token=token, code="ROLE-MATTER-TEAM")
    team = _create_team(client, token=token, slug="matter-team-access-role")
    _seed_linked_ip_task(
        company_id=company_id,
        matter_id=matter["id"],
        owner_membership_id=member_id,
        created_by_membership_id=owner_membership_id,
        suffix="MATTER-TEAM-ACCESS",
    )
    enabled = client.put(
        "/api/teams/scoping",
        headers=auth_headers(token),
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text

    denied = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={
            "team_id": team["id"],
            "expected_updated_at": matter["updated_at"],
        },
    )
    assert denied.status_code == 400, denied.text
    assert "active linked IP record" in denied.text

    factory = get_session_factory()
    with factory() as session:
        persisted = session.get(Matter, matter["id"])
    assert persisted is not None and persisted.team_id is None


@pytest.mark.parametrize(
    "access_case",
    ("future_matter_wall", "expiring_docket_grant"),
)
def test_update_matter_rejects_time_bounded_linked_ip_responsibility(
    client: TestClient,
    access_case: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    actor_membership_id = str(bootstrap["membership"]["id"])
    member_id = _create_member(
        client,
        token=token,
        email=f"matter-role-{access_case}@example.com",
    )
    matter = _create_matter(
        client,
        token=token,
        code=f"ROLE-MATTER-{access_case.upper().replace('_', '-')}",
    )
    _seed_unstable_linked_docket_access(
        company_id=company_id,
        matter_id=matter["id"],
        actor_membership_id=actor_membership_id,
        candidate_membership_id=member_id,
        access_case=access_case,
        suffix=f"MATTER-{access_case.upper()}",
    )

    denied = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={
            "assignee_membership_id": member_id,
            "expected_updated_at": matter["updated_at"],
        },
    )
    assert denied.status_code == 400, denied.text
    assert "durable access" in denied.text

    factory = get_session_factory()
    with factory() as session:
        persisted = session.get(Matter, matter["id"])
    assert persisted is not None
    assert persisted.assignee_membership_id is None


@pytest.mark.parametrize(
    ("writer_kind", "access_case"),
    (
        ("task_owner", "expiring_docket_grant"),
        ("hearing_recipient", "future_docket_wall"),
        ("hearing_escalation", "expiring_docket_grant"),
    ),
)
def test_open_matter_child_roles_require_durable_linked_ip_access(
    client: TestClient,
    writer_kind: str,
    access_case: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    actor_membership_id = str(bootstrap["membership"]["id"])
    member_id = _create_member(
        client,
        token=token,
        email=f"{writer_kind}-{access_case}@example.com",
    )
    matter = _create_matter(
        client,
        token=token,
        code=f"ROLE-{writer_kind.upper().replace('_', '-')}",
    )
    _seed_unstable_linked_docket_access(
        company_id=company_id,
        matter_id=matter["id"],
        actor_membership_id=actor_membership_id,
        candidate_membership_id=member_id,
        access_case=access_case,
        suffix=f"CHILD-{writer_kind.upper()}",
    )

    if writer_kind == "task_owner":
        denied = client.post(
            f"/api/matters/{matter['id']}/tasks",
            headers=auth_headers(token),
            json={
                "title": "Must not create a time-bounded IP role",
                "owner_membership_id": member_id,
                "status": "todo",
                "priority": "high",
            },
        )
    else:
        denied = client.post(
            f"/api/matters/{matter['id']}/hearings",
            headers=auth_headers(token),
            json={
                "hearing_on": (
                    datetime.now(UTC) + timedelta(days=30)
                ).date().isoformat(),
                "forum_name": "Delhi High Court",
                "purpose": "Durable linked-IP participant regression",
                "reminder_recipient_membership_ids": [
                    member_id
                    if writer_kind == "hearing_recipient"
                    else actor_membership_id
                ],
                "reminder_channels": ["in_app"],
                "escalation_membership_id": (
                    member_id
                    if writer_kind == "hearing_escalation"
                    else actor_membership_id
                ),
                "notification_critical": True,
            },
        )
    assert denied.status_code == 400, denied.text
    assert "active linked IP record" in denied.text

    factory = get_session_factory()
    with factory() as session:
        task_count = session.scalar(
            select(func.count(MatterTask.id)).where(MatterTask.matter_id == matter["id"])
        )
        hearing_count = session.scalar(
            select(func.count(MatterHearing.id)).where(
                MatterHearing.matter_id == matter["id"]
            )
        )
    assert task_count == 0
    assert hearing_count == 0


@pytest.mark.parametrize(
    "hearing_role",
    ("responsible", "attendee", "reminder_recipient", "escalation"),
)
def test_hearing_update_fences_every_resulting_participant_against_linked_ip(
    client: TestClient,
    hearing_role: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    actor_membership_id = str(bootstrap["membership"]["id"])
    member_id = _create_member(
        client,
        token=token,
        email=f"hearing-{hearing_role}-linked-ip@example.com",
    )
    matter = _create_matter(
        client,
        token=token,
        code=f"ROLE-HEARING-{hearing_role.upper().replace('_', '-')}",
    )
    _seed_unstable_linked_docket_access(
        company_id=company_id,
        matter_id=matter["id"],
        actor_membership_id=actor_membership_id,
        candidate_membership_id=member_id,
        access_case="future_docket_wall",
        suffix=f"HEARING-{hearing_role.upper()}",
    )
    original_date = (datetime.now(UTC) + timedelta(days=20)).date()
    factory = get_session_factory()
    with factory() as session:
        hearing = MatterHearing(
            company_id=company_id,
            matter_id=matter["id"],
            hearing_on=original_date,
            time_status="time_not_published",
            timezone="Asia/Kolkata",
            reminder_policy_json={
                "recipient_membership_ids": [
                    member_id
                    if hearing_role == "reminder_recipient"
                    else actor_membership_id
                ],
                "escalation_membership_id": (
                    member_id if hearing_role == "escalation" else actor_membership_id
                ),
            },
            attendee_membership_ids_json=[
                member_id if hearing_role == "attendee" else actor_membership_id
            ],
            responsible_membership_id=(
                member_id if hearing_role == "responsible" else actor_membership_id
            ),
            forum_name="Delhi High Court",
            purpose="Existing participant policy",
            status="scheduled",
        )
        session.add(hearing)
        session.commit()
        hearing_id = hearing.id

    denied = client.patch(
        f"/api/matters/{matter['id']}/hearings/{hearing_id}",
        headers=auth_headers(token),
        json={"hearing_on": (original_date + timedelta(days=1)).isoformat()},
    )
    assert denied.status_code == 400, denied.text
    assert "active linked IP record" in denied.text

    with factory() as session:
        persisted = session.get(MatterHearing, hearing_id)
    assert persisted is not None
    assert persisted.hearing_on == original_date
    assert persisted.status == "scheduled"


def test_generated_follow_up_owner_requires_durable_linked_ip_access(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    actor_membership_id = str(bootstrap["membership"]["id"])
    member_id = _create_member(
        client,
        token=token,
        email="follow-up-linked-ip@example.com",
    )
    matter = _create_matter(client, token=token, code="ROLE-FOLLOW-UP-IP")
    _seed_unstable_linked_docket_access(
        company_id=company_id,
        matter_id=matter["id"],
        actor_membership_id=actor_membership_id,
        candidate_membership_id=member_id,
        access_case="expiring_docket_grant",
        suffix="FOLLOW-UP",
    )
    factory = get_session_factory()
    with factory() as session:
        persisted_matter = session.get(Matter, matter["id"])
        assert persisted_matter is not None
        persisted_matter.assignee_membership_id = member_id
        hearing = MatterHearing(
            company_id=company_id,
            matter_id=matter["id"],
            hearing_on=(datetime.now(UTC) + timedelta(days=2)).date(),
            time_status="time_not_published",
            timezone="Asia/Kolkata",
            reminder_policy_json={
                "recipient_membership_ids": [actor_membership_id],
                "escalation_membership_id": actor_membership_id,
            },
            attendee_membership_ids_json=[],
            forum_name="Delhi High Court",
            purpose="Follow-up owner regression",
            status="scheduled",
        )
        session.add(hearing)
        session.commit()
        hearing_id = hearing.id

    denied = client.patch(
        f"/api/matters/{matter['id']}/hearings/{hearing_id}",
        headers=auth_headers(token),
        json={"status": "completed", "create_follow_up": True},
    )
    assert denied.status_code == 400, denied.text
    assert "active linked IP record" in denied.text

    with factory() as session:
        persisted_hearing = session.get(MatterHearing, hearing_id)
        task_count = session.scalar(
            select(func.count(MatterTask.id)).where(MatterTask.matter_id == matter["id"])
        )
    assert persisted_hearing is not None and persisted_hearing.status == "scheduled"
    assert task_count == 0


def _matter_context(
    session,
    *,
    membership_id: str,
) -> SessionContext:
    membership = session.get(CompanyMembership, membership_id)
    assert membership is not None
    return SessionContext(
        company=membership.company,
        membership=membership,
        user=membership.user,
    )


def test_task_create_rejects_dispose_reopen_lifecycle_aba(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    actor_membership_id = str(bootstrap["membership"]["id"])
    matter = _create_matter(client, token=token, code="ROLE-CREATE-ABA")
    factory = get_session_factory()
    with factory() as session:
        context = _matter_context(session, membership_id=actor_membership_id)
        original_lock = matter_service.lock_company_memberships_for_assignment
        injected = False

        def inject_lifecycle_aba(lock_session, **kwargs):
            nonlocal injected
            if not injected:
                injected = True
                lock_session.execute(
                    update(Matter)
                    .where(Matter.id == matter["id"])
                    .values(
                        status="intake",
                        is_active=True,
                        lifecycle_version=Matter.lifecycle_version + 2,
                    )
                )
            return original_lock(lock_session, **kwargs)

        monkeypatch.setattr(
            matter_service,
            "lock_company_memberships_for_assignment",
            inject_lifecycle_aba,
        )
        with pytest.raises(HTTPException) as exc_info:
            matter_service.create_matter_task(
                session,
                context=context,
                matter_id=matter["id"],
                payload=MatterTaskCreateRequest(
                    title="Stale pre-disposal create must fail",
                    status="todo",
                    priority="high",
                ),
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "matter_assignment_fence_changed"
        assert session.scalar(
            select(MatterTask.id).where(
                MatterTask.matter_id == matter["id"],
                MatterTask.title == "Stale pre-disposal create must fail",
            )
        ) is None
        session.rollback()


def test_task_update_rejects_disposal_cancelled_child_aba(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    actor_membership_id = str(bootstrap["membership"]["id"])
    matter = _create_matter(client, token=token, code="ROLE-UPDATE-ABA")
    created = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={
            "title": "Original task history",
            "status": "todo",
            "priority": "medium",
        },
    )
    assert created.status_code == 200, created.text
    task_id = str(created.json()["id"])
    factory = get_session_factory()
    with factory() as session:
        context = _matter_context(session, membership_id=actor_membership_id)
        original_fence = matter_service._lock_matter_assignment_fence
        injected = False

        def inject_child_aba(*args, **kwargs):
            nonlocal injected
            result = original_fence(*args, **kwargs)
            if not injected:
                injected = True
                now = datetime.now(UTC)
                session.execute(
                    update(Matter)
                    .where(Matter.id == matter["id"])
                    .values(lifecycle_version=Matter.lifecycle_version + 2)
                )
                session.execute(
                    update(MatterTask)
                    .where(MatterTask.id == task_id)
                    .values(
                        status="cancelled",
                        completed_at=now,
                        cancelled_by_matter_disposal=True,
                        updated_at=now,
                    )
                )
            return result

        monkeypatch.setattr(
            matter_service,
            "_lock_matter_assignment_fence",
            inject_child_aba,
        )
        with pytest.raises(HTTPException) as exc_info:
            matter_service.update_matter_task(
                session,
                context=context,
                matter_id=matter["id"],
                task_id=task_id,
                payload=MatterTaskUpdateRequest(title="Must not rewrite history"),
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "matter_task_assignment_changed"
        persisted = session.get(MatterTask, task_id)
        assert persisted is not None
        assert persisted.title == "Original task history"
        assert persisted.status == "cancelled"
        assert persisted.cancelled_by_matter_disposal is True
        session.rollback()


def _transition_matter(
    client: TestClient,
    *,
    token: str,
    matter: dict,
    to_status: str,
) -> dict:
    response = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": to_status,
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": f"Role-fence regression transition to {to_status}.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_disposal_neutralized_task_and_hearing_are_fully_immutable_after_reopen(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    actor_id = str(bootstrap["membership"]["id"])
    replacement_id = _create_member(
        client,
        token=token,
        email="immutable-history-replacement@example.com",
    )
    matter = _create_matter(client, token=token, code="ROLE-HISTORY-IMMUTABLE")
    task_response = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={
            "title": "Immutable disposal task",
            "owner_membership_id": actor_id,
            "due_on": (date.today() + timedelta(days=10)).isoformat(),
            "status": "todo",
            "priority": "medium",
        },
    )
    assert task_response.status_code == 200, task_response.text
    hearing_response = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": (date.today() + timedelta(days=20)).isoformat(),
            "forum_name": "Delhi High Court",
            "purpose": "Immutable disposal hearing",
            "reminder_recipient_membership_ids": [actor_id],
            "reminder_channels": ["in_app"],
            "escalation_membership_id": actor_id,
            "notification_critical": True,
        },
    )
    assert hearing_response.status_code == 200, hearing_response.text
    task_id = str(task_response.json()["id"])
    hearing_id = str(hearing_response.json()["id"])
    refreshed_matter = client.get(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
    )
    assert refreshed_matter.status_code == 200, refreshed_matter.text
    matter = refreshed_matter.json()

    disposed = _transition_matter(
        client,
        token=token,
        matter=matter,
        to_status="disposed",
    )
    _transition_matter(
        client,
        token=token,
        matter=disposed,
        to_status="intake",
    )

    factory = get_session_factory()
    with factory() as session:
        activity_before = session.scalar(
            select(func.count(MatterActivity.id)).where(
                MatterActivity.matter_id == matter["id"]
            )
        )
        audit_before = session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.matter_id == matter["id"]
            )
        )
        reminders_before = session.scalar(
            select(func.count(HearingReminder.id)).where(
                HearingReminder.hearing_id == hearing_id
            )
        )

    task_denied = client.patch(
        f"/api/matters/{matter['id']}/tasks/{task_id}",
        headers=auth_headers(token),
        json={
            "title": "Must not rewrite disposal history",
            "owner_membership_id": replacement_id,
            "due_on": (date.today() + timedelta(days=40)).isoformat(),
        },
    )
    assert task_denied.status_code == 409, task_denied.text
    assert task_denied.json()["code"] == "matter_task_lifecycle_history_immutable"

    hearing_denied = client.patch(
        f"/api/matters/{matter['id']}/hearings/{hearing_id}",
        headers=auth_headers(token),
        json={
            "outcome_note": "Must not rewrite disposal history",
            "hearing_on": (date.today() + timedelta(days=50)).isoformat(),
            "time_status": "session",
            "session_label": "Forbidden rewrite",
        },
    )
    assert hearing_denied.status_code == 409, hearing_denied.text
    assert hearing_denied.json()["code"] == (
        "matter_hearing_lifecycle_history_immutable"
    )

    with factory() as session:
        task = session.get(MatterTask, task_id)
        hearing = session.get(MatterHearing, hearing_id)
        assert task is not None
        assert task.title == "Immutable disposal task"
        assert task.owner_membership_id == actor_id
        assert task.status == "cancelled"
        assert task.cancelled_by_matter_disposal is True
        assert hearing is not None
        assert hearing.purpose == "Immutable disposal hearing"
        assert hearing.outcome_note is None
        assert hearing.status == "cancelled"
        assert hearing.cancelled_by_matter_disposal is True
        assert session.scalar(
            select(func.count(MatterActivity.id)).where(
                MatterActivity.matter_id == matter["id"]
            )
        ) == activity_before
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.matter_id == matter["id"]
            )
        ) == audit_before
        assert session.scalar(
            select(func.count(HearingReminder.id)).where(
                HearingReminder.hearing_id == hearing_id
            )
        ) == reminders_before


def test_matter_and_team_mutation_actor_fence_inventory_is_complete() -> None:
    assert matter_service.MATTER_MUTATION_CAPABILITIES == {
        "create_matter": "matters:create",
        "import_matter": "matters:bulk_import",
        "update_matter": "matters:edit",
        "transition_matter_lifecycle_status": "matters:archive",
        "create_matter_note": "matters:write",
        "create_matter_task": "matters:write",
        "update_matter_task": "matters:write",
        "create_matter_hearing": "matters:write",
        "update_matter_hearing": "matters:write",
        "create_matter_court_order": "matters:edit",
        "update_matter_court_order": "matters:edit",
        "create_matter_court_sync_import": "court_sync:run",
        "create_matter_attachment": "documents:upload",
        "update_matter_attachment_metadata": "documents:manage",
        "request_matter_attachment_processing": "documents:manage",
        "create_time_entry": "time_entries:write",
        "create_matter_invoice": "invoices:issue",
    }
    direct_parent_writers = {
        "create_matter_note",
        "create_matter_court_order",
        "update_matter_court_order",
        "create_matter_court_sync_import",
        "create_matter_attachment",
        "update_matter_attachment_metadata",
        "request_matter_attachment_processing",
        "create_time_entry",
        "create_matter_invoice",
    }
    for function_name in sorted(direct_parent_writers):
        source = inspect.getsource(getattr(matter_service, function_name))
        assert source.index("_lock_matter_mutation_actor(") < source.index(
            "_get_matter_model("
        )
        assert f'"{function_name}"' in source

    assignment_fenced_writers = {
        "update_matter",
        "create_matter_task",
        "update_matter_task",
        "create_matter_hearing",
        "update_matter_hearing",
    }
    for function_name in sorted(assignment_fenced_writers):
        source = inspect.getsource(getattr(matter_service, function_name))
        assert "_lock_matter_assignment_fence(" in source
        assert f'"{function_name}"' in source

    create_source = inspect.getsource(matter_service.create_matter)
    assert create_source.index("lock_company_memberships_for_assignment(") < (
        create_source.index("assert_matter_limit(")
    )
    assert '"create_matter" if commit else "import_matter"' in create_source

    lifecycle_source = inspect.getsource(
        matter_service.transition_matter_lifecycle_status
    )
    assert lifecycle_source.index("_lock_matter_mutation_actor(") < (
        lifecycle_source.index("_get_matter_model(")
    )
    assert '"transition_matter_lifecycle_status"' in lifecycle_source

    assert "require_locked_membership_capability" in inspect.getsource(
        matter_service._assert_active_locked_actor
    )
    assert "require_locked_membership_capability" in inspect.getsource(
        team_service._assert_active_locked_actor
    )
    for function_name in (
        "create_team",
        "update_team",
        "delete_team",
        "add_team_member",
        "remove_team_member",
        "set_team_scoping",
    ):
        source = inspect.getsource(getattr(team_service, function_name))
        assert (
            "_assert_active_locked_actor(" in source
            or "_lock_whole_team_access_fence(" in source
            or "_lock_single_team_member_access_fence(" in source
        )


@pytest.mark.parametrize(
    "surface",
    (
        "matter_create",
        "matter_update",
        "matter_lifecycle",
        "matter_note",
        "matter_task",
        "court_order",
        "court_sync",
        "attachment_upload",
        "attachment_manage",
        "time_entry",
        "invoice",
        "team_create",
        "team_update_noop",
        "team_readd",
        "team_scoping_noop",
    ),
)
def test_locked_actor_capability_is_rechecked_after_route_authorization(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    actor_id = str(bootstrap["membership"]["id"])
    is_team_surface = surface.startswith("team_")
    matter = (
        None
        if surface == "matter_create" or is_team_surface
        else _create_matter(
            client,
            token=token,
            code=f"ROLE-CAP-{surface.upper().replace('_', '-')}",
        )
    )
    team = (
        _create_team(client, token=token, slug=f"cap-{surface.replace('_', '-')}")
        if is_team_surface and surface != "team_create"
        else None
    )
    if surface == "team_readd":
        assert team is not None
        added = client.post(
            f"/api/teams/{team['id']}/members",
            headers=auth_headers(token),
            json={"membership_id": actor_id, "is_lead": False},
        )
        assert added.status_code == 200, added.text
    module = team_service if is_team_surface else matter_service
    original_lock = module.lock_company_memberships_for_assignment
    injected = False

    counted_models = (
        AuditEvent,
        Matter,
        MatterActivity,
        MatterAttachment,
        MatterCourtOrder,
        MatterCourtSyncRun,
        MatterInvoice,
        MatterNote,
        MatterTask,
        MatterTimeEntry,
        Team,
        TeamMembership,
    )
    with get_session_factory()() as session:
        counts_before = {
            model: session.scalar(select(func.count(model.id)))
            for model in counted_models
        }
        original_matter = session.get(Matter, matter["id"]) if matter else None
        original_matter_snapshot = (
            original_matter.title,
            str(original_matter.status),
            original_matter.updated_at,
        ) if original_matter else None

    def demotion_wins(lock_session, **kwargs):
        nonlocal injected
        if not injected and actor_id in {
            value for value in kwargs["membership_ids"] if value is not None
        }:
            injected = True
            lock_session.execute(
                update(CompanyMembership)
                .where(CompanyMembership.id == actor_id)
                .values(role="viewer")
            )
            lock_session.commit()
        return original_lock(lock_session, **kwargs)

    monkeypatch.setattr(module, "lock_company_memberships_for_assignment", demotion_wins)
    if surface == "matter_create":
        denied = client.post(
            "/api/matters/",
            headers=auth_headers(token),
            json={
                "title": "Must not survive demotion",
                "matter_code": "ROLE-CAP-CREATE-DENIED",
                "practice_area": "IP",
                "forum_level": "high_court",
                "status": "intake",
            },
        )
    elif surface == "matter_update":
        assert matter is not None
        denied = client.patch(
            f"/api/matters/{matter['id']}",
            headers=auth_headers(token),
            json={
                "title": "Must not survive demotion",
                "expected_updated_at": matter["updated_at"],
            },
        )
    elif surface == "matter_lifecycle":
        assert matter is not None
        denied = client.patch(
            f"/api/matters/{matter['id']}/lifecycle/status",
            headers=auth_headers(token),
            json={
                "to_status": "disposed",
                "expected_from_status": matter["status"],
                "expected_updated_at": matter["updated_at"],
                "reason": "Must not survive demotion.",
            },
        )
    elif surface == "matter_note":
        assert matter is not None
        denied = client.post(
            f"/api/matters/{matter['id']}/notes",
            headers=auth_headers(token),
            json={"body": "Must not survive demotion"},
        )
    elif surface == "matter_task":
        assert matter is not None
        denied = client.post(
            f"/api/matters/{matter['id']}/tasks",
            headers=auth_headers(token),
            json={"title": "Must not survive demotion", "status": "todo"},
        )
    elif surface == "court_order":
        assert matter is not None
        denied = client.post(
            f"/api/matters/{matter['id']}/court-orders",
            headers=auth_headers(token),
            json={
                "order_date": date.today().isoformat(),
                "title": "Must not survive demotion",
                "summary": "Must not survive demotion",
            },
        )
    elif surface == "court_sync":
        assert matter is not None
        denied = client.post(
            f"/api/matters/{matter['id']}/court-sync/import",
            headers=auth_headers(token),
            json={"source": "demotion-test", "cause_list_entries": [], "orders": []},
        )
    elif surface == "attachment_upload":
        assert matter is not None
        denied = client.post(
            f"/api/matters/{matter['id']}/attachments",
            headers=auth_headers(token),
            files={"file": ("denied.txt", b"must not survive", "text/plain")},
        )
    elif surface == "attachment_manage":
        assert matter is not None
        denied = client.patch(
            f"/api/matters/{matter['id']}/attachments/missing/metadata",
            headers=auth_headers(token),
            json={"document_type": "other"},
        )
    elif surface == "time_entry":
        assert matter is not None
        denied = client.post(
            f"/api/matters/{matter['id']}/time-entries",
            headers=auth_headers(token),
            json={
                "work_date": date.today().isoformat(),
                "description": "Must not survive demotion",
                "duration_minutes": 30,
            },
        )
    elif surface == "invoice":
        assert matter is not None
        denied = client.post(
            f"/api/matters/{matter['id']}/invoices",
            headers=auth_headers(token),
            json={
                "issued_on": date.today().isoformat(),
                "manual_items": [
                    {"description": "Must not survive demotion", "amount_minor": 100}
                ],
            },
        )
    elif surface == "team_create":
        denied = client.post(
            "/api/teams/",
            headers=auth_headers(token),
            json={"name": "Must not survive demotion", "slug": "demotion-denied"},
        )
    elif surface == "team_update_noop":
        assert team is not None
        denied = client.patch(
            f"/api/teams/{team['id']}",
            headers=auth_headers(token),
            json={},
        )
    elif surface == "team_readd":
        assert team is not None
        denied = client.post(
            f"/api/teams/{team['id']}/members",
            headers=auth_headers(token),
            json={"membership_id": actor_id, "is_lead": False},
        )
    else:
        assert surface == "team_scoping_noop"
        denied = client.put(
            "/api/teams/scoping",
            headers=auth_headers(token),
            json={"enabled": False},
        )
    assert denied.status_code == 403, denied.text
    with get_session_factory()() as session:
        assert {
            model: session.scalar(select(func.count(model.id)))
            for model in counted_models
        } == counts_before
        if matter is not None:
            reloaded_matter = session.get(Matter, matter["id"])
            assert reloaded_matter is not None
            assert (
                reloaded_matter.title,
                str(reloaded_matter.status),
                reloaded_matter.updated_at,
            ) == original_matter_snapshot
