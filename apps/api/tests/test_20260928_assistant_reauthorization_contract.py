"""Workspace Assistant saved answers stay locked after any event (2026-09-28).

``PrivateSavedOutputAccess`` rows exist only for Workspace Assistant answers.
Until 2026-09-28 an ``access_changed`` projection event marked an answer's rows
``reauthorization_required`` and each read decided again: a document-only
answer came back once its author could read the document again, while an
answer that also saved the Matter stayed hidden because the Matter's version
carries its access policy version. The turn list committed nothing, but the
export and a citation open committed their decision, so an export during a
temporary loss locked an answer for good that the turn list would later serve.

The user decided (2026-09-28) that answers lock for good after any relevant
event, access included, as Reviews and Drafts do, and that no read ever saves a
decision. These tests prove it through the real endpoints and registration
path with a deterministic provider: a member asks two sessions about one
indexed Matter document; the Matter-scoped answer saves the Matter and the
document, the tenant-scoped answer only the document. They also prove that an
event reaches a document the index no longer holds, an IP docket's typed
records and linked documents, and any number of saved answers in one statement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select, update

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    IpDocumentLink,
    MatterAttachment,
    PrivateSavedOutputAccess,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.llm_types import LLMCompletion
from caseops_api.services.private_retrieval import (
    propagate_private_projection_change,
    register_private_saved_output,
)
from caseops_api.services.private_retrieval_jobs import rebuild_private_index
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_document_workflow import _upload
from tests.test_ip_record_workflow import _application, _asset, _docket
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
ANSWER_TEXT = "Saved-answer contract synthesized answer."
VISIBLE = ("visible", 1)
HIDDEN = ("permission_changed", 0)


class FirstSourceProvider:
    """Answer from the first offered source, as a deterministic provider."""

    name = "saved-answer-contract"
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
                    "status": "answered" if source_ids else "abstained",
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
    company_id: str
    owner_token: str
    owner_membership_id: str
    member_token: str
    member_membership_id: str
    matter_id: str
    document_id: str
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


def persisted_rows(answers: Answers) -> list[tuple]:
    """Every saved-output field a read could write, as the database holds it."""

    with get_session_factory()() as session:
        return sorted(
            session.execute(
                select(
                    PrivateSavedOutputAccess.id,
                    PrivateSavedOutputAccess.state,
                    PrivateSavedOutputAccess.locked_reason,
                    PrivateSavedOutputAccess.locked_at,
                    PrivateSavedOutputAccess.last_reauthorized_at,
                    PrivateSavedOutputAccess.updated_at,
                ).where(PrivateSavedOutputAccess.assistant_turn_id.in_(answers.turns.values()))
            ).all()
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


def every_read(answers: Answers) -> dict[str, tuple]:
    """The turn list, the export and a citation open, for both answers."""

    return {
        name: (
            rendered(answers, name),
            rendered(answers, name, via="export"),
            open_citation(answers, name),
        )
        for name in answers.turns
    }


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
    matter_id = str(_matter(client, owner_token, "ASSISTANT-SAVED")["id"])
    # The question's only distinctive term appears in the document alone, so a
    # tenant-scoped answer saves the document and not the Matter.
    term = f"Savedanswer{uuid4().hex[:12]}"
    document_id = _indexed_matter_attachment(
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
        company_id=company_id,
        owner_token=owner_token,
        owner_membership_id=owner_membership_id,
        member_token=member_token,
        member_membership_id=member_membership_id,
        matter_id=matter_id,
        document_id=document_id,
        sessions={name: str(row["id"]) for name, row in sessions.items()},
        turns=turns,
        citations=citations,
    )
    assert all_rows(answers) == rows_in_state("accessible")
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


HIDDEN_EVERYWHERE = (HIDDEN, HIDDEN, 409)


def test_an_access_change_that_keeps_access_locks_both_answers_for_good(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    # Unrelated source creation and access events leave both answers alone.
    unrelated = str(_matter(client, answers.owner_token, "ASSISTANT-UNRELATED")["id"])
    granted_elsewhere = client.post(
        f"/api/matters/{unrelated}/access/grants",
        headers=answers.owner(),
        json={"membership_id": answers.member_membership_id, "reason": "Other work."},
    )
    assert granted_elsewhere.status_code == 200, granted_elsewhere.text
    assert all_rows(answers) == rows_in_state("accessible")

    # A grant on the answers' own Matter keeps the member's access, but it is
    # an access change: both answers lock for good, the document-only one too.
    granted = client.post(
        f"/api/matters/{answers.matter_id}/access/grants",
        headers=answers.owner(),
        json={"membership_id": answers.member_membership_id, "reason": "Assigned."},
    )
    assert granted.status_code == 200, granted.text
    assert all_rows(answers) == rows_in_state("locked")
    assert every_read(answers) == {name: HIDDEN_EVERYWHERE for name in answers.turns}
    assert all_rows(answers) == rows_in_state("locked")


def test_an_access_loss_and_its_restore_leave_both_answers_locked(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    wall_id = add_wall(answers)
    assert all_rows(answers) == rows_in_state("locked")
    assert rendered(answers, TENANT_SCOPED) == HIDDEN
    assert rendered(answers, MATTER_SCOPED) == HIDDEN

    # Restoring access does not bring the answers back, whatever the member
    # opened during the loss.
    remove_wall(answers, wall_id)
    assert all_rows(answers) == rows_in_state("locked")
    assert every_read(answers) == {name: HIDDEN_EVERYWHERE for name in answers.turns}


def test_reads_never_write_a_saved_answer_state(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    # A tenant-scoped row left in reauthorization_required before 2026-09-28
    # stays hidden, and no read path turns it back into an accessible row.
    with get_session_factory()() as session:
        session.execute(
            update(PrivateSavedOutputAccess)
            .where(PrivateSavedOutputAccess.assistant_turn_id == answers.turns[TENANT_SCOPED])
            .values(
                state="reauthorization_required",
                locked_reason="legacy_access_changed",
                locked_at=datetime.now(UTC),
            )
        )
        session.commit()
    before = persisted_rows(answers)
    reads = every_read(answers)
    assert reads[TENANT_SCOPED] == HIDDEN_EVERYWHERE
    # The untouched Matter-scoped answer stays served through every path.
    assert reads[MATTER_SCOPED] == (VISIBLE, VISIBLE, 200)
    assert persisted_rows(answers) == before
    assert saved_rows(answers, TENANT_SCOPED) == [("matter_document", "reauthorization_required")]


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
    assert every_read(answers) == {name: HIDDEN_EVERYWHERE for name in answers.turns}


def test_an_access_event_locks_a_document_answer_the_index_no_longer_holds(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)

    # The document is queued for processing again and a rebuild drops it from
    # the private index, so the event's generation holds no projection of it.
    with get_session_factory()() as session:
        attachment = session.get(MatterAttachment, answers.document_id)
        assert attachment is not None
        attachment.processing_status = "pending"
        session.commit()
        rebuild_private_index(session, company_id=answers.company_id, activate=True)
        session.commit()
    assert rendered(answers, TENANT_SCOPED) == VISIBLE

    wall_id = add_wall(answers)
    remove_wall(answers, wall_id)
    assert all_rows(answers) == rows_in_state("locked")
    assert rendered(answers, TENANT_SCOPED) == HIDDEN


def test_an_ip_docket_event_locks_its_records_and_linked_documents(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)
    headers = answers.owner()
    # The docket's own records, built with the IP record workflow's endpoints
    # as the opposition fixtures build them.
    docket = _docket(client, headers, "Saved-answer docket")
    other = _docket(client, headers, "Saved-answer unrelated docket")
    asset = _asset(client, headers, docket["id"], "SAVED MARK")
    application = _application(client, headers, docket["id"], asset["id"])
    proceeding = client.post(
        f"/api/ip/dockets/{docket['id']}/proceedings",
        headers=headers,
        json={
            "application_id": application["id"],
            "proceeding_kind": "opposition",
            "side": "opponent",
            "office": "Trade Marks Registry Delhi",
            "jurisdiction": "IN",
            "stage": "draft",
            "origin_kind": "manual_intake",
            "source_pending_identifier_allocation": True,
        },
    )
    assert proceeding.status_code == 201, proceeding.text
    proceeding_id = str(proceeding.json()["id"])
    assert client.post("/api/ip/document-taxonomy/seed", headers=headers).status_code == 200

    def upload(label: str, docket_id: str) -> str:
        content = f"{label} saved-answer evidence {uuid4()}".encode() * 8
        return str(
            _upload(
                client,
                headers,
                filename=f"{label}.txt",
                content=content,
                docket_id=docket_id,
            )["document"]["id"]
        )

    linked_to_docket = upload("docket", docket["id"])
    linked_elsewhere = upload("elsewhere", other["id"])
    # Documents that reach the docket only through one of its children.
    through_children = {
        "application": (upload("application", other["id"]), str(application["id"])),
        "proceeding": (upload("proceeding", other["id"]), proceeding_id),
    }
    with get_session_factory()() as session:
        for child_type, (document_id, child_id) in through_children.items():
            session.add(
                IpDocumentLink(
                    company_id=answers.company_id,
                    document_id=document_id,
                    target_type=child_type,
                    target_id=child_id,
                    **{f"{child_type}_id": child_id},
                    created_by_membership_id=answers.owner_membership_id,
                )
            )
        session.commit()

    reached = {
        ("ip_docket", str(docket["id"])),
        ("ip_asset", str(asset["id"])),
        ("trademark_application", str(application["id"])),
        ("ip_proceeding", proceeding_id),
        ("ip_document", linked_to_docket),
        *(("ip_document", document_id) for document_id, _child in through_children.values()),
    }
    untouched = {
        ("ip_docket", str(other["id"])),
        ("ip_document", linked_elsewhere),
        ("matter", answers.matter_id),
    }
    anchor = answers.turns[TENANT_SCOPED]
    with get_session_factory()() as session:
        register_private_saved_output(
            session,
            company_id=answers.company_id,
            assistant_turn_id=anchor,
            sources=[(kind, key, "saved-version", None) for kind, key in reached | untouched],
        )
        session.commit()
        event_row = propagate_private_projection_change(
            session,
            company_id=answers.company_id,
            actor_membership_id=answers.owner_membership_id,
            idempotency_key=f"saved-answer-docket:{uuid4()}",
            event_type="access_changed",
            target_type="ip_docket",
            target_id=str(docket["id"]),
            target_version="1",
            reason_code="saved_answer_docket_access_changed",
        )
        session.commit()
        locked_count = event_row.affected_saved_output_count
        states = {
            (row.source_type, row.source_id): row.state
            for row in session.scalars(
                select(PrivateSavedOutputAccess).where(
                    PrivateSavedOutputAccess.assistant_turn_id == anchor,
                    PrivateSavedOutputAccess.source_version == "saved-version",
                )
            )
        }
    assert {key: states[key] for key in reached} == dict.fromkeys(reached, "locked")
    assert {key: states[key] for key in untouched} == dict.fromkeys(untouched, "accessible")
    assert locked_count == len(reached)


def test_one_event_locks_any_number_of_saved_answers_in_one_statement(
    client: TestClient,
    monkeypatch,
) -> None:
    answers = ask_about_one_document(client, monkeypatch)
    anchor = answers.turns[TENANT_SCOPED]
    small = str(_matter(client, answers.owner_token, "ASSISTANT-SMALL")["id"])
    large = str(_matter(client, answers.owner_token, "ASSISTANT-LARGE")["id"])
    documents = {
        matter_id: _indexed_matter_attachment(
            matter_id=matter_id,
            membership_id=answers.owner_membership_id,
            text=f"Bounded saved-answer lock {matter_id} {uuid4()}.",
        )
        for matter_id in (small, large)
    }
    with get_session_factory()() as session:
        for matter_id, copies in ((small, 2), (large, 60)):
            register_private_saved_output(
                session,
                company_id=answers.company_id,
                assistant_turn_id=anchor,
                sources=[
                    ("matter_document", documents[matter_id], f"version-{index}", None)
                    for index in range(copies)
                ],
            )
        session.commit()

    def lock(matter_id: str) -> tuple[int, list[str]]:
        statements: list[str] = []

        def record(_conn, _cursor, statement, _params, _context, _many) -> None:
            if "private_saved_output_access" in statement:
                statements.append(statement)

        with get_session_factory()() as session:
            engine = session.get_bind()
            sqlalchemy_event.listen(engine, "before_cursor_execute", record)
            try:
                event_row = propagate_private_projection_change(
                    session,
                    company_id=answers.company_id,
                    actor_membership_id=answers.owner_membership_id,
                    idempotency_key=f"saved-answer-bound:{uuid4()}",
                    event_type="access_changed",
                    target_type="matter",
                    target_id=matter_id,
                    target_version="1",
                    reason_code="saved_answer_bound",
                )
                session.commit()
            finally:
                sqlalchemy_event.remove(engine, "before_cursor_execute", record)
            return event_row.affected_saved_output_count, statements

    small_count, small_statements = lock(small)
    large_count, large_statements = lock(large)
    assert (small_count, large_count) == (2, 60)
    assert len(large_statements) == len(small_statements) <= 2, "\n\n".join(large_statements)
