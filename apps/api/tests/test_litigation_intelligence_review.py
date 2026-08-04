from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from caseops_api.db.models import (
    AffidavitIntelligenceRun,
    AffidavitQuestion,
    AffidavitStatement,
    AuditEvent,
    Company,
    CompanyMembership,
    DocumentProcessingStatus,
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
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.litigation_intelligence import (
    LitigationIntelligenceReviewItem,
    LitigationIntelligenceReviewMutationRequest,
    LitigationIntelligenceReviewMutationResponse,
    LitigationIntelligenceReviewSource,
)
from caseops_api.services.litigation_intelligence_review import (
    mutate_litigation_intelligence_review_item,
)
from caseops_api.services.session_context import SessionContext


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
            "status": "intake",
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
    role: str = "member",
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": "LI Review Member",
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


def _audit_events(company_id: str) -> list[AuditEvent]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.company_id == company_id)
                .order_by(AuditEvent.created_at.asc())
            )
        )


def _review_actions(matter_id: str) -> list[LitigationIntelligenceReviewAction]:
    factory = get_session_factory()
    with factory() as session:
        return list(
            session.scalars(
                select(LitigationIntelligenceReviewAction)
                .where(LitigationIntelligenceReviewAction.matter_id == matter_id)
                .order_by(LitigationIntelligenceReviewAction.created_at.asc())
            )
        )


def _dispose_matter(matter_id: str) -> None:
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.status = "disposed"
        matter.is_active = False
        session.commit()


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
    matter_sources = [
        item["source"]
        for item in body["items"]
        if item["source"]["source_type"] == "matter_document"
    ]
    assert matter_sources
    assert all(
        source["source_action"]["target_type"] == "matter_attachment"
        and source["source_action"]["target_id"] == source["source_id"]
        and "/source-actions/targets/matter_attachment/"
        in source["source_action"]["open_url"]
        for source in matter_sources
    )
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


def test_litigation_intelligence_review_mutation_actions_are_audited_and_idempotent(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s9-actions-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "LI-S9-ACTIONS")
    _seed_review_records(matter_id)

    review = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )
    assert review.status_code == 200, review.text
    items = review.json()["items"]
    by_type = {item["item_type"]: item for item in items}

    mark_reviewed = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": by_type["proceeding_signal"]["id"],
            "item_type": "proceeding_signal",
            "action": "mark_reviewed",
            "note": "Confirmed against the source order.",
        },
    )
    assert mark_reviewed.status_code == 200, mark_reviewed.text
    mark_body = mark_reviewed.json()
    assert mark_body["status_before"] == "auto_promoted"
    assert mark_body["status_after"] == "reviewed"
    assert mark_body["applied"] is True

    repeated = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": by_type["proceeding_signal"]["id"],
            "item_type": "proceeding_signal",
            "action": "mark_reviewed",
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status_before"] == "reviewed"
    assert repeated.json()["status_after"] == "reviewed"
    assert repeated.json()["applied"] is False
    assert repeated.json()["no_op_reason"] == "repeat_terminal_action"

    note = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": by_type["affidavit_question"]["id"],
            "item_type": "affidavit_question",
            "action": "edit_note",
            "note": "Ask the witness to identify Invoice A.",
        },
    )
    assert note.status_code == 200, note.text
    assert note.json()["status_after"] == "review_required"

    noted_review = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )
    assert noted_review.status_code == 200, noted_review.text
    noted_question = next(
        item
        for item in noted_review.json()["items"]
        if item["id"] == by_type["affidavit_question"]["id"]
    )
    assert noted_question["review_note"] == "Ask the witness to identify Invoice A."
    assert noted_question["last_review_action"] == "edit_note"

    accept = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": by_type["affidavit_question"]["id"],
            "item_type": "affidavit_question",
            "action": "accept",
            "note": "Question approved for prep.",
        },
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status_after"] == "accepted"

    reject_after_accept = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": by_type["affidavit_question"]["id"],
            "item_type": "affidavit_question",
            "action": "reject",
        },
    )
    assert reject_after_accept.status_code == 409, reject_after_accept.text
    assert "conflict_terminal_state" in reject_after_accept.json()["detail"]

    reject = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": by_type["predictive_signal"]["id"],
            "item_type": "predictive_signal",
            "action": "reject",
            "note": "Sample is too thin for this matter.",
        },
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["source_type"] == "predictive_signal_item"
    assert reject.json()["status_after"] == "rejected"

    accept_after_reject = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": by_type["predictive_signal"]["id"],
            "item_type": "predictive_signal",
            "action": "accept",
        },
    )
    assert accept_after_reject.status_code == 409, accept_after_reject.text
    assert "conflict_terminal_state" in accept_after_reject.json()["detail"]

    final_review = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )
    assert final_review.status_code == 200, final_review.text
    final_ids = {item["id"] for item in final_review.json()["items"]}
    assert by_type["proceeding_signal"]["id"] not in final_ids
    assert by_type["affidavit_question"]["id"] not in final_ids
    assert by_type["predictive_signal"]["id"] not in final_ids

    action_rows = _review_actions(matter_id)
    assert [row.action for row in action_rows] == [
        "mark_reviewed",
        "mark_reviewed",
        "edit_note",
        "accept",
        "reject",
    ]
    events = [
        event
        for event in _audit_events(company_id)
        if event.action == "litigation_intelligence_review.item_mutated"
    ]
    assert len(events) == 7
    metadata_rows = [json.loads(event.metadata_json or "{}") for event in events]
    for event, metadata in zip(events, metadata_rows, strict=True):
        assert event.company_id == company_id
        assert event.matter_id == matter_id
        assert event.actor_membership_id is not None
        assert event.target_type == metadata["source_type"]
        assert event.target_id == metadata["source_id"]
        assert "applied" in metadata
        serialized_metadata = json.dumps(metadata).lower()
        assert "source_payload" not in serialized_metadata
        assert "source_snippet" not in serialized_metadata

    metadata = next(
        row
        for row in metadata_rows
        if row["item_id"] == by_type["proceeding_signal"]["id"]
        and row["action"] == "mark_reviewed"
        and row["applied"] is True
    )
    assert metadata["before"]["status"] == "auto_promoted"
    assert metadata["after"]["status"] == "reviewed"
    assert metadata["after"]["note"] == "Confirmed against the source order."
    assert metadata["idempotent"] is False
    repeat_metadata = next(
        row
        for row in metadata_rows
        if row["item_id"] == by_type["proceeding_signal"]["id"]
        and row["action"] == "mark_reviewed"
        and row["applied"] is False
    )
    assert repeat_metadata["no_op_reason"] == "repeat_terminal_action"
    reject_conflict_metadata = next(
        row
        for row in metadata_rows
        if row["item_id"] == by_type["affidavit_question"]["id"]
        and row["action"] == "reject"
    )
    assert reject_conflict_metadata["before"]["status"] == "accepted"
    assert reject_conflict_metadata["after"]["status"] == "accepted"
    assert reject_conflict_metadata["applied"] is False
    assert reject_conflict_metadata["no_op_reason"] == "conflict_terminal_state"
    assert reject_conflict_metadata["conflict_reason"] == "conflict_terminal_state"
    accept_conflict_metadata = next(
        row
        for row in metadata_rows
        if row["item_id"] == by_type["predictive_signal"]["id"]
        and row["action"] == "accept"
    )
    assert accept_conflict_metadata["before"]["status"] == "rejected"
    assert accept_conflict_metadata["after"]["status"] == "rejected"
    assert accept_conflict_metadata["applied"] is False
    assert accept_conflict_metadata["no_op_reason"] == "conflict_terminal_state"
    assert accept_conflict_metadata["conflict_reason"] == "conflict_terminal_state"


