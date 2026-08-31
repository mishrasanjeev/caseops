from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.db.models import (
    AssistantActionPreview,
    AssistantActionStatus,
    AssistantSession,
    AuditEvent,
    Draft,
    Matter,
    MatterTask,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.private_retrieval import private_source_version
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_record_workflow import _application, _asset, _docket
from tests.test_workspace_assistant_qa import _ask, _enable_assistant, _matter, _session


def _write_proposal(response, action_type: str) -> tuple[dict, dict]:
    assert response.status_code == 200, response.text
    body = response.json()
    proposal = next(
        action
        for action in body["assistant_turn"]["proposed_actions"]
        if action["action_type"] == action_type
    )
    assert proposal["requires_confirmation"] is True
    assert proposal["execution_available"] is True
    assert proposal["target_version"]
    return body, proposal


def _preview(
    client: TestClient,
    token: str,
    *,
    assistant_session: dict,
    turn_id: str,
    proposal: dict,
    action_input: dict,
):
    return client.post(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/actions/preview",
        headers=auth_headers(token),
        json={
            "expected_version": assistant_session["version"],
            "turn_id": turn_id,
            "proposal_id": proposal["proposal_id"],
            "input": action_input,
        },
    )


def _confirm(
    client: TestClient,
    token: str,
    *,
    assistant_session: dict,
    preview: dict,
    preview_token: str | None = None,
):
    return client.post(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/actions/{preview['preview_id']}/confirm",
        headers=auth_headers(token),
        json={
            "expected_version": assistant_session["version"],
            "preview_token": preview_token or preview["preview_token"],
        },
    )


def test_matter_task_preview_confirm_is_exact_atomic_and_idempotent(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-064A-TASK")
    assistant_session = _session(client, token, matter["id"])
    body, proposal = _write_proposal(
        _ask(
            client,
            token,
            assistant_session=assistant_session,
            question="Create a task to review the evidence tomorrow.",
        ),
        "task",
    )
    assistant_session = body["session"]
    turn_id = body["assistant_turn"]["id"]

    with get_session_factory()() as session:
        before = int(session.scalar(select(func.count(MatterTask.id))) or 0)
    preview_response = _preview(
        client,
        token,
        assistant_session=assistant_session,
        turn_id=turn_id,
        proposal=proposal,
        action_input={
            "title": "Review registry evidence",
            "description": "Check the source record before the deadline.",
            "due_on": "2026-09-02",
            "priority": "high",
        },
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["status"] == "pending"
    assert preview["resulting_session_version"] is None
    assert preview["summary"].startswith("Create one task")
    assert len(preview["preview_token"]) == 64
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(MatterTask.id))) == before

    tampered = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=preview,
        preview_token="0" * 64,
    )
    assert tampered.status_code == 409
    assert tampered.json()["type"] == "assistant_action_preview_invalid"
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(MatterTask.id))) == before

    confirmed_response = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=preview,
    )
    assert confirmed_response.status_code == 200, confirmed_response.text
    confirmed = confirmed_response.json()
    assert confirmed["status"] == "confirmed"
    assert confirmed["resulting_session_version"] == assistant_session["version"] + 1
    assert confirmed["result_type"] == "matter_task"
    with get_session_factory()() as session:
        tasks = list(session.scalars(select(MatterTask).order_by(MatterTask.created_at)).all())
        assert len(tasks) == before + 1
        assert tasks[-1].matter_id == matter["id"]
        assert tasks[-1].title == "Review registry evidence"
        assert tasks[-1].priority == "high"
        assert tasks[-1].due_on.isoformat() == "2026-09-02"
        action = session.get(AssistantActionPreview, preview["preview_id"])
        assert action is not None and action.status == AssistantActionStatus.CONFIRMED
        assert action.result_id == tasks[-1].id
        assert session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.action == "workspace_assistant.action_confirmed"
            )
        ) == 1

    replay = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=preview,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["result_id"] == confirmed["result_id"]
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(MatterTask.id))) == before + 1


