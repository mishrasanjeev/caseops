"""Workspace Assistant saved-answer reauthorization contract (2026-09-28).

``PrivateSavedOutputAccess`` rows exist only for Workspace Assistant answers.
An ``access_changed`` projection event marks an answer's rows
``reauthorization_required``; every other event marks them ``locked``. Each
read then decides again: a ``reauthorization_required`` row is served while
its reader still resolves the same source version, and a ``locked`` row never
is. The turn list does not commit that decision; the session export and a
successful citation open do.

No test covered ``reauthorization_required``. These pin today's contract
through the real endpoints and the real registration path, with a
deterministic provider, before any decision to change it. A member asks two
sessions about one indexed Matter document. The Matter-scoped answer saves the
Matter and the document; the tenant-scoped answer saves only the document. The
document's version is its SHA-256, which no Matter access change alters, while
the Matter's version carries its access policy version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import PrivateSavedOutputAccess
from caseops_api.db.session import get_session_factory
from caseops_api.services.llm_types import LLMCompletion
from caseops_api.services.private_retrieval_jobs import rebuild_private_index
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_private_retrieval_foundation import _create_member
from tests.test_private_retrieval_workflow import (
    _ask_assistant,
    _assistant_session,
    _indexed_matter_attachment,
    _set_ip_workspace_entitlement,
)
from tests.test_workspace_assistant_qa import _enable_assistant, _matter

MATTER_SCOPED = "Matter-scoped answer"
TENANT_SCOPED = "tenant-scoped answer"
ANSWER_TEXT = "Reauthorization contract synthesized answer."
VISIBLE = ("visible", 1)
HIDDEN = ("permission_changed", 0)


class FirstSourceProvider:
    """Answer from the first offered source, as a deterministic provider."""

    name = "reauthorization-contract"
    model = "caseops-mock-1"

    def generate(self, messages, *, temperature=0.0, max_tokens=1024):
        del temperature, max_tokens
        source_ids = [
            line.split(":", 1)[1].strip()
            for message in messages
            for line in message.content.splitlines()
            if line.startswith("SOURCE_ID:")
        ]
        return LLMCompletion(
            text=json.dumps(
                {
                    "status": "answered",
                    "answer": ANSWER_TEXT,
                    "confidence": "medium",
                    "used_source_ids": source_ids[:1],
                    "suggested_searches": [],
                }
            ),
            provider=self.name,
            model=self.model,
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=1,
        )


@dataclass
class Answers:
    client: TestClient
    owner_token: str
    member_token: str
    member_membership_id: str
    matter_id: str
    sessions: dict[str, str]
    turns: dict[str, str]
    citations: dict[str, list[str]]

    def owner(self) -> dict[str, str]:
        return auth_headers(self.owner_token)

    def member(self) -> dict[str, str]:
        return auth_headers(self.member_token)


def saved_rows(answers: Answers, name: str) -> list[tuple[str, str]]:
    """The answer's saved-output rows as (source type, state)."""

    with get_session_factory()() as session:
        return sorted(
            (row.source_type, row.state)
            for row in session.scalars(
                select(PrivateSavedOutputAccess).where(
                    PrivateSavedOutputAccess.assistant_turn_id == answers.turns[name]
                )
            )
        )


def rendered(answers: Answers, name: str, *, via: str = "turns") -> tuple[str, int]:
    """How the member's own read renders the answer: status and citations."""

    session_id = answers.sessions[name]
    response = answers.client.get(
        f"/api/workspace-assistant/sessions/{session_id}/{via}",
        headers=answers.member(),
    )
    assert response.status_code == 200, response.text
    items = response.json()["items" if via == "turns" else "turns"]
    item = next(turn for turn in items if turn["id"] == answers.turns[name])
    assert (ANSWER_TEXT in item["content"]) is (item["render_status"] == "visible")
    return item["render_status"], len(item["citations"])


def open_citation(answers: Answers, name: str) -> int:
    response = answers.client.post(
        f"/api/workspace-assistant/sessions/{answers.sessions[name]}/citations/"
        f"{answers.citations[name][0]}/open",
        headers=answers.member(),
    )
    return response.status_code


