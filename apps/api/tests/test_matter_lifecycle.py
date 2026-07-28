from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    DEFAULT_MATTER_STATUS,
    AuditEvent,
    AuditResult,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CompanyMembership,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingTargetType,
    HearingReminder,
    HearingReminderStatus,
    Matter,
    MatterActivity,
    MatterCourtSyncJob,
    MatterCourtSyncJobStatus,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    UserCalendarConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.matters import MatterCreateRequest
from caseops_api.services.matters import (
    _assert_matter_not_disposed,
    _matter_lock_statement,
)
from tests.test_auth_company import auth_headers, bootstrap_company


def _create_matter(
    client: TestClient,
    token: str,
    *,
    code: str,
    status: str | None = None,
    opposing_party: str = "Unique Counterparty Ltd",
) -> dict:
    payload: dict[str, object] = {
        "title": f"Lifecycle regression {code}",
        "matter_code": code,
        "practice_area": "litigation",
        "forum_level": "high_court",
        "court_name": "Delhi High Court",
        "client_name": "Lifecycle Client Ltd",
        "opposing_party": opposing_party,
    }
    if status is not None:
        payload["status"] = status
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _lifecycle(
    client: TestClient,
    token: str,
    matter: dict,
    *,
    to_status: str,
    reason: str = "Final judgment entered and engagement completed",
):
    return client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": to_status,
            "expected_from_status": matter["status"],
            "expected_updated_at": matter["updated_at"],
            "reason": reason,
        },
    )


