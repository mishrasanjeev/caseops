"""WTD-7.2 Tasks/Deadlines Cockpit foundation."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import AuditEvent, HearingReminder, InAppNotification
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers

REPO_ROOT = Path(__file__).resolve().parents[3]


def _bootstrap_tenant(client: TestClient, slug: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug.title()} Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "OwnerStrong!234",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _invite_member(
    client: TestClient,
    *,
    owner_token: str,
    slug: str,
    email: str,
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Cockpit Member",
            "email": email,
            "password": "MemberPass123!",
            "role": "member",
        },
    )
    assert response.status_code == 200, response.text
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": slug,
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return str(response.json()["membership_id"]), str(login.json()["access_token"])


def _create_matter(
    client: TestClient,
    *,
    token: str,
    code: str,
    title: str = "Tasks cockpit matter",
) -> str:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": title,
            "matter_code": code,
            "practice_area": "Commercial Litigation",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _import_order(client: TestClient, token: str, matter_id: str) -> None:
    response = client.post(
        f"/api/matters/{matter_id}/court-sync/import",
        headers=auth_headers(token),
        json={
            "source": "manual-test",
            "summary": "Imported order sheet.",
            "orders": [
                {
                    "order_date": "2026-05-06",
                    "title": "Daily order sheet",
                    "summary": "Daily order imported from source.",
                    "order_text": (
                        "Respondent shall file reply affidavit by 20.05.2026. "
                        "List on 10.06.2026."
                    ),
                    "source_reference": "fixture:order-sheet:1",
                    "bench_name": "Justice A. Rao",
                    "order_kind": "daily_order",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text


def _metadata(event: AuditEvent) -> dict:
    return json.loads(event.metadata_json or "{}")


def test_task_and_deadline_manual_crud_is_scoped_audited_and_no_scheduler_side_effect(
    client: TestClient,
) -> None:
    slug = f"wtd72-crud-{uuid4().hex[:6]}"
    boot = _bootstrap_tenant(client, slug)
    token = str(boot["access_token"])
    member_id, _member_token = _invite_member(
        client,
        owner_token=token,
        slug=slug,
        email=f"member-{uuid4().hex[:6]}@wtd72.example",
    )
    matter_id = _create_matter(client, token=token, code="WTD72-CRUD")

    task_create = client.post(
        f"/api/matters/{matter_id}/tasks",
        headers=auth_headers(token),
        json={
            "title": "Sensitive strategy task",
            "description": "Do not leak the privileged task body.",
            "owner_membership_id": member_id,
            "due_on": "2026-05-20",
            "priority": "urgent",
        },
    )
    assert task_create.status_code == 200, task_create.text
    task = task_create.json()
    assert task["source_type"] == "user"
    assert task["owner_membership_id"] == member_id

    tasks = client.get(
        f"/api/matters/{matter_id}/tasks",
        headers=auth_headers(token),
    )
    assert tasks.status_code == 200, tasks.text
    assert [row["id"] for row in tasks.json()["tasks"]] == [task["id"]]

    completed_task = client.patch(
        f"/api/matters/{matter_id}/tasks/{task['id']}",
        headers=auth_headers(token),
        json={"status": "completed"},
    )
    assert completed_task.status_code == 200, completed_task.text
    assert completed_task.json()["completed_at"] is not None
    reopened_task = client.patch(
        f"/api/matters/{matter_id}/tasks/{task['id']}",
        headers=auth_headers(token),
        json={"status": "todo"},
    )
    assert reopened_task.status_code == 200, reopened_task.text
    assert reopened_task.json()["completed_at"] is None

    deadline_create = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=auth_headers(token),
        json={
            "source": "custom",
            "kind": "manual",
            "title": "Sensitive filing deadline",
            "notes": "Do not leak the privileged deadline notes.",
            "due_on": "2026-05-21",
            "assignee_membership_id": member_id,
        },
    )
    assert deadline_create.status_code == 200, deadline_create.text
    deadline = deadline_create.json()
    assert deadline["source"] == "custom"
    assert deadline["assignee_membership_id"] == member_id

    deadlines = client.get(
        f"/api/matters/{matter_id}/deadlines",
        headers=auth_headers(token),
    )
    assert deadlines.status_code == 200, deadlines.text
    assert [row["id"] for row in deadlines.json()["deadlines"]] == [deadline["id"]]

    done_deadline = client.patch(
        f"/api/matters/{matter_id}/deadlines/{deadline['id']}",
        headers=auth_headers(token),
        json={"status": "done"},
    )
    assert done_deadline.status_code == 200, done_deadline.text
    assert done_deadline.json()["completed_at"] is not None
    reopened_deadline = client.patch(
        f"/api/matters/{matter_id}/deadlines/{deadline['id']}",
        headers=auth_headers(token),
        json={"status": "open"},
    )
    assert reopened_deadline.status_code == 200, reopened_deadline.text
    assert reopened_deadline.json()["completed_at"] is None

    bad_status = client.patch(
        f"/api/matters/{matter_id}/deadlines/{deadline['id']}",
        headers=auth_headers(token),
        json={"status": "bogus"},
    )
    assert bad_status.status_code == 422
    bad_due = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=auth_headers(token),
        json={"source": "custom", "kind": "manual", "title": "Bad due", "due_on": "nope"},
    )
    assert bad_due.status_code == 422

    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HearingReminder)) == 0
        assert session.scalar(select(func.count()).select_from(InAppNotification)) == 0
        audit_rows = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.matter_id == matter_id,
                    AuditEvent.action.in_(
                        [
                            "matter_task.created",
                            "matter_task.completed",
                            "matter_task.reopened",
                            "deadline.created",
                            "deadline.complete",
                            "deadline.reopen",
                        ]
                    ),
                )
                .order_by(AuditEvent.created_at.asc())
            )
        )
    actions = {row.action for row in audit_rows}
    assert {
        "matter_task.created",
        "matter_task.completed",
        "matter_task.reopened",
        "deadline.created",
        "deadline.complete",
        "deadline.reopen",
    }.issubset(actions)
    metadata_blob = json.dumps([_metadata(row) for row in audit_rows])
    assert "Sensitive strategy task" not in metadata_blob
    assert "privileged task body" not in metadata_blob
    assert "Sensitive filing deadline" not in metadata_blob
    assert "privileged deadline notes" not in metadata_blob


def test_source_backed_tasks_and_deadlines_preserve_proceeding_lineage(
    client: TestClient,
) -> None:
    slug = f"wtd72-src-{uuid4().hex[:6]}"
    boot = _bootstrap_tenant(client, slug)
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token=token, code="WTD72-SRC")
    _import_order(client, token, matter_id)

    intelligence = client.get(
        f"/api/matters/{matter_id}/proceeding-intelligence",
        headers=auth_headers(token),
    )
    assert intelligence.status_code == 200, intelligence.text
    signals = intelligence.json()["orders"][0]["signals"]
    reply_signal = next(
        signal
        for signal in signals
        if signal["signal_type"] == "reply_affidavit_deadline"
    )
    assert reply_signal["generated_task_id"]
    assert reply_signal["generated_deadline_id"]

    tasks = client.get(
        f"/api/matters/{matter_id}/tasks",
        headers=auth_headers(token),
    )
    assert tasks.status_code == 200, tasks.text
    generated_task = next(
        row
        for row in tasks.json()["tasks"]
        if row["id"] == reply_signal["generated_task_id"]
    )
    assert generated_task["source_type"] == "proceeding_intelligence"
    assert generated_task["source_ref_id"] == reply_signal["id"]
    assert generated_task["source_label"] == "reply_affidavit_deadline"

    deadlines = client.get(
        f"/api/matters/{matter_id}/deadlines",
        headers=auth_headers(token),
    )
    assert deadlines.status_code == 200, deadlines.text
    generated_deadline = next(
        row
        for row in deadlines.json()["deadlines"]
        if row["id"] == reply_signal["generated_deadline_id"]
    )
    assert generated_deadline["source"] == "proceeding"
    assert generated_deadline["source_ref_type"] == "matter_proceeding_signal"
    assert generated_deadline["source_ref_id"] == reply_signal["id"]

    completed = client.patch(
        f"/api/matters/{matter_id}/deadlines/{generated_deadline['id']}",
        headers=auth_headers(token),
        json={"status": "done"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["source_ref_type"] == "matter_proceeding_signal"
    assert completed.json()["source_ref_id"] == reply_signal["id"]


def test_tasks_and_deadlines_enforce_access_scopes(client: TestClient) -> None:
    slug = f"wtd72-access-{uuid4().hex[:6]}"
    boot = _bootstrap_tenant(client, slug)
    owner_token = str(boot["access_token"])
    owner_headers = auth_headers(owner_token)
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        slug=slug,
        email=f"scope-{uuid4().hex[:6]}@wtd72.example",
    )
    member_headers = auth_headers(member_token)

    restricted_matter = _create_matter(
        client, token=owner_token, code="WTD72-RESTRICT", title="Restricted tasks"
    )
    seed_task = client.post(
        f"/api/matters/{restricted_matter}/tasks",
        headers=owner_headers,
        json={"title": "Restricted task"},
    )
    assert seed_task.status_code == 200, seed_task.text
    seed_deadline = client.post(
        f"/api/matters/{restricted_matter}/deadlines",
        headers=owner_headers,
        json={
            "source": "custom",
            "kind": "manual",
            "title": "Restricted deadline",
            "due_on": "2026-05-20",
        },
    )
    assert seed_deadline.status_code == 200, seed_deadline.text
    restricted = client.post(
        f"/api/matters/{restricted_matter}/access/restricted",
        headers=owner_headers,
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    assert (
        client.get(
            f"/api/matters/{restricted_matter}/tasks",
            headers=member_headers,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/matters/{restricted_matter}/deadlines",
            headers=member_headers,
        ).status_code
        == 404
    )

    walled_matter = _create_matter(
        client, token=owner_token, code="WTD72-WALL", title="Walled tasks"
    )
    wall = client.post(
        f"/api/matters/{walled_matter}/access/walls",
        headers=owner_headers,
        json={"excluded_membership_id": member_id},
    )
    assert wall.status_code == 200, wall.text
    assert (
        client.post(
            f"/api/matters/{walled_matter}/tasks",
            headers=member_headers,
            json={"title": "Should not land"},
        ).status_code
        == 404
    )

    team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Litigation", "slug": "litigation"},
    )
    assert team.status_code == 201, team.text
    team_matter = _create_matter(
        client, token=owner_token, code="WTD72-TEAM", title="Team tasks"
    )
    assign = client.patch(
        f"/api/matters/{team_matter}",
        headers=owner_headers,
        json={"team_id": team.json()["id"]},
    )
    assert assign.status_code == 200, assign.text
    scope = client.put(
        "/api/teams/scoping",
        headers=owner_headers,
        json={"enabled": True},
    )
    assert scope.status_code == 200, scope.text
    invalid_owner_task = client.post(
        f"/api/matters/{team_matter}/tasks",
        headers=owner_headers,
        json={"title": "Invalid owner task", "owner_membership_id": member_id},
    )
    assert invalid_owner_task.status_code == 400, invalid_owner_task.text
    task_without_owner = client.post(
        f"/api/matters/{team_matter}/tasks",
        headers=owner_headers,
        json={"title": "Team owner only task"},
    )
    assert task_without_owner.status_code == 200, task_without_owner.text
    invalid_owner_update = client.patch(
        f"/api/matters/{team_matter}/tasks/{task_without_owner.json()['id']}",
        headers=owner_headers,
        json={"owner_membership_id": member_id},
    )
    assert invalid_owner_update.status_code == 400, invalid_owner_update.text
    invalid_deadline_assignee = client.post(
        f"/api/matters/{team_matter}/deadlines",
        headers=owner_headers,
        json={
            "source": "custom",
            "kind": "manual",
            "title": "Invalid assignee deadline",
            "due_on": "2026-05-20",
            "assignee_membership_id": member_id,
        },
    )
    assert invalid_deadline_assignee.status_code == 400, invalid_deadline_assignee.text
    team_deadline = client.post(
        f"/api/matters/{team_matter}/deadlines",
        headers=owner_headers,
        json={
            "source": "custom",
            "kind": "manual",
            "title": "Team owner only deadline",
            "due_on": "2026-05-20",
        },
    )
    assert team_deadline.status_code == 200, team_deadline.text
    invalid_deadline_update = client.patch(
        f"/api/matters/{team_matter}/deadlines/{team_deadline.json()['id']}",
        headers=owner_headers,
        json={"assignee_membership_id": member_id},
    )
    assert invalid_deadline_update.status_code == 400, invalid_deadline_update.text
    assert (
        client.post(
            f"/api/matters/{team_matter}/deadlines",
            headers=member_headers,
            json={
                "source": "custom",
                "kind": "manual",
                "title": "Should not land",
                "due_on": "2026-05-20",
            },
        ).status_code
        == 404
    )

    other = _bootstrap_tenant(client, f"wtd72-other-{uuid4().hex[:6]}")
    assert (
        client.get(
            f"/api/matters/{team_matter}/tasks",
            headers=auth_headers(str(other["access_token"])),
        ).status_code
        == 404
    )


def test_wtd72_docs_mark_cockpit_foundation_with_template_caveat() -> None:
    future = (REPO_ROOT / "docs/FUTURE_WORKPLAN_2026-05-14.md").read_text(
        encoding="utf-8"
    )
    strict = (REPO_ROOT / "docs/STRICT_ENTERPRISE_GAP_TASKLIST.md").read_text(
        encoding="utf-8"
    )
    work_to_be_done = (REPO_ROOT / "docs/WORK_TO_BE_DONE.md").read_text(
        encoding="utf-8"
    )

    assert "`WTD-7.2` tasks/deadlines" in future
    assert "matter-cockpit Tasks/Deadlines foundation is implemented" in future
    assert "admin task templates per practice area" in future
    assert "remain missing" in future
    assert "`WTD-7.2` `Partially implemented`" in strict
    assert "Tasks/Deadlines Cockpit" in strict
    assert "foundation is implemented" in strict
    assert "admin task templates per practice-area remain missing" in strict
    assert "tasks/deadlines: matter-cockpit foundation implemented" in work_to_be_done
