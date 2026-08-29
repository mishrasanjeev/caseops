from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from caseops_api.db.models import (
    AssistantCitation,
    AssistantSession,
    AssistantTurn,
    AuditEvent,
    IpDocument,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    Matter,
    MatterTask,
    ModelRun,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.services.llm import PURPOSE_ASSISTANT
from caseops_api.services.llm_types import LLMCompletion, LLMProviderError
from tests.test_auth_company import auth_headers, bootstrap_company


def _enable_assistant(client: TestClient, token: str) -> None:
    response = client.patch(
        "/api/admin/tenant-ai-policy",
        headers=auth_headers(token),
        json={
            "workspace_assistant_enabled": True,
            "assistant_retention_days": 45,
            "allowed_models_assistant": ["caseops-mock-1"],
            "expected_version": 1,
        },
    )
    assert response.status_code == 200, response.text


def _matter(client: TestClient, token: str, code: str) -> dict:
    response = client.post(
        "/api/matters",
        headers=auth_headers(token),
        json={
            "matter_code": code,
            "title": f"Workspace assistant {code}",
            "practice_area": "Intellectual Property",
            "forum_level": "high_court",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _session(client: TestClient, token: str, matter_id: str) -> dict:
    response = client.post(
        "/api/workspace-assistant/sessions",
        headers=auth_headers(token),
        json={
            "title": "IP file review",
            "scopes": [{"scope_type": "matter", "scope_id": matter_id}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _ask(
    client: TestClient,
    token: str,
    *,
    assistant_session: dict,
    question: str,
):
    return client.post(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/ask",
        headers=auth_headers(token),
        json={
            "expected_version": assistant_session["version"],
            "question": question,
        },
    )


def test_scoped_qa_citations_abstention_proposals_export_and_deletion_boundary(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    headers = auth_headers(token)
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-062B")

    options = client.get(
        "/api/workspace-assistant/scope-options",
        headers=headers,
        params={"q": "AI-062B", "limit": 5},
    )
    assert options.status_code == 200, options.text
    assert options.json()["truncated"] is False
    assert any(
        row["scope_type"] == "matter" and row["scope_id"] == matter["id"]
        for row in options.json()["items"]
    )

    assistant_session = _session(client, token, matter["id"])
    answered = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="What is the status and practice area of this matter?",
    )
    assert answered.status_code == 200, answered.text
    answer = answered.json()
    assistant_session = answer["session"]
    assert answer["assistant_turn"]["status"] == "completed"
    assert answer["assistant_turn"]["render_status"] == "visible"
    assert answer["assistant_turn"]["model"] == {
        "run_id": answer["assistant_turn"]["model"]["run_id"],
        "provider": "mock",
        "model": "caseops-mock-1",
        "purpose": "assistant",
        "prompt_tokens": answer["assistant_turn"]["model"]["prompt_tokens"],
        "completion_tokens": answer["assistant_turn"]["model"]["completion_tokens"],
        "latency_ms": answer["assistant_turn"]["model"]["latency_ms"],
        "status": "ok",
    }
    citation = answer["assistant_turn"]["citations"][0]
    assert citation["source_type"] == "matter"
    assert citation["source_id"] == matter["id"]
    assert citation["source_version"]
    assert citation["source_sha256"]
    assert citation["source_url"] == f"/app/matters/{matter['id']}"
    assert citation["verified_at"]

    with get_session_factory()() as session:
        tasks_before = int(session.scalar(select(func.count(MatterTask.id))) or 0)
    proposed = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="Create a task to review this matter tomorrow.",
    )
    assert proposed.status_code == 200, proposed.text
    proposal_body = proposed.json()
    assistant_session = proposal_body["session"]
    task_proposal = next(
        action
        for action in proposal_body["assistant_turn"]["proposed_actions"]
        if action["action_type"] == "task"
    )
    assert task_proposal["requires_confirmation"] is True
    assert task_proposal["execution_available"] is True
    assert task_proposal["target_version"]
    assert matter["title"] in task_proposal["target_label"]
    assert task_proposal["target_type"] == "matter"
    assert task_proposal["target_id"] == matter["id"]
    assert len(task_proposal["proposal_id"]) == 32
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(MatterTask.id))) == tasks_before

    legal = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="What does the law say under section 21 and which judgment controls?",
    )
    assert legal.status_code == 200, legal.text
    legal_body = legal.json()
    assistant_session = legal_body["session"]
    assert legal_body["assistant_turn"]["status"] == "abstained"
    assert legal_body["assistant_turn"]["citations"] == []
    assert legal_body["assistant_turn"]["model"] is None
    assert any(
        action["href"].startswith("/app/research?")
        for action in legal_body["assistant_turn"]["proposed_actions"]
        if action["action_type"] == "search"
    )

    exported = client.get(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/export",
        headers=headers,
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["schema_version"] == 1
    assert len(exported.json()["turns"]) == 6
    assert "legal-hold-aware" in exported.json()["retention_disposition"]

    deletion = client.delete(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}",
        headers=headers,
    )
    assert deletion.status_code == 409
    assert deletion.json()["type"] == "assistant_deletion_governance_required"

    with get_session_factory()() as session:
        assert session.scalar(select(func.count(AssistantTurn.id))) == 6
        assert session.scalar(select(func.count(AssistantCitation.id))) == 2
        assert session.scalar(select(func.count(ModelRun.id))) == 2
        audit = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "workspace_assistant.question_answered")
            .order_by(AuditEvent.created_at.desc())
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json or "{}")
        assert len(metadata["question_sha256"]) == 64
        assert "section 21" not in (audit.metadata_json or "")