def ask_about_one_document(client: TestClient, monkeypatch) -> Answers:
    """Create two member answers about one indexed Matter document."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    owner_membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, owner_token)
    member_membership_id, member_token = _create_member(client, owner_token)
    # A login cookie wins over an explicit bearer; every request below names
    # its actor with a bearer.
    client.cookies.clear()
    matter_id = str(_matter(client, owner_token, "ASSISTANT-REAUTH")["id"])
    # The question's only distinctive term appears in the document alone, so a
    # tenant-scoped answer saves the document and not the Matter.
    term = f"Reauthcontract{uuid4().hex[:12]}"
    _indexed_matter_attachment(
        matter_id=matter_id,
        membership_id=owner_membership_id,
        text=f"{term} hearing strategy evidence for the opposition.",
    )
    _set_ip_workspace_entitlement(company_id)
    monkeypatch.setenv("CASEOPS_IP_WORKSPACE_ENABLED", "true")
    get_settings.cache_clear()
    with get_session_factory()() as session:
        rebuild_private_index(session, company_id=company_id, activate=True)
        session.commit()
    monkeypatch.setattr(
        "caseops_api.services.workspace_assistant.build_provider",
        lambda purpose: FirstSourceProvider(),
    )
    sessions = {
        MATTER_SCOPED: _assistant_session(
            client, member_token, scope_type="matter", scope_id=matter_id
        ),
        TENANT_SCOPED: _assistant_session(
            client, member_token, scope_type="tenant", scope_id=company_id
        ),
    }
    turns: dict[str, str] = {}
    citations: dict[str, list[str]] = {}
    for name, assistant_session in sessions.items():
        response = _ask_assistant(
            client,
            member_token,
            assistant_session=assistant_session,
            question=f"Summarize {term}.",
        )
        assert response.status_code == 200, response.text
        turn = response.json()["assistant_turn"]
        assert turn["status"] == "completed", turn
        turns[name] = str(turn["id"])
        citations[name] = [str(citation["id"]) for citation in turn["citations"]]
        assert len(citations[name]) == 1, turn
    answers = Answers(
        client=client,
        owner_token=owner_token,
        member_token=member_token,
        member_membership_id=member_membership_id,
        matter_id=matter_id,
        sessions={name: str(row["id"]) for name, row in sessions.items()},
        turns=turns,
        citations=citations,
    )
    assert saved_rows(answers, MATTER_SCOPED) == [
        ("matter", "accessible"),
        ("matter_document", "accessible"),
    ]
    assert saved_rows(answers, TENANT_SCOPED) == [("matter_document", "accessible")]
    assert rendered(answers, MATTER_SCOPED) == VISIBLE
    assert rendered(answers, TENANT_SCOPED) == VISIBLE
    return answers


def add_wall(answers: Answers) -> str:
    response = answers.client.post(
        f"/api/matters/{answers.matter_id}/access/walls",
        headers=answers.owner(),
        json={
            "excluded_membership_id": answers.member_membership_id,
            "reason": "Contract test wall.",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def remove_wall(answers: Answers, wall_id: str) -> None:
    response = answers.client.delete(
        f"/api/matters/{answers.matter_id}/access/walls/{wall_id}",
        headers=answers.owner(),
    )
    assert response.status_code == 204, response.text


def transition(answers: Answers, to_status: str) -> None:
    current = answers.client.get(f"/api/matters/{answers.matter_id}", headers=answers.owner())
    assert current.status_code == 200, current.text
    response = answers.client.patch(
        f"/api/matters/{answers.matter_id}/lifecycle/status",
        headers=answers.owner(),
        json={
            "to_status": to_status,
            "expected_from_status": current.json()["status"],
            "expected_updated_at": current.json()["updated_at"],
            "reason": f"Contract test moves this Matter to {to_status}.",
        },
    )
    assert response.status_code == 200, response.text


def all_rows(answers: Answers) -> dict[str, list[tuple[str, str]]]:
    return {name: saved_rows(answers, name) for name in answers.turns}


def rows_in_state(state: str) -> dict[str, list[tuple[str, str]]]:
    return {
        MATTER_SCOPED: [("matter", state), ("matter_document", state)],
        TENANT_SCOPED: [("matter_document", state)],
    }


def test_access_change_that_keeps_access_reauthorizes_on_every_read(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    # Unrelated events leave both answers untouched.
    unrelated = str(_matter(client, answers.owner_token, "ASSISTANT-UNRELATED")["id"])
    granted_elsewhere = client.post(
        f"/api/matters/{unrelated}/access/grants",
        headers=answers.owner(),
        json={"membership_id": answers.member_membership_id, "reason": "Other work."},
    )
    assert granted_elsewhere.status_code == 200, granted_elsewhere.text
    assert all_rows(answers) == rows_in_state("accessible")

    # A grant on the answers' own Matter keeps the member's access but is an
    # access change: every saved row now needs reauthorization.
    granted = client.post(
        f"/api/matters/{answers.matter_id}/access/grants",
        headers=answers.owner(),
        json={"membership_id": answers.member_membership_id, "reason": "Assigned."},
    )
    assert granted.status_code == 200, granted.text
    assert all_rows(answers) == rows_in_state("reauthorization_required")

    for _read in range(2):
        # The document-only answer is served again; the Matter's version
        # moved with its access policy, so the answer that saved it is not.
        assert rendered(answers, TENANT_SCOPED) == VISIBLE
        assert rendered(answers, MATTER_SCOPED) == HIDDEN
        # The turn list decides on every read and commits nothing.
        assert all_rows(answers) == rows_in_state("reauthorization_required")


def test_access_loss_hides_and_restore_serves_the_document_answer_again(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    wall_id = add_wall(answers)
    assert all_rows(answers) == rows_in_state("reauthorization_required")
    assert rendered(answers, TENANT_SCOPED) == HIDDEN
    assert rendered(answers, MATTER_SCOPED) == HIDDEN
    # Hidden by the read, but not locked: the turn list commits nothing.
    assert all_rows(answers) == rows_in_state("reauthorization_required")

    remove_wall(answers, wall_id)
    assert all_rows(answers) == rows_in_state("reauthorization_required")
    assert rendered(answers, TENANT_SCOPED) == VISIBLE
    assert rendered(answers, MATTER_SCOPED) == HIDDEN

    # A refused citation open rolls back; a successful one commits the
    # reauthorization it made.
    assert open_citation(answers, MATTER_SCOPED) == 409
    assert (
        saved_rows(answers, MATTER_SCOPED)
        == rows_in_state("reauthorization_required")[MATTER_SCOPED]
    )
    assert open_citation(answers, TENANT_SCOPED) == 200
    assert saved_rows(answers, TENANT_SCOPED) == [("matter_document", "accessible")]


def test_export_during_an_access_loss_locks_the_answer_for_good(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    wall_id = add_wall(answers)
    # The export decides like the turn list, then commits its audit event and
    # with it the lock the decision made.
    assert rendered(answers, TENANT_SCOPED, via="export") == HIDDEN
    assert saved_rows(answers, TENANT_SCOPED) == [("matter_document", "locked")]
    assert (
        saved_rows(answers, MATTER_SCOPED)
        == rows_in_state("reauthorization_required")[MATTER_SCOPED]
    )

    # Restoring access does not reach a locked row. Compare the previous test,
    # where the same restore served the answer again.
    remove_wall(answers, wall_id)
    assert saved_rows(answers, TENANT_SCOPED) == [("matter_document", "locked")]
    assert rendered(answers, TENANT_SCOPED) == HIDDEN
    assert open_citation(answers, TENANT_SCOPED) == 409


def test_a_non_access_event_locks_the_answer_for_good(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    transition(answers, "disposed")
    assert all_rows(answers) == rows_in_state("locked")
    transition(answers, "intake")
    assert all_rows(answers) == rows_in_state("locked")

    # The member reads the reopened Matter and its unchanged document again,
    # yet neither answer returns.
    matter = client.get(f"/api/matters/{answers.matter_id}", headers=answers.member())
    assert matter.status_code == 200, matter.text
    assert rendered(answers, TENANT_SCOPED) == HIDDEN
    assert rendered(answers, MATTER_SCOPED) == HIDDEN
    assert open_citation(answers, TENANT_SCOPED) == 409
