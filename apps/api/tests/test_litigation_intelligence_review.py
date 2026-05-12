from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from caseops_api.db.models import (
    AffidavitIntelligenceRun,
    AffidavitQuestion,
    AffidavitStatement,
    AuditEvent,
    Company,
    DocumentProcessingStatus,
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
from caseops_api.schemas.litigation_intelligence import (
    LitigationIntelligenceReviewItem,
    LitigationIntelligenceReviewSource,
)


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
            "title": f"Litigation Intelligence Review {code}",
            "matter_code": code,
            "client_name": "Acme Industries",
            "opposing_party": "Beta Projects",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "court_name": "Delhi High Court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _invite_member(
    client: TestClient,
    *,
    owner_token: str,
    company_slug: str,
    email: str,
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": "LI Review Member",
            "email": email,
            "role": "member",
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


def _seed_review_records(matter_id: str) -> None:
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        order = MatterCourtOrder(
            matter_id=matter.id,
            order_date=date(2026, 5, 11),
            title="Daily order sheet",
            summary="Raw order imported from official source.",
            order_text=(
                "Matter listed on 20.05.2026. Respondent shall file reply within "
                "two weeks from the date of this order."
            ),
            source="manual-test",
            source_reference="fixture:order:li-s6",
            bench_name="Justice Source",
            order_kind="daily_order",
        )
        session.add(order)
        session.flush()
        proceeding_signal = MatterProceedingSignal(
            company_id=matter.company_id,
            matter_id=matter.id,
            court_order_id=order.id,
            signal_type="reply_affidavit_deadline",
            signal_text="Respondent shall file reply within two weeks.",
            action_required="File reply affidavit",
            due_on=date(2026, 5, 25),
            confidence_label="high",
            source_snippet="file reply within two weeks from the date of this order",
            review_status="auto_promoted",
            extraction_method="deterministic",
            parser_version="caseops-proceeding-deterministic-v1",
            source_hash=uuid4().hex + uuid4().hex,
            dedupe_key=uuid4().hex,
        )
        session.add(proceeding_signal)

        attachment = MatterAttachment(
            matter_id=matter.id,
            original_filename="chief-affidavit.txt",
            storage_key=f"test/li-s6/{uuid4().hex}.txt",
            content_type="text/plain",
            size_bytes=120,
            sha256_hex=(uuid4().hex + uuid4().hex)[:64],
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=120,
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
            source_char_count=120,
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
        question = AffidavitQuestion(
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
        session.add(question)
        session.flush()

        mock_session = MockHearingSession(
            company_id=matter.company_id,
            matter_id=matter.id,
            source_affidavit_run_id=affidavit_run.id,
            mode="client_preparation",
            status="active",
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
                    "average_response_seconds": 30,
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
            source_affidavit_question_id=question.id,
            source_affidavit_statement_id=statement.id,
            source_attachment_id=attachment.id,
            source_chunk_id=chunk.id,
            source_chunk_index=0,
            turn_index=0,
            category="document_support",
            question_text=question.question_text,
            reason=question.reason,
            source_quote=question.source_quote,
            difficulty_label="medium",
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
                source_affidavit_question_id=question.id,
                response_text="It is supported by another oral assurance.",
                response_word_count=8,
                elapsed_seconds=30,
                answered_question=True,
                consistency_with_affidavit=True,
                unsupported_assertion_added=True,
                missing_document_reference=True,
                contradiction_with_source=False,
                response_completeness="medium",
                confidence_label="low",
                feedback_text="Response adds facts not visible in the source quote.",
                evaluation_json="{}",
                source_quote=question.source_quote,
                review_required=True,
                review_status="review_required",
            )
        )

        predictive_run = PredictiveSignalRun(
            company_id=matter.company_id,
            matter_id=matter.id,
            status="completed",
            mode="predictive",
            sample_size=3,
            evidence_quality="thin",
            disclaimer="Predictive intelligence is decision support, not legal advice.",
            limitation_note="The indexed source sample remains thin.",
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
            sample_size=3,
            confidence_label="low",
            confidence_band_low=0.1,
            confidence_band_high=0.6,
            limitation_note="Low sample size requires review.",
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
                source_type="matter_document",
                source_id=attachment.id,
                title=attachment.original_filename,
                source_reference="chunk 0",
                excerpt=question.source_quote,
            )
        )
        session.commit()


def _audit_actions(company_id: str) -> list[str]:
    factory = get_session_factory()
    with factory() as session:
        return [
            event.action
            for event in session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc())
            )
        ]