def test_turn_render_and_export_fail_closed_after_scope_permission_changes(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    _enable_assistant(client, owner_token)
    matter = _matter(client, owner_token, "AI-062B-ACL")
    member_response = client.post(
        "/api/companies/current/users",
        headers=auth_headers(owner_token),
        json={
            "full_name": "Scoped Assistant User",
            "email": "scoped-assistant@asterlegal.in",
            "password": "AssistantPass123!",
            "role": "member",
        },
    )
    assert member_response.status_code == 200, member_response.text
    login = client.post(
        "/api/auth/login",
        json={
            "email": "scoped-assistant@asterlegal.in",
            "password": "AssistantPass123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    token = str(login.json()["access_token"])
    assistant_session = _session(client, token, matter["id"])
    answered = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="What is this matter called?",
    )
    assert answered.status_code == 200, answered.text
    assistant_session = answered.json()["session"]

    with get_session_factory()() as session:
        row = session.get(Matter, matter["id"])
        assert row is not None
        row.restricted_access = True
        session.commit()

    turns = client.get(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/turns",
        headers=auth_headers(token),
    )
    assert turns.status_code == 200, turns.text
    assert turns.json()["items"][0]["render_status"] == "visible"
    hidden = turns.json()["items"][1]
    assert hidden["render_status"] == "permission_changed"
    assert hidden["citations"] == []
    assert "access" in hidden["content"].casefold()
    assert matter["title"] not in hidden["content"]

    exported = client.get(
        f"/api/workspace-assistant/sessions/{assistant_session['id']}/export",
        headers=auth_headers(token),
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["session"]["scope_state"] == "permission_changed"
    assert exported.json()["session"]["scopes"] == []
    assert exported.json()["turns"][1]["render_status"] == "permission_changed"
    assert exported.json()["turns"][1]["citations"] == []


def test_provider_wait_releases_database_transaction_and_rejects_a_stale_session(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-062B-CONCURRENT")
    assistant_session = _session(client, token, matter["id"])

    class ConcurrentProvider:
        name = "mock"
        model = "caseops-mock-1"

        def generate(self, messages, *, temperature=0.0, max_tokens=2048):
            with get_session_factory()() as concurrent:
                row = concurrent.get(AssistantSession, assistant_session["id"])
                assert row is not None
                row.version += 1
                concurrent.commit()
            source_id = next(
                line.split(":", 1)[1].strip()
                for message in messages
                for line in message.content.splitlines()
                if line.startswith("SOURCE_ID:")
            )
            payload = {
                "status": "answered",
                "answer": "This answer must lose the concurrency race.",
                "confidence": "medium",
                "used_source_ids": [source_id],
                "suggested_searches": [],
            }
            return LLMCompletion(
                text=json.dumps(payload),
                provider=self.name,
                model=self.model,
                prompt_tokens=10,
                completion_tokens=10,
                latency_ms=1,
            )

    monkeypatch.setattr(
        "caseops_api.services.workspace_assistant.build_provider",
        lambda purpose: ConcurrentProvider(),
    )
    response = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="What is this matter's status?",
    )
    assert response.status_code == 409, response.text
    assert response.json()["type"] == "assistant_session_version_conflict"
    with get_session_factory()() as session:
        row = session.get(AssistantSession, assistant_session["id"])
        assert row is not None
        assert row.version == 2
        assert session.scalar(select(func.count(AssistantTurn.id))) == 0
        assert session.scalar(select(func.count(ModelRun.id))) == 0


def test_provider_failures_are_audited_without_raw_privileged_content(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-062B-FAIL")
    assistant_session = _session(client, token, matter["id"])

    class FailingProvider:
        name = "mock"
        model = "caseops-mock-1"

        def generate(self, messages, *, temperature=0.0, max_tokens=2048):
            raise LLMProviderError("upstream secret body must not be persisted")

    monkeypatch.setattr(
        "caseops_api.services.workspace_assistant.build_provider",
        lambda purpose: FailingProvider(),
    )
    response = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="What is this matter's status?",
    )
    assert response.status_code == 503
    assert response.json()["type"] == "workspace_assistant_unavailable"
    with get_session_factory()() as session:
        turns = session.scalars(
            select(AssistantTurn).order_by(AssistantTurn.sequence.asc())
        ).all()
        assert [turn.status for turn in turns] == ["completed", "failed"]
        run = session.scalar(select(ModelRun))
        assert run is not None
        assert run.status == "failed_provider"
        assert run.error == "LLMProviderError"
        assert "upstream secret" not in (run.error or "")
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "workspace_assistant.question_failed"
            )
        )
        assert audit is not None
        assert "upstream secret" not in (audit.metadata_json or "")


def test_provider_construction_failure_uses_the_same_safe_audited_boundary(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    _enable_assistant(client, token)
    matter = _matter(client, token, "AI-062B-CONFIG-FAIL")
    assistant_session = _session(client, token, matter["id"])

    def fail_to_build(*, purpose: str):
        assert purpose == PURPOSE_ASSISTANT
        raise LLMProviderError("provider configuration secret must not be persisted")

    monkeypatch.setattr(
        "caseops_api.services.workspace_assistant.build_provider",
        fail_to_build,
    )
    response = _ask(
        client,
        token,
        assistant_session=assistant_session,
        question="What is this matter's status?",
    )
    assert response.status_code == 503
    assert response.json()["type"] == "workspace_assistant_unavailable"
    with get_session_factory()() as session:
        run = session.scalar(select(ModelRun))
        assert run is not None
        assert run.provider == "unknown"
        assert run.model == "unknown"
        assert run.status == "failed_provider"
        assert run.error == "LLMProviderError"
        turns = session.scalars(
            select(AssistantTurn).order_by(AssistantTurn.sequence.asc())
        ).all()
        assert [turn.status for turn in turns] == ["completed", "failed"]
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "workspace_assistant.question_failed"
            )
        )
        assert audit is not None
        assert "configuration secret" not in (audit.metadata_json or "")


