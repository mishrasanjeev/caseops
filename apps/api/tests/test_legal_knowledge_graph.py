from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AffidavitIntelligenceRun,
    AffidavitQuestion,
    AffidavitStatement,
    AuditEvent,
    DocumentProcessingStatus,
    LegalKnowledgeGraphEdge,
    LegalKnowledgeGraphNode,
    LegalKnowledgeGraphRun,
    LitigationIntelligenceReviewAction,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    MatterCourtOrder,
    MatterProceedingSignal,
    MockHearingQuestion,
    MockHearingResponse,
    MockHearingSession,
    PredictiveSignalEvidence,
    PredictiveSignalItem,
    PredictiveSignalRun,
    Team,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.legal_knowledge_graph import LegalKnowledgeGraphNodeRecord
from caseops_api.services import legal_knowledge_graph as graph_service
from caseops_api.services.legal_knowledge_graph import SOURCE_SNIPPET_LIMIT


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, slug: str) -> dict[str, object]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} Firm",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug.title()} Owner",
            "owner_email": f"owner@{slug}.in",
            "owner_password": "StrongPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_matter(client: TestClient, token: str, code: str) -> str:
    response = client.post(
        "/api/matters/",
        headers=_auth(token),
        json={
            "title": f"Knowledge Graph {code}",
            "matter_code": code,
            "client_name": "Acme Industries",
            "opposing_party": "Beta Projects",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "intake",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _dispose_matter(matter_id: str) -> None:
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.status = "disposed"
        matter.is_active = False
        session.commit()


def _long_quote(label: str) -> str:
    repeated = f"{label.lower()} source text \x00 with controls. " * 80
    return f"{label} {repeated}TAIL-{label}"


def _invite_member(
    client: TestClient,
    *,
    owner_token: str,
    company_slug: str,
    email: str,
    role: str = "member",
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": "Graph Member",
            "email": email,
            "role": role,
            "password": "MemberPass123!",
        },
    )
    assert response.status_code == 200, response.text
    membership_id = str(response.json()["membership_id"])
    login = client.post(
        "/api/auth/login",
        json={
            "company_slug": company_slug,
            "email": email,
            "password": "MemberPass123!",
        },
    )
    assert login.status_code == 200, login.text
    return membership_id, str(login.json()["access_token"])


def _seed_graph_records(matter_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        order = MatterCourtOrder(
            matter_id=matter.id,
            order_date=date(2026, 5, 12),
            title="Daily order sheet",
            summary="Imported from source.",
            order_text=(
                "Respondent shall file reply affidavit by 20.05.2026. "
                "List before Justice Source on 10.06.2026."
            ),
            source="manual-test",
            source_reference="fixture:graph:order",
            bench_name="Justice Source",
            order_kind="daily_order",
        )
        session.add(order)
        session.flush()
        signal = MatterProceedingSignal(
            company_id=matter.company_id,
            matter_id=matter.id,
            court_order_id=order.id,
            signal_type="reply_affidavit_deadline",
            signal_text="Respondent shall file reply affidavit by 20.05.2026.",
            action_required="File reply affidavit",
            due_on=date(2026, 5, 20),
            confidence_label="high",
            source_snippet="Respondent shall file reply affidavit by 20.05.2026.",
            review_status="auto_promoted",
            extraction_method="deterministic",
            parser_version="caseops-proceeding-deterministic-v1",
            source_hash=uuid4().hex + uuid4().hex,
            dedupe_key=uuid4().hex,
        )
        session.add(signal)

        attachment = MatterAttachment(
            matter_id=matter.id,
            original_filename="chief-affidavit.txt",
            storage_key=f"test/li-s11/{uuid4().hex}.txt",
            content_type="text/plain",
            size_bytes=160,
            sha256_hex=(uuid4().hex + uuid4().hex)[:64],
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=160,
            extracted_text="I state that respondent paid Rs. 10,000 under Invoice A.",
            document_type="chief_affidavit",
            lifecycle_stage="pleadings",
        )
        session.add(attachment)
        session.flush()
        chunk = MatterAttachmentChunk(
            attachment_id=attachment.id,
            chunk_index=0,
            content=attachment.extracted_text or "",
            token_count=10,
        )
        session.add(chunk)
        session.flush()
        affidavit_run = AffidavitIntelligenceRun(
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            status="completed",
            extraction_method="deterministic",
            parser_version="caseops-affidavit-deterministic-v1",
            source_hash=uuid4().hex + uuid4().hex,
            source_char_count=160,
            missing_data_json="[]",
            disclaimer="Affidavit intelligence is source-backed, not legal advice.",
        )
        session.add(affidavit_run)
        session.flush()
        statement = AffidavitStatement(
            run_id=affidavit_run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            source_chunk_id=chunk.id,
            source_chunk_index=0,
            statement_type="evidence_gap",
            statement_text="Payment assertion requires invoice support.",
            source_quote="respondent paid Rs. 10,000 under Invoice A",
            confidence_label="medium",
            review_status="review_required",
            dedupe_key=uuid4().hex,
        )
        session.add(statement)
        session.flush()
        affidavit_question = AffidavitQuestion(
            run_id=affidavit_run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            statement_id=statement.id,
            source_chunk_id=chunk.id,
            source_chunk_index=0,
            category="document_support",
            question_text="Which invoice supports the payment statement?",
            reason="The affidavit claims payment but needs source support.",
            source_quote=statement.source_quote,
            confidence_label="low",
            review_required=True,
            review_status="review_required",
            dedupe_key=uuid4().hex,
        )
        session.add(affidavit_question)
        session.flush()

        mock_session = MockHearingSession(
            company_id=matter.company_id,
            matter_id=matter.id,
            source_affidavit_run_id=affidavit_run.id,
            mode="client_preparation",
            status="completed",
            review_status="review_required",
            disclaimer="Mock hearing feedback is source-backed, not legal advice.",
            scorecard_json=json.dumps(
                {
                    "total_questions": 1,
                    "answered_questions": 1,
                    "responses_recorded": 1,
                    "answered_question_count": 1,
                    "unsupported_assertion_count": 1,
                    "missing_document_reference_count": 1,
                    "contradiction_count": 0,
                    "review_required_count": 1,
                    "average_response_seconds": 24,
                }
            ),
            total_questions=1,
            answered_questions=1,
            unsupported_assertion_count=1,
            missing_document_reference_count=1,
            review_required_count=1,
        )
        session.add(mock_session)
        session.flush()
        mock_question = MockHearingQuestion(
            company_id=matter.company_id,
            matter_id=matter.id,
            session_id=mock_session.id,
            source_affidavit_run_id=affidavit_run.id,
            source_affidavit_question_id=affidavit_question.id,
            source_affidavit_statement_id=statement.id,
            source_attachment_id=attachment.id,
            source_chunk_id=chunk.id,
            source_chunk_index=0,
            turn_index=1,
            category="document_support",
            question_text=affidavit_question.question_text,
            reason=affidavit_question.reason,
            source_quote=affidavit_question.source_quote,
            difficulty_label="low",
            status="answered",
        )
        session.add(mock_question)
        session.flush()
        session.add(
            MockHearingResponse(
                company_id=matter.company_id,
                matter_id=matter.id,
                session_id=mock_session.id,
                question_id=mock_question.id,
                source_affidavit_question_id=affidavit_question.id,
                response_text="Invoice A is not available in the file.",
                response_word_count=8,
                answered_question=True,
                consistency_with_affidavit=True,
                unsupported_assertion_added=True,
                missing_document_reference=True,
                contradiction_with_source=False,
                response_completeness="medium",
                confidence_label="low",
                feedback_text="Response needs document support review.",
                evaluation_json="{}",
                source_quote=affidavit_question.source_quote,
                review_required=True,
                review_status="review_required",
            )
        )

        predictive_run = PredictiveSignalRun(
            company_id=matter.company_id,
            matter_id=matter.id,
            status="completed",
            mode="predictive",
            sample_size=5,
            evidence_quality="thin",
            disclaimer="Predictive intelligence is source-backed, not legal advice.",
            limitation_note="Observed source labels only.",
        )
        session.add(predictive_run)
        session.flush()
        predictive_item = PredictiveSignalItem(
            run_id=predictive_run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            signal_type="interim_relief_likelihood",
            status="supported",
            label="Interim relief likelihood",
            estimate_label="mixed historical source-label band",
            sample_size=5,
            confidence_label="low",
            confidence_band_low=0.17,
            confidence_band_high=0.64,
            limitation_note="Observed source labels only.",
            features_json="[]",
            missing_data_json="[]",
        )
        session.add(predictive_item)
        session.flush()
        session.add(
            PredictiveSignalEvidence(
                run_id=predictive_run.id,
                item_id=predictive_item.id,
                company_id=matter.company_id,
                matter_id=matter.id,
                source_type="matter_court_order",
                source_id=order.id,
                title=order.title,
                source_reference=order.source_reference,
                excerpt="Respondent shall file reply affidavit by 20.05.2026.",
                source_date="2026-05-12",
                weight=1.0,
            )
        )
        session.add(
            LitigationIntelligenceReviewAction(
                company_id=matter.company_id,
                matter_id=matter.id,
                item_type="affidavit_question",
                item_id=f"affidavit-question:{affidavit_question.id}",
                source_type="affidavit_question",
                source_id=affidavit_question.id,
                action="accept",
                note="Accepted for hearing prep.",
                status_before="review_required",
                status_after="reviewed",
            )
        )
        session.commit()


def test_legal_knowledge_graph_materializes_source_backed_matter_graph(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s11-main-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S11-MAIN")
    _seed_graph_records(matter_id)

    response = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["status"] == "completed"
    assert payload["summary"]["node_count"] >= 10
    assert payload["summary"]["edge_count"] >= 8
    assert "not legal advice" in payload["disclaimer"].lower()
    node_types = {node["node_type"] for node in payload["nodes"]}
    assert {
        "matter",
        "proceeding_signal",
        "affidavit_statement",
        "affidavit_question",
        "mock_hearing_question",
        "mock_hearing_response",
        "predictive_signal",
        "bench_context",
        "legal_source",
        "review_action",
    }.issubset(node_types)
    assert all(
        node["source_quote"] or node["limitation_note"]
        for node in payload["nodes"]
    )
    assert all(
        edge["source_quote"] or edge["limitation_note"]
        for edge in payload["edges"]
    )
    edge_types = {edge["edge_type"] for edge in payload["edges"]}
    assert {"derived_from", "references", "relates_to", "prompts"}.issubset(edge_types)

    get_response = client.get(
        f"/api/matters/{matter_id}/legal-knowledge-graph",
        headers=_auth(token),
    )
    assert get_response.status_code == 200, get_response.text
    assert get_response.json()["run_id"] == payload["run_id"]

    factory = get_session_factory()
    with factory() as session:
        actions = [
            event.action
            for event in session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == str(boot["company"]["id"]))
                .order_by(AuditEvent.created_at.asc())
            )
        ]
    assert "legal_knowledge_graph.materialized" in actions
    assert "legal_knowledge_graph.viewed" in actions


def test_disposed_matter_blocks_graph_materialization_without_graph_side_effects(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s11-disposed-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S11-DISPOSED")
    _seed_graph_records(matter_id)
    _dispose_matter(matter_id)

    response = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )

    assert response.status_code == 409, response.text
    assert "disposed" in response.json()["detail"].lower()
    listed = client.get(
        f"/api/matters/{matter_id}/legal-knowledge-graph",
        headers=_auth(token),
    )
    assert listed.status_code == 200, listed.text
    with get_session_factory()() as session:
        assert session.scalar(
            select(LegalKnowledgeGraphRun).where(
                LegalKnowledgeGraphRun.matter_id == matter_id
            )
        ) is None
        assert session.scalar(
            select(LegalKnowledgeGraphNode).where(
                LegalKnowledgeGraphNode.matter_id == matter_id
            )
        ) is None
        assert session.scalar(
            select(LegalKnowledgeGraphEdge).where(
                LegalKnowledgeGraphEdge.matter_id == matter_id
            )
        ) is None


def test_graph_materialization_rechecks_after_concurrent_disposal(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = _bootstrap(client, f"li-s11-race-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S11-RACE")
    _seed_graph_records(matter_id)
    original_build_graph_specs = graph_service._build_graph_specs
    disposal_interposed = False

    def build_graph_then_dispose(session, matter):
        nonlocal disposal_interposed
        graph = original_build_graph_specs(session, matter)
        if not disposal_interposed:
            _dispose_matter(matter_id)
            disposal_interposed = True
        return graph

    monkeypatch.setattr(
        graph_service,
        "_build_graph_specs",
        build_graph_then_dispose,
    )

    response = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )

    assert disposal_interposed is True
    assert response.status_code == 409, response.text
    with get_session_factory()() as session:
        assert session.scalar(
            select(LegalKnowledgeGraphRun).where(
                LegalKnowledgeGraphRun.matter_id == matter_id
            )
        ) is None
        assert session.scalar(
            select(LegalKnowledgeGraphNode).where(
                LegalKnowledgeGraphNode.matter_id == matter_id
            )
        ) is None
        assert session.scalar(
            select(LegalKnowledgeGraphEdge).where(
                LegalKnowledgeGraphEdge.matter_id == matter_id
            )
        ) is None


def test_legal_knowledge_graph_materialization_is_idempotent(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s11-idem-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S11-IDEM")
    _seed_graph_records(matter_id)

    first = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )
    second = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_payload = first.json()
    second_payload = second.json()
    assert second_payload["run_id"] == first_payload["run_id"]
    assert second_payload["summary"]["node_count"] == first_payload["summary"]["node_count"]
    assert second_payload["summary"]["edge_count"] == first_payload["summary"]["edge_count"]
    factory = get_session_factory()
    with factory() as session:
        assert (
            len(
                list(
                    session.scalars(
                        select(LegalKnowledgeGraphRun).where(
                            LegalKnowledgeGraphRun.matter_id == matter_id
                        )
                    )
                )
            )
            == 1
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(LegalKnowledgeGraphNode).where(
                            LegalKnowledgeGraphNode.matter_id == matter_id
                        )
                    )
                )
            )
            == second_payload["summary"]["node_count"]
        )