def test_litigation_intelligence_review_aggregates_source_linked_items_and_audits(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s6-main-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S6-MAIN")
    _seed_review_records(matter_id)

    response = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    item_types = {item["item_type"] for item in body["items"]}
    assert {
        "proceeding_signal",
        "affidavit_statement",
        "affidavit_question",
        "mock_hearing_session",
        "mock_hearing_response",
        "predictive_signal",
        "bench_context",
    }.issubset(item_types)
    assert body["summary"]["total_items"] == len(body["items"])
    assert body["summary"]["source_linked_count"] == len(body["items"])
    assert body["summary"]["review_required_count"] >= 5
    assert "not legal advice" in body["disclaimer"]
    assert all(item["source"]["source_id"] for item in body["items"])
    assert all(item["source"]["snippet"] for item in body["items"])
    rendered = json.dumps(body).lower()
    for forbidden in (
        "guaranteed",
        "will win",
        "judge reputation",
        "judge likes",
        "judge dislikes",
        "emotional instability",
        "psychological diagnosis",
        "biometric",
        "voice stress",
    ):
        assert forbidden not in rendered

    actions = _audit_actions(str(boot["company"]["id"]))
    assert "litigation_intelligence_review.viewed" in actions


def test_litigation_intelligence_review_enforces_matter_visibility(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, f"li-s6-acl-a-{uuid4().hex[:6]}")
    owner_token = str(boot_a["access_token"])
    company_slug = str(boot_a["company"]["slug"])
    company_id = str(boot_a["company"]["id"])
    matter_id = _create_matter(client, owner_token, "LI-S6-ACL")
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email=f"li-s6-member-{uuid4().hex[:6]}@example.in",
    )
    boot_b = _bootstrap(client, f"li-s6-acl-b-{uuid4().hex[:6]}")
    tenant_b_token = str(boot_b["access_token"])

    cross_tenant = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(tenant_b_token),
    )
    assert cross_tenant.status_code == 404, cross_tenant.text

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    hidden = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(member_token),
    )
    assert hidden.status_code == 404, hidden.text

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=_auth(owner_token),
        json={"membership_id": member_id, "reason": "LI-S6 review"},
    )
    assert grant.status_code == 200, grant.text
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    walled = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(member_token),
    )
    assert walled.status_code == 404, walled.text

    team_matter_id = _create_matter(client, owner_token, "LI-S6-TEAM")
    with get_session_factory()() as session:
        team = Team(
            id=str(uuid4()),
            company_id=company_id,
            name="LI-S6 Team",
            slug=f"li-s6-team-{uuid4().hex[:6]}",
        )
        session.add(team)
        session.flush()
        matter = session.get(Matter, team_matter_id)
        company = session.get(Company, company_id)
        assert matter is not None
        assert company is not None
        matter.team_id = team.id
        company.team_scoping_enabled = True
        session.commit()
    team_hidden = client.get(
        f"/api/matters/{team_matter_id}/litigation-intelligence/review",
        headers=_auth(member_token),
    )
    assert team_hidden.status_code == 404, team_hidden.text


def test_litigation_intelligence_review_schema_rejects_unknown_item_or_source_type() -> None:
    source = LitigationIntelligenceReviewSource(
        source_type="matter_document",
        source_id="att-1",
        label="Affidavit",
        snippet="source quote",
    )
    with pytest.raises(ValidationError):
        LitigationIntelligenceReviewItem(
            id="unsafe-1",
            item_type="voice_emotion_score",
            title="Unsafe",
            description="Unsafe item",
            status="review_required",
            priority="high",
            limitation_note="Unsafe",
            review_reason="Unsafe",
            source=source,
            created_at="2026-05-12T00:00:00Z",
        )
    with pytest.raises(ValidationError):
        LitigationIntelligenceReviewSource(
            source_type="manual_upload",
            source_id="manual-1",
            label="Manual",
            snippet="source quote",
        )