def test_scope_search_document_policy_work_is_bounded_without_n_plus_one(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    token = str(bootstrap["access_token"])
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    _enable_assistant(client, token)

    with get_session_factory()() as session:
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key="assistant-batch",
            label="Assistant batch",
            updated_by_membership_id=membership_id,
        )
        session.add(taxonomy)
        session.flush()

        def add_documents(start: int, count: int) -> None:
            for index in range(start, start + count):
                document = IpDocument(
                    company_id=company_id,
                    taxonomy_entry_id=taxonomy.id,
                    title=f"Assistant batch evidence {index:02d}",
                    created_by_membership_id=membership_id,
                )
                session.add(document)
                session.flush()
                session.add(
                    IpDocumentVersion(
                        company_id=company_id,
                        document_id=document.id,
                        version=1,
                        original_filename=f"batch-{index:02d}.txt",
                        display_name=f"batch-{index:02d}.txt",
                        storage_key=f"assistant-batch/{index:02d}",
                        content_type="text/plain",
                        size_bytes=32,
                        sha256_hex=f"{index + 1:064x}",
                        processing_status="indexed",
                        extracted_char_count=32,
                        extracted_text=f"Assistant batch evidence {index:02d}",
                        state="draft",
                        uploaded_by_membership_id=membership_id,
                    )
                )

        add_documents(0, 1)
        session.commit()

    def measured_search() -> tuple[int, dict]:
        query_count = 0

        def count_query(*_args: object) -> None:
            nonlocal query_count
            query_count += 1

        engine = get_engine()
        event.listen(engine, "before_cursor_execute", count_query)
        try:
            response = client.get(
                "/api/workspace-assistant/scope-options",
                headers=auth_headers(token),
                params={"q": "Assistant batch", "limit": 20},
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_query)
        assert response.status_code == 200, response.text
        return query_count, response.json()

    one_document_queries, first = measured_search()
    assert len([item for item in first["items"] if item["scope_type"] == "ip_document"]) == 1

    with get_session_factory()() as session:
        taxonomy = session.scalar(
            select(IpDocumentTaxonomyEntry).where(
                IpDocumentTaxonomyEntry.company_id == company_id,
                IpDocumentTaxonomyEntry.key == "assistant-batch",
            )
        )
        assert taxonomy is not None
        for index in range(1, 9):
            document = IpDocument(
                company_id=company_id,
                taxonomy_entry_id=taxonomy.id,
                title=f"Assistant batch evidence {index:02d}",
                created_by_membership_id=membership_id,
            )
            session.add(document)
            session.flush()
            session.add(
                IpDocumentVersion(
                    company_id=company_id,
                    document_id=document.id,
                    version=1,
                    original_filename=f"batch-{index:02d}.txt",
                    display_name=f"batch-{index:02d}.txt",
                    storage_key=f"assistant-batch/{index:02d}",
                    content_type="text/plain",
                    size_bytes=32,
                    sha256_hex=f"{index + 1:064x}",
                    processing_status="indexed",
                    extracted_char_count=32,
                    extracted_text=f"Assistant batch evidence {index:02d}",
                    state="draft",
                    uploaded_by_membership_id=membership_id,
                )
            )
        session.commit()

    many_document_queries, many = measured_search()
    assert len([item for item in many["items"] if item["scope_type"] == "ip_document"]) == 5
    assert many_document_queries <= one_document_queries + 1
    assert many_document_queries <= 20