def test_postgresql_matter_lock_statement_locks_only_parent_table() -> None:
    sql = str(
        _matter_lock_statement(company_id="company-id", matter_id="matter-id").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()

    assert " join " not in sql
    assert "for update of matters" in sql


def test_legacy_core_guard_treats_inactive_nonterminal_row_as_nonoperational() -> None:
    inconsistent = Matter(
        company_id="company-id",
        title="Legacy inactive row",
        matter_code="LEGACY-INACTIVE",
        status="active",
        practice_area="litigation",
        forum_level="high_court",
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        _assert_matter_not_disposed(inconsistent, operation="create work")

    assert getattr(exc_info.value, "status_code", None) == 409
    assert "inactive" in str(getattr(exc_info.value, "detail", "")).lower()


@pytest.mark.parametrize(
    ("status_value", "is_active"),
    (("disposed", True), ("active", False)),
)
def test_database_rejects_inconsistent_lifecycle_state(
    client: TestClient,
    status_value: str,
    is_active: bool,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, code=f"LIFE-DB-{status_value}-{is_active}")
    with get_session_factory()() as session:
        row = session.get(Matter, matter["id"])
        assert row is not None
        row.status = status_value
        row.is_active = is_active
        with pytest.raises(IntegrityError):
            session.commit()


def test_create_defaults_to_active_and_explicit_active_needs_no_conflict_check(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])

    implicit = _create_matter(client, token, code="LIFE-DEFAULT")
    explicit = _create_matter(client, token, code="LIFE-EXPLICIT", status="active")

    assert (implicit["status"], implicit["is_active"]) == ("active", True)
    assert (explicit["status"], explicit["is_active"]) == ("active", True)


def test_creation_policy_defaults_are_active_below_the_http_boundary(
    client: TestClient,
) -> None:
    """Guard every omitted-status producer, not only the Pydantic route."""

    bootstrap = bootstrap_company(client)
    payload = MatterCreateRequest(
        title="Schema default matter",
        matter_code="LIFE-SCHEMA-DEFAULT",
        practice_area="litigation",
        forum_level="high_court",
        court_name="Delhi High Court",
    )
    assert payload.status == DEFAULT_MATTER_STATUS.value

    status_column = Matter.__table__.c.status
    assert status_column.default is not None
    assert status_column.default.arg == DEFAULT_MATTER_STATUS
    assert status_column.server_default is not None
    assert str(status_column.server_default.arg).strip("'") == DEFAULT_MATTER_STATUS.value

    # Direct/background ORM construction used to fall back to Intake even
    # after the UI and request schema had moved to Active.
    with get_session_factory()() as session:
        row = Matter(
            company_id=str(bootstrap["company"]["id"]),
            title="ORM default matter",
            matter_code="LIFE-ORM-DEFAULT",
            practice_area="litigation",
            forum_level="high_court",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        assert (row.status, row.is_active) == (DEFAULT_MATTER_STATUS.value, True)


def test_create_rejects_terminal_status_without_lifecycle_controls(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    base_payload = {
        "title": "Terminal creation bypass",
        "practice_area": "litigation",
        "forum_level": "high_court",
        "court_name": "Delhi High Court",
        "client_name": "Lifecycle Client Ltd",
    }

    for terminal_status in ("disposed", "closed"):
        response = client.post(
            "/api/matters/",
            headers=auth_headers(token),
            json={
                **base_payload,
                "matter_code": f"LIFE-CREATE-{terminal_status.upper()}",
                "status": terminal_status,
            },
        )
        assert response.status_code == 409, response.text
        assert "lifecycle status endpoint" in response.json()["detail"]


def test_cancelled_task_status_is_internal_to_lifecycle_disposal(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, code="LIFE-TASK-CANCEL")

    forbidden_create = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={"title": "Bypass task", "status": "cancelled"},
    )
    assert forbidden_create.status_code == 422, forbidden_create.text

    task = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={"title": "Valid open task"},
    )
    assert task.status_code == 200, task.text
    forbidden_update = client.patch(
        f"/api/matters/{matter['id']}/tasks/{task.json()['id']}",
        headers=auth_headers(token),
        json={"status": "cancelled"},
    )
    assert forbidden_update.status_code == 422, forbidden_update.text


def test_generic_patch_rejects_stale_write_and_direct_lifecycle_mutation(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, code="LIFE-OCC")

    updated = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={"title": "Fresh lifecycle title", "expected_updated_at": matter["updated_at"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["updated_at"] != matter["updated_at"]

    missing_token = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={"description": "Mutation without compare-and-swap token"},
    )
    assert missing_token.status_code == 422, missing_token.text

    stale = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={"description": "Stale overwrite", "expected_updated_at": matter["updated_at"]},
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "matter_stale_write"
    assert "Refresh" in stale.json()["detail"]

    stale_lifecycle = _lifecycle(client, token, matter, to_status="disposed")
    assert stale_lifecycle.status_code == 409, stale_lifecycle.text
    assert stale_lifecycle.json()["code"] == "matter_stale_write"
    with get_session_factory()() as session:
        denied = session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.matter_id == matter["id"],
                AuditEvent.action == "matter.lifecycle.transition_denied",
            )
            .order_by(AuditEvent.created_at.desc())
        )
        assert denied is not None and denied.result == AuditResult.DENIED
        assert json.loads(denied.metadata_json or "{}")["reason"] == "stale_updated_at"

    direct_active = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={"is_active": False},
    )
    assert direct_active.status_code == 422, direct_active.text

    direct_dispose = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={
            "status": "disposed",
            "expected_updated_at": updated.json()["updated_at"],
        },
    )
    assert direct_dispose.status_code == 409, direct_dispose.text