def test_preview_supersession_expiry_policy_and_target_changes_fail_closed(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-064A-STALE")
    body, proposal = _write_proposal(
        _ask(
            client,
            token,
            assistant_session=_session(client, token, matter["id"]),
            question="Create a task to review this file.",
        ),
        "task",
    )
    assistant_session = body["session"]
    kwargs = {
        "assistant_session": assistant_session,
        "turn_id": body["assistant_turn"]["id"],
        "proposal": proposal,
        "action_input": {"title": "Review first version"},
    }
    first = _preview(client, token, **kwargs).json()
    second_response = _preview(client, token, **kwargs)
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    replaced = _confirm(client, token, assistant_session=assistant_session, preview=first)
    assert replaced.status_code == 409
    assert replaced.json()["type"] == "assistant_action_preview_superseded"

    with get_session_factory()() as session:
        row = session.get(AssistantActionPreview, second["preview_id"])
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(minutes=20)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        from caseops_api.services.assistant_actions import _preview_token, _sha256

        expired_preview_token = _preview_token(row)
        row.preview_token_sha256 = _sha256(expired_preview_token)
        session.commit()
        second["preview_token"] = expired_preview_token
    expired = _confirm(client, token, assistant_session=assistant_session, preview=second)
    assert expired.status_code == 409
    assert expired.json()["type"] == "assistant_action_preview_expired"

    policy_preview = _preview(client, token, **kwargs).json()
    changed_policy = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={"assistant_retention_days": 46, "expected_version": 2},
    )
    assert changed_policy.status_code == 200, changed_policy.text
    rejected_policy = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=policy_preview,
    )
    assert rejected_policy.status_code == 409
    assert rejected_policy.json()["type"] == "assistant_action_policy_changed"

    stale_target_preview = _preview(client, token, **kwargs).json()
    updated = client.patch(
        f"/api/matters/{matter['id']}",
        headers=auth_headers(token),
        json={"description": "Changed after preview", "expected_updated_at": matter["updated_at"]},
    )
    assert updated.status_code == 200, updated.text
    rejected_target = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=stale_target_preview,
    )
    assert rejected_target.status_code == 409
    assert rejected_target.json()["type"] == "assistant_action_target_changed"
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(MatterTask.id))) == 0


def test_matter_draft_and_allowlisted_field_update_use_canonical_writers(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-064A-WRITES")
    assistant_session = _session(client, token, matter["id"])

    draft_body, draft_proposal = _write_proposal(
        _ask(
            client,
            token,
            assistant_session=assistant_session,
            question="Prepare a draft memo for this matter.",
        ),
        "draft",
    )
    assistant_session = draft_body["session"]
    draft_preview = _preview(
        client,
        token,
        assistant_session=assistant_session,
        turn_id=draft_body["assistant_turn"]["id"],
        proposal=draft_proposal,
        action_input={"title": "Registry response memo", "draft_type": "memo"},
    ).json()
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Draft.id))) == 0
    draft_confirmed = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=draft_preview,
    )
    assert draft_confirmed.status_code == 200, draft_confirmed.text
    assistant_session["version"] = draft_confirmed.json()["resulting_session_version"]

    field_body, field_proposal = _write_proposal(
        _ask(
            client,
            token,
            assistant_session=assistant_session,
            question="Update the client name on this matter.",
        ),
        "field_update",
    )
    assistant_session = field_body["session"]
    with get_session_factory()() as session:
        current_matter = session.get(Matter, matter["id"])
        assert current_matter is not None
        assert field_proposal["target_version"] == private_source_version(current_matter)
    forbidden = _preview(
        client,
        token,
        assistant_session=assistant_session,
        turn_id=field_body["assistant_turn"]["id"],
        proposal=field_proposal,
        action_input={"field_name": "status", "field_value": "Disposed"},
    )
    assert forbidden.status_code == 422

    field_preview_response = _preview(
        client,
        token,
        assistant_session=assistant_session,
        turn_id=field_body["assistant_turn"]["id"],
        proposal=field_proposal,
        action_input={"field_name": "client_name", "field_value": "Kaveri Brands Ltd"},
    )
    assert field_preview_response.status_code == 200, field_preview_response.text
    field_preview = field_preview_response.json()
    with get_session_factory()() as session:
        assert session.get(Matter, matter["id"]).client_name is None
    field_confirmed = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=field_preview,
    )
    assert field_confirmed.status_code == 200, field_confirmed.text
    with get_session_factory()() as session:
        draft = session.scalar(select(Draft).where(Draft.matter_id == matter["id"]))
        assert draft is not None and draft.title == "Registry response memo"
        assert draft.status == "draft"
        assert session.get(Matter, matter["id"]).client_name == "Kaveri Brands Ltd"