def test_disposed_matter_keeps_review_readable_but_rejects_mutation_without_side_effects(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s9-disposed-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "LI-S9-DISPOSED")
    _seed_review_records(matter_id)

    before = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )
    assert before.status_code == 200, before.text
    item = next(
        row for row in before.json()["items"] if row["item_type"] == "affidavit_question"
    )
    _dispose_matter(matter_id)

    rejected = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": item["id"],
            "item_type": item["item_type"],
            "action": "accept",
            "note": "This must not be persisted after disposal.",
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert "disposed" in rejected.text.lower()

    # Disposal terminates operational work, not authorized historical reads.
    after = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )
    assert after.status_code == 200, after.text
    assert item["id"] in {row["id"] for row in after.json()["items"]}
    assert _review_actions(matter_id) == []
    assert not [
        event
        for event in _audit_events(company_id)
        if event.action == "litigation_intelligence_review.item_mutated"
    ]


def test_review_mutation_refreshes_stale_matter_before_any_child_write(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s9-stale-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "LI-S9-STALE")
    _seed_review_records(matter_id)
    review = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )
    assert review.status_code == 200, review.text
    item = next(
        row for row in review.json()["items"] if row["item_type"] == "affidavit_question"
    )

    factory = get_session_factory()
    with factory() as stale_session:
        stale_matter = stale_session.get(Matter, matter_id)
        company = stale_session.get(Company, company_id)
        membership = stale_session.scalar(
            select(CompanyMembership).where(CompanyMembership.company_id == company_id)
        )
        assert stale_matter is not None
        assert stale_matter.is_active is True
        assert company is not None
        assert membership is not None
        user = stale_session.get(User, membership.user_id)
        assert user is not None
        context = SessionContext(company=company, membership=membership, user=user)

        _dispose_matter(matter_id)

        with pytest.raises(HTTPException) as exc_info:
            mutate_litigation_intelligence_review_item(
                stale_session,
                context=context,
                matter_id=matter_id,
                payload=LitigationIntelligenceReviewMutationRequest(
                    item_id=item["id"],
                    item_type=item["item_type"],
                    action="accept",
                ),
            )
        assert exc_info.value.status_code == 409
        assert "disposed" in str(exc_info.value.detail).lower()
        assert stale_matter.status == "disposed"
        assert stale_matter.is_active is False

    assert _review_actions(matter_id) == []