def test_legal_knowledge_graph_bounds_all_source_snippets_before_response(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s11-bounds-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S11-BOUNDS")
    _seed_graph_records(matter_id)
    long_values = {
        "PROCEEDING": _long_quote("PROCEEDING"),
        "AFFIDAVIT-STATEMENT": _long_quote("AFFIDAVIT-STATEMENT"),
        "AFFIDAVIT-QUESTION": _long_quote("AFFIDAVIT-QUESTION"),
        "MOCK-QUESTION": _long_quote("MOCK-QUESTION"),
        "MOCK-RESPONSE": _long_quote("MOCK-RESPONSE"),
        "PREDICTIVE": _long_quote("PREDICTIVE"),
    }

    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        proceeding_signal = session.scalar(
            select(MatterProceedingSignal).where(
                MatterProceedingSignal.matter_id == matter_id
            )
        )
        affidavit_statement = session.scalar(
            select(AffidavitStatement).where(AffidavitStatement.matter_id == matter_id)
        )
        affidavit_question = session.scalar(
            select(AffidavitQuestion).where(AffidavitQuestion.matter_id == matter_id)
        )
        mock_question = session.scalar(
            select(MockHearingQuestion).where(MockHearingQuestion.matter_id == matter_id)
        )
        mock_response = session.scalar(
            select(MockHearingResponse).where(MockHearingResponse.matter_id == matter_id)
        )
        predictive_evidence = session.scalar(
            select(PredictiveSignalEvidence).where(
                PredictiveSignalEvidence.matter_id == matter_id
            )
        )
        assert proceeding_signal is not None
        assert affidavit_statement is not None
        assert affidavit_question is not None
        assert mock_question is not None
        assert mock_response is not None
        assert predictive_evidence is not None
        proceeding_signal.source_snippet = long_values["PROCEEDING"]
        affidavit_statement.source_quote = long_values["AFFIDAVIT-STATEMENT"]
        affidavit_question.source_quote = long_values["AFFIDAVIT-QUESTION"]
        mock_question.source_quote = long_values["MOCK-QUESTION"]
        mock_response.source_quote = long_values["MOCK-RESPONSE"]
        predictive_evidence.excerpt = long_values["PREDICTIVE"]
        session.commit()

    response = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    def exposed_quotes(data: dict[str, object]) -> list[str]:
        return [
            str(item["source_quote"])
            for collection in ("nodes", "edges")
            for item in data[collection]  # type: ignore[index]
            if item.get("source_quote")  # type: ignore[union-attr]
        ]

    quotes = exposed_quotes(payload)
    for label in long_values:
        matching = [quote for quote in quotes if label in quote]
        assert matching, f"Expected bounded quote for {label}"
        assert all(len(quote) <= SOURCE_SNIPPET_LIMIT for quote in matching)
        assert all(quote.endswith("...") for quote in matching)
        assert all(f"TAIL-{label}" not in quote for quote in matching)
        assert all("\x00" not in quote for quote in matching)

    persisted_node_marker = "PERSISTED-NODE"
    persisted_edge_marker = "PERSISTED-EDGE"
    factory = get_session_factory()
    with factory() as session:
        node = session.scalar(
            select(LegalKnowledgeGraphNode).where(
                LegalKnowledgeGraphNode.matter_id == matter_id,
                LegalKnowledgeGraphNode.source_quote.is_not(None),
            )
        )
        edge = session.scalar(
            select(LegalKnowledgeGraphEdge).where(
                LegalKnowledgeGraphEdge.matter_id == matter_id,
                LegalKnowledgeGraphEdge.source_quote.is_not(None),
            )
        )
        assert node is not None
        assert edge is not None
        node.source_quote = _long_quote(persisted_node_marker)
        edge.source_quote = _long_quote(persisted_edge_marker)
        session.commit()

    get_response = client.get(
        f"/api/matters/{matter_id}/legal-knowledge-graph",
        headers=_auth(token),
    )
    assert get_response.status_code == 200, get_response.text
    persisted_quotes = exposed_quotes(get_response.json())
    for label in (persisted_node_marker, persisted_edge_marker):
        matching = [quote for quote in persisted_quotes if label in quote]
        assert matching, f"Expected serialized bounded quote for {label}"
        assert all(len(quote) <= SOURCE_SNIPPET_LIMIT for quote in matching)
        assert all(quote.endswith("...") for quote in matching)
        assert all(f"TAIL-{label}" not in quote for quote in matching)
        assert all("\x00" not in quote for quote in matching)


def test_summary_only_records_are_not_materialized(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s11-summary-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S11-SUMMARY")
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        order = MatterCourtOrder(
            matter_id=matter.id,
            order_date=date(2026, 5, 12),
            title="Summary-only order",
            summary="Generated summary: reply affidavit due.",
            order_text=None,
            source="manual-test",
            source_reference="fixture:summary-only",
        )
        session.add(order)
        session.flush()
        session.add(
            MatterProceedingSignal(
                company_id=matter.company_id,
                matter_id=matter.id,
                court_order_id=order.id,
                signal_type="reply_affidavit_deadline",
                signal_text="Reply affidavit due.",
                confidence_label="high",
                source_snippet="Reply affidavit due.",
                review_status="review_required",
                extraction_method="deterministic",
                parser_version="caseops-proceeding-deterministic-v1",
                source_hash=uuid4().hex + uuid4().hex,
                dedupe_key=uuid4().hex,
            )
        )
        session.commit()

    response = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]["status"] == "no_source_records"
    assert payload["summary"]["source_record_count"] == 0
    assert {node["node_type"] for node in payload["nodes"]} == {"matter"}


def test_legal_knowledge_graph_access_denials(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s11-access-{uuid4().hex[:6]}")
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, owner_token, "LI-S11-ACCESS")
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email=f"li-s11-member-{uuid4().hex[:6]}@example.in",
    )

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    assert (
        client.get(
            f"/api/matters/{matter_id}/legal-knowledge-graph",
            headers=_auth(member_token),
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
            headers=_auth(member_token),
        ).status_code
        == 404
    )

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    _restricted_member_id, restricted_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email=f"li-s11-restricted-{uuid4().hex[:6]}@example.in",
    )
    assert (
        client.get(
            f"/api/matters/{matter_id}/legal-knowledge-graph",
            headers=_auth(restricted_token),
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
            headers=_auth(restricted_token),
        ).status_code
        == 404
    )

    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        team = Team(
            id=str(uuid4()),
            company_id=company_id,
            name="Graph Scoped Team",
            slug=f"graph-scoped-{uuid4().hex[:8]}",
        )
        session.add(team)
        session.flush()
        matter.restricted_access = False
        matter.team_id = team.id
        company = matter.company
        company.team_scoping_enabled = True
        session.commit()
    _team_member_id, team_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email=f"li-s11-team-{uuid4().hex[:6]}@example.in",
    )
    assert (
        client.get(
            f"/api/matters/{matter_id}/legal-knowledge-graph",
            headers=_auth(team_token),
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
            headers=_auth(team_token),
        ).status_code
        == 404
    )

    other = _bootstrap(client, f"li-s11-other-{uuid4().hex[:6]}")
    assert (
        client.get(
            f"/api/matters/{matter_id}/legal-knowledge-graph",
            headers=_auth(str(other["access_token"])),
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
            headers=_auth(str(other["access_token"])),
        ).status_code
        == 404
    )