def test_ip_task_and_review_required_pleading_are_confirmed_on_explicit_targets(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    _enable_assistant(client, token)
    docket = _docket(client, headers, "AI-064A IP MARK")
    asset = _asset(client, headers, docket["id"], "AI-064A IP MARK")
    application = _application(client, headers, docket["id"], asset["id"])
    proceeding_response = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": application["id"],
            "proceeding_kind": "opposition",
            "side": "opponent",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "stage": "draft",
            "origin_kind": "linked_application",
        },
    )
    assert proceeding_response.status_code == 201, proceeding_response.text
    proceeding = proceeding_response.json()
    created_session = client.post(
        "/api/workspace-assistant/sessions",
        headers=headers,
        json={
            "title": "Opposition action review",
            "scopes": [{"scope_type": "ip_proceeding", "scope_id": proceeding["id"]}],
        },
    )
    assert created_session.status_code == 201, created_session.text
    assistant_session = created_session.json()

    task_body, task_proposal = _write_proposal(
        _ask(
            client,
            token,
            assistant_session=assistant_session,
            question="Create a task for the opposition response.",
        ),
        "task",
    )
    assistant_session = task_body["session"]
    task_preview = _preview(
        client,
        token,
        assistant_session=assistant_session,
        turn_id=task_body["assistant_turn"]["id"],
        proposal=task_proposal,
        action_input={"title": "Review opposition response", "priority": "urgent"},
    ).json()
    task_confirm = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=task_preview,
    )
    assert task_confirm.status_code == 200, task_confirm.text
    assistant_session["version"] = task_confirm.json()["resulting_session_version"]

    draft_body, draft_proposal = _write_proposal(
        _ask(
            client,
            token,
            assistant_session=assistant_session,
            question="Prepare a draft opposition pleading.",
        ),
        "draft",
    )
    assistant_session = draft_body["session"]
    draft_preview_response = _preview(
        client,
        token,
        assistant_session=assistant_session,
        turn_id=draft_body["assistant_turn"]["id"],
        proposal=draft_proposal,
        action_input={"title": "Notice of opposition response"},
    )
    assert draft_preview_response.status_code == 200, draft_preview_response.text
    assert any(
        change["field"] == "Reviewed template"
        for change in draft_preview_response.json()["changes"]
    )
    draft_confirm = _confirm(
        client,
        token,
        assistant_session=assistant_session,
        preview=draft_preview_response.json(),
    )
    assert draft_confirm.status_code == 200, draft_confirm.text
    with get_session_factory()() as session:
        task = session.scalar(select(MatterTask).where(MatterTask.ip_docket_id == docket["id"]))
        assert task is not None and task.priority == "urgent"
        draft = session.scalar(select(Draft).where(Draft.ip_docket_id == docket["id"]))
        assert draft is not None
        assert draft.ip_proceeding_id == proceeding["id"]
        assert draft.review_required is True
        assert draft.status == "draft"