def test_lifecycle_transition_matrix_reason_audit_and_disposed_immutability(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _create_matter(client, token, code="LIFE-MATRIX")

    non_terminal = _lifecycle(client, token, matter, to_status="on_hold")
    assert non_terminal.status_code == 409, non_terminal.text

    stale_status = client.patch(
        f"/api/matters/{matter['id']}/lifecycle/status",
        headers=auth_headers(token),
        json={
            "to_status": "disposed",
            "expected_from_status": "intake",
            "expected_updated_at": matter["updated_at"],
            "reason": "Final judgment entered and engagement completed",
        },
    )
    assert stale_status.status_code == 409, stale_status.text

    trivial_reason = _lifecycle(client, token, matter, to_status="disposed", reason="done")
    assert trivial_reason.status_code == 422, trivial_reason.text

    disposed_response = _lifecycle(client, token, matter, to_status="disposed")
    assert disposed_response.status_code == 200, disposed_response.text
    disposed = disposed_response.json()
    assert (disposed["status"], disposed["is_active"]) == ("disposed", False)

    immutable = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={"title": "Disposed title mutation", "expected_updated_at": disposed["updated_at"]},
    )
    assert immutable.status_code == 409, immutable.text

    wrong_reopen = _lifecycle(client, token, disposed, to_status="active")
    assert wrong_reopen.status_code == 409, wrong_reopen.text

    reopened_response = _lifecycle(
        client,
        token,
        disposed,
        to_status="intake",
        reason="New instructions require reopening this engagement",
    )
    assert reopened_response.status_code == 200, reopened_response.text
    reopened = reopened_response.json()
    assert (reopened["status"], reopened["is_active"]) == ("intake", True)

    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.matter_id == matter["id"],
                AuditEvent.action == "matter.lifecycle.reopened",
            )
        )
        activity = session.scalar(
            select(MatterActivity).where(
                MatterActivity.matter_id == matter["id"],
                MatterActivity.event_type == "matter_reopened",
            )
        )
        assert audit is not None
        assert json.loads(audit.metadata_json or "{}")["reason"].startswith(
            "New instructions"
        )
        assert activity is not None
        assert activity.detail == "New instructions require reopening this engagement"
        denied = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.matter_id == matter["id"],
                    AuditEvent.action == "matter.lifecycle.transition_denied",
                )
            )
        )
        reasons = {
            json.loads(event.metadata_json or "{}").get("reason")
            for event in denied
        }
        assert {"invalid_transition", "expected_status_mismatch"} <= reasons
        assert all(event.result == AuditResult.DENIED for event in denied)


def test_lifecycle_endpoint_requires_archive_capability(client: TestClient) -> None:
    boot = bootstrap_company(client)
    owner_token = str(boot["access_token"])
    matter = _create_matter(client, owner_token, code="LIFE-ROLE")
    created = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Ordinary Member",
            "email": "member@lifecycle.example",
            "password": "MemberStrong123!",
            "role": "member",
        },
    )
    assert created.status_code == 200, created.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "member@lifecycle.example",
            "password": "MemberStrong123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text

    denied = _lifecycle(
        client,
        str(login.json()["access_token"]),
        matter,
        to_status="disposed",
    )
    assert denied.status_code == 403, denied.text