def test_litigation_intelligence_review_mutation_rejects_unsafe_notes(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s9-note-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S9-NOTE")
    _seed_review_records(matter_id)

    review = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(token),
    )
    assert review.status_code == 200, review.text
    item = next(
        row for row in review.json()["items"] if row["item_type"] == "affidavit_question"
    )

    for note in (
        "Guaranteed outcome because this is a favorable judge.",
        "The witness will lose on this point.",
        "Record a loss probability for this issue.",
        "Add a win/loss view to the queue.",
        "This is based on judge reputation.",
    ):
        unsafe = client.post(
            f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
            headers=_auth(token),
            json={
                "item_id": item["id"],
                "item_type": item["item_type"],
                "action": "edit_note",
                "note": note,
            },
        )
        assert unsafe.status_code == 422, unsafe.text
        assert "unsupported prediction" in unsafe.json()["detail"]
    assert _review_actions(matter_id) == []


def test_litigation_intelligence_review_mutation_validates_closed_item_contract(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s9-contract-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S9-CONTRACT")
    _seed_review_records(matter_id)

    invalid_type = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": "voice-emotion-score:unsafe",
            "item_type": "voice_emotion_score",
            "action": "accept",
        },
    )
    assert invalid_type.status_code == 422, invalid_type.text

    mismatched_id = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(token),
        json={
            "item_id": "predictive-signal:wrong-prefix",
            "item_type": "affidavit_question",
            "action": "accept",
        },
    )
    assert mismatched_id.status_code == 400, mismatched_id.text


def test_litigation_intelligence_review_mutation_enforces_matter_visibility(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, f"li-s9-acl-a-{uuid4().hex[:6]}")
    owner_token = str(boot_a["access_token"])
    company_slug = str(boot_a["company"]["slug"])
    company_id = str(boot_a["company"]["id"])
    matter_id = _create_matter(client, owner_token, "LI-S9-ACL")
    _seed_review_records(matter_id)
    review = client.get(
        f"/api/matters/{matter_id}/litigation-intelligence/review",
        headers=_auth(owner_token),
    )
    assert review.status_code == 200, review.text
    item = review.json()["items"][0]

    _, partner_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email=f"li-s9-partner-{uuid4().hex[:6]}@example.in",
        role="partner",
    )
    boot_b = _bootstrap(client, f"li-s9-acl-b-{uuid4().hex[:6]}")
    tenant_b_token = str(boot_b["access_token"])

    payload = {
        "item_id": item["id"],
        "item_type": item["item_type"],
        "action": "mark_reviewed",
    }
    cross_tenant = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(tenant_b_token),
        json=payload,
    )
    assert cross_tenant.status_code == 404, cross_tenant.text

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    restricted_denied = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(partner_token),
        json=payload,
    )
    assert restricted_denied.status_code == 404, restricted_denied.text

    walled_member_id, walled_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email=f"li-s9-walled-{uuid4().hex[:6]}@example.in",
        role="partner",
    )
    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=_auth(owner_token),
        json={"membership_id": walled_member_id, "reason": "LI-S9 review"},
    )
    assert grant.status_code == 200, grant.text
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": walled_member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    walled_denied = client.post(
        f"/api/matters/{matter_id}/litigation-intelligence/review/actions",
        headers=_auth(walled_token),
        json=payload,
    )
    assert walled_denied.status_code == 404, walled_denied.text

    team_matter_id = _create_matter(client, owner_token, "LI-S9-TEAM")
    _seed_review_records(team_matter_id)
    team_review = client.get(
        f"/api/matters/{team_matter_id}/litigation-intelligence/review",
        headers=_auth(owner_token),
    )
    assert team_review.status_code == 200, team_review.text
    team_item = team_review.json()["items"][0]
    with get_session_factory()() as session:
        team = Team(
            id=str(uuid4()),
            company_id=company_id,
            name="LI-S9 Team",
            slug=f"li-s9-team-{uuid4().hex[:6]}",
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
    team_hidden = client.post(
        f"/api/matters/{team_matter_id}/litigation-intelligence/review/actions",
        headers=_auth(partner_token),
        json={
            "item_id": team_item["id"],
            "item_type": team_item["item_type"],
            "action": "mark_reviewed",
        },
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
    with pytest.raises(ValidationError):
        LitigationIntelligenceReviewMutationResponse(
            matter_id="matter-1",
            item_id="affidavit-question:q-1",
            item_type="affidavit_question",
            source_type="manual_upload",
            source_id="manual-1",
            action="accept",
            status_before="review_required",
            status_after="accepted",
            audit_event_id="audit-1",
            applied=True,
            updated_at="2026-05-12T00:00:00Z",
        )


def test_litigation_intelligence_review_action_db_constraints_fail_closed(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s9-db-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "LI-S9-DB")

    factory = get_session_factory()
    with factory() as session:
        session.add(
            LitigationIntelligenceReviewAction(
                company_id=company_id,
                matter_id=matter_id,
                item_type="voice_emotion_score",
                item_id="voice-emotion-score:unsafe",
                source_type="predictive_signal_item",
                source_id="source-1",
                action="accept",
                status_before="review_required",
                status_after="accepted",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