def test_confirmation_rolls_back_domain_write_and_preview_state_together(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-064A-ROLLBACK")
    body, proposal = _write_proposal(
        _ask(
            client,
            token,
            assistant_session=_session(client, token, matter["id"]),
            question="Create a task for atomicity testing.",
        ),
        "task",
    )
    assistant_session = body["session"]
    preview = _preview(
        client,
        token,
        assistant_session=assistant_session,
        turn_id=body["assistant_turn"]["id"],
        proposal=proposal,
        action_input={"title": "Atomic boundary task"},
    ).json()

    from caseops_api.services import assistant_actions

    original = assistant_actions.create_matter_task

    def fail_after_flush(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("forced assistant action rollback")

    monkeypatch.setattr(assistant_actions, "create_matter_task", fail_after_flush)
    with pytest.raises(RuntimeError, match="forced assistant action rollback"):
        _confirm(client, token, assistant_session=assistant_session, preview=preview)
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(MatterTask.id))) == 0
        row = session.get(AssistantActionPreview, preview["preview_id"])
        assert row is not None and row.status == AssistantActionStatus.PENDING
        assistant_row = session.get(AssistantSession, assistant_session["id"])
        assert assistant_row is not None
        assert assistant_row.version == assistant_session["version"]


def test_confirmation_rechecks_tenant_session_and_actor_capabilities(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    _enable_assistant(client, owner_token)
    matter = _matter(client, owner_token, "AI-064A-AUTH")
    member = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Assistant Action Member",
            "email": "assistant-action-member@asterlegal.in",
            "password": "AssistantMember123!",
            "role": "member",
        },
    )
    assert member.status_code == 200, member.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "assistant-action-member@asterlegal.in",
            "password": "AssistantMember123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    member_token = str(login.json()["access_token"])
    body, proposal = _write_proposal(
        _ask(
            client,
            member_token,
            assistant_session=_session(client, member_token, matter["id"]),
            question="Create a task that must remain permission scoped.",
        ),
        "task",
    )
    assistant_session = body["session"]
    preview = _preview(
        client,
        member_token,
        assistant_session=assistant_session,
        turn_id=body["assistant_turn"]["id"],
        proposal=proposal,
        action_input={"title": "Permission-scoped task"},
    ).json()

    tenant_b = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Beryl Legal LLP",
            "company_slug": "beryl-legal",
            "company_type": "law_firm",
            "owner_full_name": "Beryl Owner",
            "owner_email": "owner@beryllegal.in",
            "owner_password": "BerylOwnerPass123!",
        },
    )
    assert tenant_b.status_code == 200, tenant_b.text
    tenant_b_token = str(tenant_b.json()["access_token"])
    _enable_assistant(client, tenant_b_token)
    cross_tenant = _confirm(
        client,
        tenant_b_token,
        assistant_session=assistant_session,
        preview=preview,
    )
    assert cross_tenant.status_code == 404
    assert cross_tenant.json()["type"] == "assistant_action_preview_not_found"

    changed_session = _ask(
        client,
        member_token,
        assistant_session=assistant_session,
        question="What is the title of this matter?",
    )
    assert changed_session.status_code == 200, changed_session.text
    stale = _confirm(
        client,
        member_token,
        assistant_session=assistant_session,
        preview=preview,
    )
    assert stale.status_code == 409
    assert stale.json()["type"] == "assistant_session_version_conflict"

    role = client.post(
        "/api/companies/current/roles",
        headers=auth_headers(owner_token),
        json={
            "name": "Assistant read only",
            "description": "May ask but may not change Matter records.",
            "base_role": "viewer",
            "permissions": ["ai:generate"],
        },
    )
    assert role.status_code == 200, role.text
    assigned = client.post(
        f"/api/companies/current/employees/{member.json()['membership_id']}/role",
        headers=auth_headers(owner_token),
        json={"custom_role_id": role.json()["id"]},
    )
    assert assigned.status_code == 200, assigned.text
    fresh_login = client.post(
        "/api/auth/login",
        json={
            "email": "assistant-action-member@asterlegal.in",
            "password": "AssistantMember123!",
            "company_slug": "aster-legal",
        },
    )
    assert fresh_login.status_code == 200, fresh_login.text
    denied = _confirm(
        client,
        str(fresh_login.json()["access_token"]),
        assistant_session=assistant_session,
        preview=preview,
    )
    assert denied.status_code == 403
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(MatterTask.id))) == 0