def test_dispose_atomically_clears_operational_state_and_blocks_new_work(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter = _create_matter(client, token, code="LIFE-SIDE")
    future = "2099-01-15"
    today = date.today().isoformat()

    task_response = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={"title": "Open operational task", "due_on": today},
    )
    assert task_response.status_code == 200, task_response.text
    deadline_response = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=auth_headers(token),
        json={"title": "Open operational deadline", "due_on": future},
    )
    assert deadline_response.status_code == 200, deadline_response.text
    hearing_response = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": future,
            "forum_name": "Delhi High Court",
            "purpose": "Final directions",
        },
    )
    assert hearing_response.status_code == 200, hearing_response.text
    hearing_id = hearing_response.json()["id"]
    past_hearing_response = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2000-01-15",
            "forum_name": "Delhi High Court",
            "purpose": "Unclosed historical listing",
        },
    )
    assert past_hearing_response.status_code == 200, past_hearing_response.text
    attachment_response = client.post(
        f"/api/matters/{matter['id']}/attachments",
        headers=auth_headers(token),
        files={
            "file": (
                "lifecycle-disposal.txt",
                b"Queued document work must be neutralized on disposal.",
                "text/plain",
            )
        },
    )
    assert attachment_response.status_code == 200, attachment_response.text
    attachment_id = attachment_response.json()["id"]

    with get_session_factory()() as session:
        reminder = session.scalar(
            select(HearingReminder).where(HearingReminder.hearing_id == hearing_id)
        )
        if reminder is None:
            membership_id = session.scalar(
                select(CompanyMembership.id).where(
                    CompanyMembership.company_id == company_id
                )
            )
            session.add(
                HearingReminder(
                    company_id=company_id,
                    matter_id=matter["id"],
                    hearing_id=hearing_id,
                    recipient_membership_id=membership_id,
                    recipient_email="owner@asterlegal.in",
                    scheduled_for=datetime(2099, 1, 14, tzinfo=UTC),
                    status=HearingReminderStatus.QUEUED,
                )
            )
        session.add(
            MatterCourtSyncJob(
                company_id=company_id,
                matter_id=matter["id"],
                requested_by_membership_id=boot["membership"]["id"],
                source="ecourtsindia",
                status=MatterCourtSyncJobStatus.QUEUED,
            )
        )
        session.add(
            MatterDeadline(
                matter_id=matter["id"],
                source="manual",
                kind="other",
                title="Already missed operational deadline",
                due_on=date.today(),
                status="missed",
                created_by_membership_id=boot["membership"]["id"],
            )
        )
        document_job = session.scalar(
            select(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.attachment_id == attachment_id,
                DocumentProcessingJob.target_type
                == DocumentProcessingTargetType.MATTER_ATTACHMENT,
            )
            .order_by(DocumentProcessingJob.queued_at.desc())
        )
        assert document_job is not None
        document_job.status = DocumentProcessingJobStatus.QUEUED
        document_job.started_at = None
        document_job.completed_at = None
        document_job.error_message = None
        document_job_id = document_job.id
        session.commit()

    current = client.get(
        f"/api/matters/{matter['id']}", headers=auth_headers(token)
    ).json()
    disposed_response = _lifecycle(client, token, current, to_status="disposed")
    assert disposed_response.status_code == 200, disposed_response.text
    disposed = disposed_response.json()
    assert disposed["next_hearing_on"] is None
    assert disposed["next_hearing_source"] == "unknown"
    assert disposed["next_hearing_manual_lock"] is False

    with get_session_factory()() as session:
        hearing = session.get(MatterHearing, hearing_id)
        past_hearing = session.get(
            MatterHearing,
            past_hearing_response.json()["id"],
        )
        deadline = session.get(MatterDeadline, deadline_response.json()["id"])
        missed_deadline = session.scalar(
            select(MatterDeadline).where(
                MatterDeadline.matter_id == matter["id"],
                MatterDeadline.title == "Already missed operational deadline",
            )
        )
        task = session.get(MatterTask, task_response.json()["id"])
        reminder = session.scalar(
            select(HearingReminder).where(HearingReminder.hearing_id == hearing_id)
        )
        job = session.scalar(
            select(MatterCourtSyncJob).where(
                MatterCourtSyncJob.matter_id == matter["id"]
            )
        )
        document_job = session.get(DocumentProcessingJob, document_job_id)
        assert hearing is not None and hearing.status == "cancelled"
        assert past_hearing is not None and past_hearing.status == "cancelled"
        assert deadline is not None and deadline.status == "cancelled"
        assert missed_deadline is not None and missed_deadline.status == "cancelled"
        assert task is not None and task.status == "cancelled"
        assert reminder is not None and reminder.status == "cancelled"
        assert job is not None and job.status == "failed"
        assert document_job is not None
        assert document_job.status == DocumentProcessingJobStatus.FAILED
        assert "disposed" in str(document_job.error_message).lower()

    today_view = client.get("/api/me/today", headers=auth_headers(token))
    assert today_view.status_code == 200, today_view.text
    assert all(
        row["matter"]["id"] != matter["id"]
        for stream in (
            "hearings_next_7d",
            "tasks_due_or_overdue",
            "drafts_in_review",
            "overdue_invoices",
            "deadlines_next_7d",
        )
        for row in today_view.json()[stream]
    )

    blocked_calls = [
        client.post(
            f"/api/matters/{matter['id']}/tasks",
            headers=auth_headers(token),
            json={"title": "Forbidden new task"},
        ),
        client.patch(
            f"/api/matters/{matter['id']}/tasks/{task_response.json()['id']}",
            headers=auth_headers(token),
            json={"title": "Forbidden task update"},
        ),
        client.post(
            f"/api/matters/{matter['id']}/deadlines",
            headers=auth_headers(token),
            json={"title": "Forbidden deadline", "due_on": future},
        ),
        client.post(
            f"/api/matters/{matter['id']}/hearings",
            headers=auth_headers(token),
            json={
                "hearing_on": future,
                "forum_name": "Delhi High Court",
                "purpose": "Forbidden hearing",
            },
        ),
        client.post(
            f"/api/matters/{matter['id']}/court-sync/import",
            headers=auth_headers(token),
            json={
                "source": "Manual regression",
                "summary": "Disposed matters reject imported court data.",
                "cause_list_entries": [],
                "orders": [],
            },
        ),
        client.post(
            f"/api/matters/{matter['id']}/court-sync/pull",
            headers=auth_headers(token),
            json={
                "source": "delhi_high_court_live",
                "source_reference": "Disposed lifecycle regression",
            },
        ),
        client.post(
            f"/api/matters/{matter['id']}/attachments/{attachment_id}/retry",
            headers=auth_headers(token),
        ),
    ]
    assert [response.status_code for response in blocked_calls] == [
        409,
        409,
        409,
        409,
        409,
        409,
        409,
    ]

    reopened_response = _lifecycle(
        client,
        token,
        disposed,
        to_status="intake",
        reason="A new engagement phase requires controlled reopening",
    )
    assert reopened_response.status_code == 200, reopened_response.text
    with get_session_factory()() as session:
        hearing = session.get(MatterHearing, hearing_id)
        deadline = session.get(MatterDeadline, deadline_response.json()["id"])
        task = session.get(MatterTask, task_response.json()["id"])
        assert hearing is not None and hearing.status == "cancelled"
        assert deadline is not None and deadline.status == "cancelled"
        assert task is not None and task.status == "cancelled"
        assert hearing.cancelled_by_matter_disposal is True
        assert deadline.cancelled_by_matter_disposal is True
        assert task.cancelled_by_matter_disposal is True

    resurrection_attempts = [
        client.patch(
            f"/api/matters/{matter['id']}/tasks/{task_response.json()['id']}",
            headers=auth_headers(token),
            json={"status": "todo"},
        ),
        client.patch(
            f"/api/matters/{matter['id']}/deadlines/{deadline_response.json()['id']}",
            headers=auth_headers(token),
            json={"status": "open"},
        ),
        client.patch(
            f"/api/matters/{matter['id']}/hearings/{hearing_id}",
            headers=auth_headers(token),
            json={"status": "scheduled"},
        ),
    ]
    assert [response.status_code for response in resurrection_attempts] == [409, 409, 409]

    reopened_today = client.get("/api/me/today", headers=auth_headers(token))
    assert reopened_today.status_code == 200, reopened_today.text
    assert all(
        row["matter"]["id"] != matter["id"]
        for stream in (
            "hearings_next_7d",
            "tasks_due_or_overdue",
            "deadlines_next_7d",
        )
        for row in reopened_today.json()[stream]
    )