def test_legal_knowledge_graph_closed_contracts_fail_closed(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s11-closed-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S11-CLOSED")

    response = client.post(
        f"/api/matters/{matter_id}/legal-knowledge-graph/materialize",
        headers=_auth(token),
    )
    assert response.status_code == 200, response.text
    run_id = str(response.json()["run_id"])

    with pytest.raises(ValidationError):
        LegalKnowledgeGraphNodeRecord.model_validate(
            {
                "id": "bad-node",
                "node_key": "bad",
                "node_type": "unknown_node",
                "label": "Bad",
                "source_type": "matter",
                "source_id": matter_id,
                "limitation_note": "bad",
                "created_at": "2026-05-12T00:00:00Z",
            }
        )

    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        session.add(
            LegalKnowledgeGraphNode(
                run_id=run_id,
                company_id=matter.company_id,
                matter_id=matter.id,
                node_key="bad-node",
                node_type="unknown_node",
                label="Bad node",
                source_type="matter",
                source_id=matter.id,
                limitation_note="Bad node should fail.",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        root = session.scalar(
            select(LegalKnowledgeGraphNode).where(
                LegalKnowledgeGraphNode.run_id == run_id,
                LegalKnowledgeGraphNode.node_type == "matter",
            )
        )
        assert root is not None
        session.add(
            LegalKnowledgeGraphEdge(
                run_id=run_id,
                company_id=matter.company_id,
                matter_id=matter.id,
                from_node_id=root.id,
                to_node_id=root.id,
                edge_type="unknown_edge",
                label="Bad edge",
                source_type="matter",
                source_id=matter.id,
                limitation_note="Bad edge should fail.",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
