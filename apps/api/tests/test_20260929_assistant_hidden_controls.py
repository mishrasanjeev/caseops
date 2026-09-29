"""Hidden saved answers redact controls and cannot authorize cached writes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from caseops_api.db.models import (
    AssistantActionPreview,
    AssistantCitation,
    AssistantTurn,
    AuditEvent,
    MatterAttachment,
    MatterTask,
    ModelRun,
    PrivateSavedOutputAccess,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.private_retrieval import propagate_private_projection_change
from tests.test_20260928_assistant_reauthorization_contract import ask_about_one_document
from tests.test_auth_company import auth_headers
from tests.test_private_retrieval_workflow import _assistant_session
from tests.test_workspace_assistant_actions import _confirm, _preview, _write_proposal
from tests.test_workspace_assistant_qa import _ask, _session


def _answer_with_controls(client: TestClient, monkeypatch, *, write: bool = False) -> tuple:
    seeded = ask_about_one_document(client, monkeypatch)
    with get_session_factory()() as session:
        document = session.get(MatterAttachment, seeded.document_id)
        assert document is not None
        term = document.extracted_text.split()[0]
    assistant_session = (
        _session(client, seeded.owner_token, seeded.matter_id)
        if write
        else _assistant_session(
            client,
            seeded.owner_token,
            scope_type="tenant",
            scope_id=seeded.company_id,
        )
    )
    response = _ask(
        client,
        seeded.owner_token,
        assistant_session=assistant_session,
        question=f"Show {term}" + (" and create a task to review this evidence." if write else "."),
        no_paid_providers=True,
    )
    assert response.status_code == 200, response.text
    body, proposal = _write_proposal(response, "task") if write else (response.json(), None)
    turn = body["assistant_turn"]
    assert turn["render_status"] == "visible"
    assert turn["citations"]
    if not write:
        assert any(citation["source_id"] == seeded.document_id for citation in turn["citations"])
    navigation = next(
        action for action in turn["proposed_actions"] if action["action_type"] == "navigation"
    )
    assert navigation["target_label"] and navigation["href"]
    # Retained provider suggestions can contain private labels too. Seed the
    # historical manifest, not a simplified response or a frontend-only mock.
    suggestion = f"Find evidence about {navigation['target_label']}"
    with get_session_factory()() as session:
        saved = session.get(AssistantTurn, turn["id"])
        assert saved is not None
        assert (
            session.scalar(
                select(PrivateSavedOutputAccess.id).where(
                    PrivateSavedOutputAccess.assistant_turn_id == turn["id"],
                    PrivateSavedOutputAccess.source_id == seeded.document_id,
                )
            )
            is not None
        )
        saved.retrieval_manifest_json = {
            **saved.retrieval_manifest_json,
            "suggested_searches": [suggestion],
        }
        session.commit()
    return seeded, body, proposal, navigation, suggestion


def _retained_snapshot(turn_id: str) -> dict:
    with get_session_factory()() as session:
        turn = session.execute(
            select(AssistantTurn.__table__).where(AssistantTurn.id == turn_id)
        ).one()
        return {
            "turn": tuple(turn),
            "citations": list(
                session.execute(
                    select(AssistantCitation.__table__)
                    .where(AssistantCitation.turn_id == turn_id)
                    .order_by(AssistantCitation.id)
                ).all()
            ),
            "sources": list(
                session.execute(
                    select(PrivateSavedOutputAccess.__table__)
                    .where(PrivateSavedOutputAccess.assistant_turn_id == turn_id)
                    .order_by(PrivateSavedOutputAccess.id)
                ).all()
            ),
            "model": list(
                session.execute(
                    select(ModelRun.__table__).where(ModelRun.id == turn.model_run_id)
                ).all()
            ),
        }


@pytest.mark.parametrize(
    "hidden_by",
    [
        "locked",
        "reauthorization_required",
        "redacted",
        "citation_version",
    ],
)
def test_hidden_turns_and_exports_remove_private_labels_links_and_controls(
    client: TestClient,
    monkeypatch,
    hidden_by: str,
) -> None:
    seeded, body, _proposal, navigation, suggestion = _answer_with_controls(client, monkeypatch)
    session_id = body["session"]["id"]
    turn_id = body["assistant_turn"]["id"]
    headers = {**auth_headers(seeded.owner_token), "X-CaseOps-Automated-Test": "no-paid-providers"}

    def read(via: str) -> dict:
        response = client.get(
            f"/api/workspace-assistant/sessions/{session_id}/{via}",
            headers=headers,
        )
        assert response.status_code == 200, response.text
        items = response.json()["items" if via == "turns" else "turns"]
        return next(item for item in items if item["id"] == turn_id)

    for via in ("turns", "export"):
        visible = read(via)
        assert visible["render_status"] == "visible"
        assert visible["suggested_searches"] == [suggestion]
        assert visible["proposed_actions"] == body["assistant_turn"]["proposed_actions"]
    with get_session_factory()() as session:
        if hidden_by == "citation_version":
            session.execute(
                update(AssistantCitation)
                .where(AssistantCitation.turn_id == turn_id)
                .values(source_version="superseded-version")
            )
        else:
            session.execute(
                update(PrivateSavedOutputAccess)
                .where(PrivateSavedOutputAccess.assistant_turn_id == turn_id)
                .values(
                    state=hidden_by,
                    locked_at=datetime.now(UTC),
                    locked_reason="hidden-control-regression",
                )
            )
        session.commit()
    before = _retained_snapshot(turn_id)
    for via in ("turns", "export", "turns"):
        hidden = read(via)
        assert hidden["render_status"] == "permission_changed"
        assert hidden["citations"] == []
        assert hidden["suggested_searches"] == []
        assert hidden["proposed_actions"] == []
        assert navigation["target_label"] not in hidden["content"]
        assert navigation["href"] not in hidden["content"]
        assert hidden["model"] == body["assistant_turn"]["model"]
    citation = body["assistant_turn"]["citations"][0]
    rejected = client.post(
        f"/api/workspace-assistant/sessions/{session_id}/citations/{citation['id']}/open",
        headers=headers,
    )
    assert rejected.status_code == 409, rejected.text
    assert _retained_snapshot(turn_id) == before


@pytest.mark.parametrize("confirmed", [False, True], ids=["pending-write", "confirmed-replay"])
def test_hidden_answer_rejects_cached_preview_confirmation_and_result_replay(
    client: TestClient,
    monkeypatch,
    confirmed: bool,
) -> None:
    seeded, body, proposal, _navigation, _suggestion = _answer_with_controls(
        client,
        monkeypatch,
        write=True,
    )
    assistant_session = body["session"]
    turn_id = body["assistant_turn"]["id"]
    kwargs = {
        "assistant_session": assistant_session,
        "turn_id": turn_id,
        "proposal": proposal,
        "action_input": {"title": "Private saved evidence task"},
    }
    response = _preview(client, seeded.owner_token, **kwargs)
    assert response.status_code == 200, response.text
    preview = response.json()
    if confirmed:
        response = _confirm(
            client, seeded.owner_token, assistant_session=assistant_session, preview=preview
        )
        assert response.status_code == 200, response.text
        assert response.json()["result_href"]
        replay = _confirm(
            client, seeded.owner_token, assistant_session=assistant_session, preview=preview
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["result_id"] == response.json()["result_id"]

    # Lock only the cited document, leaving the write target and its access
    # unchanged. A target-only guard cannot detect the saved-answer boundary.
    with get_session_factory()() as session:
        event = propagate_private_projection_change(
            session,
            company_id=seeded.company_id,
            actor_membership_id=seeded.owner_membership_id,
            idempotency_key=f"hidden-controls:{uuid4()}",
            event_type="source_changed",
            target_type="matter_document",
            target_id=seeded.document_id,
            target_version="reindexed-version",
            reason_code="hidden_control_regression",
        )
        assert event.affected_saved_output_count > 0
        session.commit()
    before = _retained_snapshot(turn_id)

    def action_snapshot() -> tuple:
        with get_session_factory()() as session:
            return (
                session.scalar(select(func.count(MatterTask.id))),
                list(
                    session.execute(
                        select(AssistantActionPreview.__table__).order_by(AssistantActionPreview.id)
                    ).all()
                ),
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.action.in_(
                            [
                                "workspace_assistant.action_previewed",
                                "workspace_assistant.action_confirmed",
                            ]
                        ),
                    )
                ),
            )

    actions_before = action_snapshot()
    # Confirm first: a new preview would supersede the original and mask an
    # executable pending write with an unrelated supersession rejection.
    rejected_confirm = _confirm(
        client, seeded.owner_token, assistant_session=assistant_session, preview=preview
    )
    assert rejected_confirm.status_code == 409, rejected_confirm.text
    assert rejected_confirm.json()["type"] == "assistant_action_answer_hidden"
    rejected_preview = _preview(client, seeded.owner_token, **kwargs)
    assert rejected_preview.status_code == 409, rejected_preview.text
    assert rejected_preview.json()["type"] == "assistant_action_answer_hidden"
    assert action_snapshot() == actions_before
    assert _retained_snapshot(turn_id) == before