def test_reopen_keeps_prior_conflict_check_historical_without_gating_activation(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, code="LIFE-CONFLICT", status="intake")
    first_check = client.post(
        f"/api/matters/{matter['id']}/conflict-checks",
        headers=auth_headers(token),
        json={
            "opposing_party_name": "Unique Counterparty Ltd",
            "related_party_names": [],
        },
    )
    assert first_check.status_code == 200, first_check.text
    assert first_check.json()["status"] == "cleared"
    assert first_check.json()["matter_lifecycle_version"] == matter["lifecycle_version"]

    activated = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={"status": "active", "expected_updated_at": matter["updated_at"]},
    )
    assert activated.status_code == 200, activated.text
    disposed_response = _lifecycle(client, token, activated.json(), to_status="disposed")
    assert disposed_response.status_code == 200, disposed_response.text
    reopened_response = _lifecycle(
        client,
        token,
        disposed_response.json(),
        to_status="intake",
        reason="Client returned with materially new instructions",
    )
    assert reopened_response.status_code == 200, reopened_response.text

    listed_checks = client.get(
        f"/api/matters/{matter['id']}/conflict-checks",
        headers=auth_headers(token),
    )
    assert listed_checks.status_code == 200, listed_checks.text
    assert len(listed_checks.json()["checks"]) == 1
    historical_check = listed_checks.json()["checks"][0]
    assert historical_check["id"] == first_check.json()["id"]
    assert (
        historical_check["matter_lifecycle_version"]
        == matter["lifecycle_version"]
    )
    assert (
        historical_check["matter_lifecycle_version"]
        < reopened_response.json()["lifecycle_version"]
    )

    reactivated = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={
            "status": "active",
            "expected_updated_at": reopened_response.json()["updated_at"],
        },
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "active"
    assert (
        reactivated.json()["lifecycle_version"]
        == reopened_response.json()["lifecycle_version"]
    )


