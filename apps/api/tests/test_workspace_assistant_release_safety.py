from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from caseops_api.db.models import (
    AssistantTurn,
    AuditEvent,
    Company,
    Matter,
    MatterAttachment,
    ModelRun,
    PrivateSavedOutputAccess,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import workspace_assistant as assistant
from caseops_api.services.private_retrieval_jobs import rebuild_private_index
from tests.test_20260928_assistant_reauthorization_contract import (
    FirstSourceProvider,
    add_wall,
    ask_about_one_document,
    transition,
)
from tests.test_postgres_validation import _ensure_migrations  # noqa: F401
from tests.test_private_retrieval_workflow import _assistant_session
from tests.test_workspace_assistant_qa import _ask, _matter


def test_new_and_retained_abstentions_never_disclose_unmanifested_controls(client, monkeypatch):
    seeded = ask_about_one_document(client, monkeypatch)
    conversation = _assistant_session(
        client, seeded.owner_token, scope_type="matter", scope_id=seeded.matter_id
    )
    secret = "Private provider suggestion or source label"
    private_href = f"/app/matters/{seeded.matter_id}"

    class AbstainingProvider(FirstSourceProvider):
        def generate(self, messages, **kwargs):
            assert any("SOURCE_ID:" in message.content for message in messages)
            completion = super().generate(messages, **kwargs)
            completion.text = json.dumps(
                {
                    "status": "abstained",
                    "answer": secret,
                    "confidence": "insufficient",
                    "used_source_ids": [],
                    "suggested_searches": [secret],
                }
            )
            return completion

    monkeypatch.setattr(assistant, "build_provider", lambda purpose: AbstainingProvider())
    response = _ask(
        client,
        seeded.owner_token,
        assistant_session=conversation,
        question="Open this file and prepare a task",
        no_paid_providers=True,
    )
    assert response.status_code == 200, response.text
    fresh = response.json()["assistant_turn"]

    def assert_safe(turn):
        assert turn["status"] == "abstained"
        assert turn["citations"] == []
        assert secret not in json.dumps(turn)
        assert private_href not in json.dumps(turn)
        assert all(action["target_id"] is None for action in turn["proposed_actions"])
        search = next(
            action for action in turn["proposed_actions"] if action["action_type"] == "search"
        )
        assert search["href"] == "/app/research?query=Open+this+file+and+prepare+a+task"
        assert search["target_label"] is None
        assert not search["requires_confirmation"]

    assert_safe(fresh)
    assert [action["action_type"] for action in fresh["proposed_actions"]] == ["search"]
    with get_session_factory()() as db:
        row = db.get(AssistantTurn, fresh["id"])
        assert row is not None
        stored = row.retrieval_manifest_json
        assert secret not in json.dumps(stored)
        assert private_href not in json.dumps(stored)
        assert (
            db.scalar(
                select(func.count())
                .select_from(PrivateSavedOutputAccess)
                .where(
                    PrivateSavedOutputAccess.assistant_turn_id == row.id,
                )
            )
            == 0
        )
        target = {
            "target_type": "matter",
            "target_id": seeded.matter_id,
            "target_version": "old-source-version",
            "target_label": secret,
        }
        legacy = {
            **stored,
            "suggested_searches": [secret],
            "proposed_actions": [
                {
                    "action_type": "navigation",
                    "proposal_id": "legacy-open",
                    "label": secret,
                    "href": private_href,
                    "requires_confirmation": False,
                    **target,
                },
                {
                    "action_type": "task",
                    "proposal_id": "legacy-task",
                    "label": "Prepare task",
                    "requires_confirmation": True,
                    "execution_available": True,
                    **target,
                },
                {
                    **next(a for a in stored["proposed_actions"] if a["action_type"] == "search"),
                    **target,
                },
            ],
        }
        row.retrieval_manifest_json = legacy
        db.commit()

    transition(seeded, "disposed")
    for path, key in (("turns", "items"), ("turns?snapshot=true", "items"), ("export", "turns")):
        response = client.get(
            f"/api/workspace-assistant/sessions/{conversation['id']}/{path}",
            headers=seeded.owner(),
        )
        assert response.status_code == 200, response.text
        turn = next(row for row in response.json()[key] if row["id"] == fresh["id"])
        assert_safe(turn)
        assert [action["action_type"] for action in turn["proposed_actions"]] == ["search"]
    with get_session_factory()() as db:
        assert db.get(AssistantTurn, fresh["id"]).retrieval_manifest_json == legacy


def test_full_history_reauthorizes_prefix_when_later_source_is_independent(client, monkeypatch):
    seeded = ask_about_one_document(client, monkeypatch)
    second = _matter(client, seeded.owner_token, "ASSISTANT-LATER-INDEPENDENT")
    conversation = _assistant_session(
        client, seeded.member_token, scope_type="matter", scope_id=seeded.matter_id
    )
    first = _ask(
        client,
        seeded.member_token,
        assistant_session=conversation,
        question="Show current evidence",
        no_paid_providers=True,
    )
    assert first.status_code == 200, first.text
    first_turn = first.json()["assistant_turn"]
    assert first_turn["citations"][0]["source_id"] == seeded.matter_id
    def pad_history(first_sequence, end_sequence):
        with get_session_factory()() as db:
            db.add_all(
                AssistantTurn(
                    company_id=seeded.company_id,
                    session_id=conversation["id"],
                    sequence=sequence,
                    role="assistant",
                    status="abstained",
                    content_text="Synthetic retained turn.",
                    content_sha256=assistant._content_hash("Synthetic retained turn."),
                    created_by_membership_id=seeded.member_membership_id,
                )
                for sequence in range(first_sequence, end_sequence)
            )
            db.commit()

    pad_history(3, 51)
    base = f"/api/workspace-assistant/sessions/{conversation['id']}"
    changed = client.put(
        f"{base}/scopes",
        headers=seeded.member(),
        json={
            "expected_version": first.json()["session"]["version"],
            "scopes": [{"scope_type": "matter", "scope_id": second["id"]}],
        },
    )
    assert changed.status_code == 200, changed.text
    later = _ask(
        client,
        seeded.member_token,
        assistant_session=changed.json(),
        question="Show the independent file",
        no_paid_providers=True,
    )
    assert later.status_code == 200, later.text
    later_turn = later.json()["assistant_turn"]
    assert later_turn["citations"][0]["source_id"] == second["id"]
    first_page = client.get(f"{base}/turns", headers=seeded.member()).json()
    assert first_page["has_more"] and len(first_page["items"]) == 50
    first_saved = first_page["items"][1]
    assert first_saved["id"] == first_turn["id"] and first_saved["render_status"] == "visible"
    assert first_saved["content"] == first_turn["content"]
    second_page = client.get(f"{base}/turns?offset=50", headers=seeded.member())
    assert second_page.status_code == 200, second_page.text
    later_saved = second_page.json()["items"][1]
    assert later_saved["id"] == later_turn["id"] and later_saved["render_status"] == "visible"
    assert later_saved["content"] == later_turn["content"]
    newest = client.get(f"{base}/turns?latest=true", headers=seeded.member())
    assert newest.status_code == 200, newest.text
    newest_body = newest.json()
    assert (newest_body["limit"], newest_body["offset"], newest_body["has_more"]) == (50, 0, True)
    assert [item["sequence"] for item in newest_body["items"]] == list(range(3, 53))
    assert newest_body["items"][-1] == later_saved
    for invalid_latest in ("latest=true&offset=1", "latest=true&snapshot=true"):
        rejected = client.get(f"{base}/turns?{invalid_latest}", headers=seeded.member())
        assert rejected.status_code == 422, invalid_latest
    add_wall(seeded)

    clean_page = client.get(f"{base}/turns?offset=50", headers=seeded.member())
    assert clean_page.status_code == 200, clean_page.text
    assert clean_page.json()["items"][1] == later_saved
    pad_history(53, 201)
    invalid = client.get(f"{base}/turns?snapshot=true&offset=50", headers=seeded.member())
    assert invalid.status_code == 422
    snapshot = client.get(f"{base}/turns?snapshot=true", headers=seeded.member())
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert (body["limit"], body["offset"], body["has_more"]) == (200, 0, False)
    assert [item["sequence"] for item in body["items"]] == list(range(1, 201))
    hidden = body["items"][1]
    assert hidden["id"] == first_turn["id"] and hidden["render_status"] == "permission_changed"
    assert hidden["citations"] == hidden["proposed_actions"] == []
    assert first_turn["content"] not in hidden["content"]
    assert body["items"][51] == later_saved


def _document_race(client: TestClient, monkeypatch, *, writer_wins: bool):
    seeded = ask_about_one_document(client, monkeypatch)
    conversation = _assistant_session(
        client, seeded.member_token, scope_type="matter_document", scope_id=seeded.document_id
    )
    company_id = seeded.company_id
    factory = get_session_factory()
    question = "Summarize the hearing strategy evidence."
    with factory() as db:
        initial_version = db.get(Matter, seeded.matter_id).lifecycle_version
        original_digest = db.get(MatterAttachment, seeded.document_id).sha256_hex
    original_generate = assistant.generate_structured
    original_current_sources = assistant._current_sources
    provider_sessions = []
    lock_checks = []

    def capture_session(provider, *, session, **kwargs):
        provider_sessions.append(session)
        return original_generate(provider, session=session, **kwargs)

    class InterleavingProvider(FirstSourceProvider):
        def generate(self, messages, **kwargs):
            assert len(provider_sessions) == 1
            assert not provider_sessions[0].in_transaction()
            completion = super().generate(messages, **kwargs)
            assert json.loads(completion.text)["used_source_ids"] == [
                f"matter_document:{seeded.document_id}"
            ]
            if writer_wins:
                transition(seeded, "disposed")
                transition(seeded, "intake")
                with factory() as db:
                    rebuild_private_index(db, company_id=company_id, activate=True)
                    db.commit()
            return completion

    def probe_after_current_sources(session, **kwargs):
        current = original_current_sources(session, **kwargs)
        assert list(current) == [f"matter_document:{seeded.document_id}"]
        with factory() as competing:
            with pytest.raises(OperationalError) as denied:
                competing.scalar(
                    select(Company.id)
                    .where(Company.id == company_id)
                    .with_for_update(of=Company, key_share=True, nowait=True)
                )
            assert denied.value.orig.sqlstate == "55P03"
        lock_checks.append(True)
        return current

    monkeypatch.setattr(assistant, "build_provider", lambda purpose: InterleavingProvider())
    monkeypatch.setattr(assistant, "generate_structured", capture_session)
    if not writer_wins:
        monkeypatch.setattr(assistant, "_current_sources", probe_after_current_sources)

    def persisted():
        with factory() as db:
            return (
                db.scalar(
                    select(func.count())
                    .select_from(AssistantTurn)
                    .where(
                        AssistantTurn.session_id == conversation["id"],
                    )
                ),
                db.scalar(
                    select(func.count())
                    .select_from(ModelRun)
                    .where(
                        ModelRun.company_id == company_id,
                        ModelRun.purpose == assistant.PURPOSE_ASSISTANT,
                    )
                ),
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.company_id == company_id,
                        AuditEvent.target_id == conversation["id"],
                        AuditEvent.action == "workspace_assistant.question_answered",
                    )
                ),
            )

    before = persisted()
    response = _ask(
        client,
        seeded.member_token,
        assistant_session=conversation,
        question=question,
        no_paid_providers=True,
    )
    if writer_wins:
        assert response.status_code == 409, response.text
        assert response.json()["type"] == "assistant_sources_changed"
        assert persisted() == before
        with factory() as db:
            current = db.get(Matter, seeded.matter_id)
            assert current.status == "intake" and current.lifecycle_version == initial_version + 2
        # The same document bytes are valid for a fresh ask after reopening.
        monkeypatch.setattr(assistant, "build_provider", lambda purpose: FirstSourceProvider())
        fresh = _ask(
            client,
            seeded.member_token,
            assistant_session=conversation,
            question=question,
            no_paid_providers=True,
        )
        assert fresh.status_code == 200 and fresh.json()["assistant_turn"]["status"] == "completed"
        assert fresh.json()["assistant_turn"]["citations"][0]["source_version"] == original_digest
    else:
        assert response.status_code == 200, response.text
        assert lock_checks == [True]
        assert persisted() == (before[0] + 2, before[1] + 1, before[2] + 1)
        transition(seeded, "disposed")
        transition(seeded, "intake")
        history = client.get(
            f"/api/workspace-assistant/sessions/{conversation['id']}/turns", headers=seeded.member()
        )
        assert history.status_code == 200, history.text
        turn = history.json()["items"][1]
        assert turn["render_status"] == "permission_changed" and not turn["citations"]


def test_document_disposal_and_reopen_during_provider_rejects_stale_answer(client, monkeypatch):
    _document_race(client, monkeypatch, writer_wins=True)


@pytest.mark.postgres
@pytest.mark.parametrize("writer_wins", [True, False], ids=["writer-wins", "ask-locks-final-check"])
def test_document_ask_serializes_with_lifecycle_on_postgres(
    isolated_postgres_client, monkeypatch, writer_wins
):
    _document_race(isolated_postgres_client, monkeypatch, writer_wins=writer_wins)