def test_reopen_neutralizes_open_children_on_legacy_disposed_row(
    client: TestClient,
) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, code="LIFE-LEGACY-REOPEN")
    task = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={"title": "Legacy task must not revive"},
    ).json()
    deadline = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=auth_headers(token),
        json={"title": "Legacy deadline must not revive", "due_on": "2099-03-10"},
    ).json()
    hearing = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2099-03-11",
            "forum_name": "Delhi High Court",
            "purpose": "Legacy hearing must not revive",
        },
    ).json()
    migrated_task = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={"title": "Migration-cancelled task with old provider event"},
    ).json()

    # Reproduce a pre-reconciliation/migrated terminal row: the parent is
    # disposed, but its historical operational children were never cancelled.
    with get_session_factory()() as session:
        row = session.get(Matter, matter["id"])
        assert row is not None
        membership_id = session.scalar(
            select(CompanyMembership.id).where(
                CompanyMembership.company_id == row.company_id
            )
        )
        assert membership_id is not None
        migrated_task_row = session.get(MatterTask, migrated_task["id"])
        assert migrated_task_row is not None
        migrated_task_row.status = "cancelled"
        migrated_task_row.completed_at = datetime.now(UTC)
        migrated_task_row.cancelled_by_matter_disposal = True
        connection = UserCalendarConnection(
            company_id=row.company_id,
            membership_id=membership_id,
            provider="outlook",
            status="connected",
        )
        session.add(connection)
        session.flush()
        legacy_sync = CalendarEventSync(
            company_id=row.company_id,
            calendar_connection_id=connection.id,
            source_type="matter_task",
            source_id=migrated_task_row.id,
            provider_event_id="legacy-provider-event-must-be-deleted",
            sync_status=CalendarEventSyncStatus.SYNCED,
        )
        session.add(legacy_sync)
        session.flush()
        legacy_sync_id = legacy_sync.id
        row.status = "disposed"
        row.is_active = False
        session.commit()
        assert session.get(MatterTask, task["id"]).status == "todo"  # type: ignore[union-attr]
        assert session.get(MatterDeadline, deadline["id"]).status == "open"  # type: ignore[union-attr]
        assert session.get(MatterHearing, hearing["id"]).status == "scheduled"  # type: ignore[union-attr]

    legacy_disposed = client.get(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
    ).json()
    reopened = _lifecycle(
        client,
        token,
        legacy_disposed,
        to_status="intake",
        reason="Legacy terminal row requires safe controlled reopening",
    )
    assert reopened.status_code == 200, reopened.text

    with get_session_factory()() as session:
        task_row = session.get(MatterTask, task["id"])
        deadline_row = session.get(MatterDeadline, deadline["id"])
        hearing_row = session.get(MatterHearing, hearing["id"])
        migrated_task_row = session.get(MatterTask, migrated_task["id"])
        legacy_sync = session.get(CalendarEventSync, legacy_sync_id)
        assert task_row is not None and task_row.status == "cancelled"
        assert deadline_row is not None and deadline_row.status == "cancelled"
        assert hearing_row is not None and hearing_row.status == "cancelled"
        assert migrated_task_row is not None and migrated_task_row.status == "cancelled"
        assert task_row.cancelled_by_matter_disposal is True
        assert deadline_row.cancelled_by_matter_disposal is True
        assert hearing_row.cancelled_by_matter_disposal is True
        assert migrated_task_row.cancelled_by_matter_disposal is True
        assert legacy_sync is not None
        assert legacy_sync.sync_status == CalendarEventSyncStatus.DELETE_PENDING
        assert legacy_sync.next_attempt_at is not None
        assert legacy_sync.dead_letter_reason == "matter_disposed_delete"

    resurrection_attempts = [
        client.patch(
            f"/api/matters/{matter['id']}/tasks/{task['id']}",
            headers=auth_headers(token),
            json={"status": "todo"},
        ),
        client.patch(
            f"/api/matters/{matter['id']}/deadlines/{deadline['id']}",
            headers=auth_headers(token),
            json={"status": "open"},
        ),
        client.patch(
            f"/api/matters/{matter['id']}/hearings/{hearing['id']}",
            headers=auth_headers(token),
            json={"status": "scheduled"},
        ),
    ]
    assert [response.status_code for response in resurrection_attempts] == [409, 409, 409]


def test_reopen_allows_resuming_manually_cancelled_children(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, code="LIFE-MANUAL-CANCEL")
    task = client.post(
        f"/api/matters/{matter['id']}/tasks",
        headers=auth_headers(token),
        json={"title": "Manually paused task"},
    ).json()
    deadline = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=auth_headers(token),
        json={"title": "Manually paused deadline", "due_on": "2099-01-20"},
    ).json()
    hearing = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": "2099-01-21",
            "forum_name": "Delhi High Court",
            "purpose": "Manually paused hearing",
        },
    ).json()

    with get_session_factory()() as session:
        session.get(MatterTask, task["id"]).status = "cancelled"  # type: ignore[union-attr]
        session.get(MatterDeadline, deadline["id"]).status = "cancelled"  # type: ignore[union-attr]
        session.get(MatterHearing, hearing["id"]).status = "cancelled"  # type: ignore[union-attr]
        session.commit()

    current = client.get(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
    ).json()
    disposed = _lifecycle(client, token, current, to_status="disposed").json()
    reopened = _lifecycle(
        client,
        token,
        disposed,
        to_status="intake",
        reason="Client supplied new instructions for the paused work",
    )
    assert reopened.status_code == 200, reopened.text

    assert client.patch(
        f"/api/matters/{matter['id']}/tasks/{task['id']}",
        headers=auth_headers(token),
        json={"status": "todo"},
    ).status_code == 200
    assert client.patch(
        f"/api/matters/{matter['id']}/deadlines/{deadline['id']}",
        headers=auth_headers(token),
        json={"status": "open"},
    ).status_code == 200
    assert client.patch(
        f"/api/matters/{matter['id']}/hearings/{hearing['id']}",
        headers=auth_headers(token),
        json={"status": "scheduled"},
    ).status_code == 200


def test_legacy_closed_normalizes_to_inactive_disposed(client: TestClient) -> None:
    token = str(bootstrap_company(client)["access_token"])
    matter = _create_matter(client, token, code="LIFE-CLOSED")
    with get_session_factory()() as session:
        legacy = session.get(Matter, matter["id"])
        assert legacy is not None
        legacy.status = "closed"
        legacy.is_active = False
        session.add(legacy)
        session.commit()

    response = client.get(f"/api/matters/{matter['id']}", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    assert (response.json()["status"], response.json()["is_active"]) == (
        "disposed",
        False,
    )
