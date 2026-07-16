from __future__ import annotations

import re
from uuid import uuid4

from fastapi.testclient import TestClient
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
    MockHearingQuestion,
    MockHearingResponse,
    MockHearingSession,
    Team,
)
from caseops_api.db.session import get_session_factory


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
            "title": f"Mock Hearing {code}",
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
            "full_name": "Mock Hearing Member",
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


def _seed_affidavit_question(
    matter_id: str,
    *,
    category: str = "document_support",
    source_quote: str = (
        "I state that respondent paid Rs. 10,000 on 01.05.2026 under Invoice A."
    ),
    question_text: str = (
        "Which invoice, receipt, or bank record supports this payment statement?"
    ),
) -> tuple[str, str]:
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        attachment = MatterAttachment(
            id=str(uuid4()),
            matter_id=matter_id,
            original_filename="chief-affidavit.txt",
            storage_key=f"test/mock-hearing/{uuid4().hex}.txt",
            content_type="text/plain",
            size_bytes=len(source_quote),
            sha256_hex=(uuid4().hex + uuid4().hex)[:64],
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=len(source_quote),
            extracted_text=source_quote,
            document_type="chief_affidavit",
            lifecycle_stage="pleadings",
        )
        session.add(attachment)
        session.flush()
        chunk = MatterAttachmentChunk(
            attachment_id=attachment.id,
            chunk_index=0,
            content=source_quote,
            token_count=len(source_quote.split()),
        )
        session.add(chunk)
        session.flush()
        run = AffidavitIntelligenceRun(
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            status="completed",
            extraction_method="deterministic",
            parser_version="caseops-affidavit-deterministic-v1",
            source_hash=uuid4().hex + uuid4().hex,
            source_char_count=len(source_quote),
            missing_data_json="[]",
            disclaimer="source-backed affidavit intelligence",
        )
        session.add(run)
        session.flush()
        statement = AffidavitStatement(
            run_id=run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            source_chunk_id=chunk.id,
            source_chunk_index=0,
            statement_type="monetary_figure",
            statement_text=source_quote,
            source_quote=source_quote,
            confidence_label="medium",
            review_status="review_required",
            dedupe_key=uuid4().hex,
        )
        session.add(statement)
        session.flush()
        question = AffidavitQuestion(
            run_id=run.id,
            company_id=matter.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            statement_id=statement.id,
            source_chunk_id=chunk.id,
            source_chunk_index=0,
            category=category,
            question_text=question_text,
            reason="The source affidavit requires document support.",
            source_quote=source_quote,
            confidence_label="low",
            review_required=True,
            review_status="review_required",
            dedupe_key=uuid4().hex,
        )
        session.add(question)
        session.commit()
        return run.id, question.id


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


def _dispose_matter(matter_id: str) -> None:
    with get_session_factory()() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.status = "disposed"
        matter.is_active = False
        session.commit()


def test_cannot_start_mock_hearing_without_affidavit_questions(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s3-empty-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S3-EMPTY")

    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={"mode": "client_preparation"},
    )

    assert response.status_code == 409, response.text
    assert "affidavit intelligence" in response.text.lower()


def test_disposed_matter_rejects_mock_hearing_start_but_keeps_list_readable(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s3-disposed-start-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "LI-S3-DISPOSED-START")
    _seed_affidavit_question(matter_id)
    _dispose_matter(matter_id)

    rejected = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={"mode": "client_preparation"},
    )
    assert rejected.status_code == 409, rejected.text
    assert "disposed" in rejected.text.lower()

    listed = client.get(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["sessions"] == []
    with get_session_factory()() as session:
        assert (
            session.scalar(
                select(MockHearingSession).where(
                    MockHearingSession.matter_id == matter_id
                )
            )
            is None
        )
    assert "mock_hearing.created" not in _audit_actions(company_id)


def test_mock_hearing_session_uses_source_backed_affidavit_questions(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s3-start-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S3-START")
    run_id, question_id = _seed_affidavit_question(matter_id)

    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={"participant_label": "Witness A", "max_questions": 4},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source_affidavit_run_id"] == run_id
    assert payload["participant_label"] == "Witness A"
    assert payload["status"] == "active"
    assert payload["questions"][0]["source_affidavit_question_id"] == question_id
    assert payload["questions"][0]["source_quote"]
    assert payload["scorecard"]["total_questions"] == 1

    list_response = client.get(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["latest_session"]["id"] == payload["id"]


def test_mock_hearing_response_evaluation_is_source_linked_and_flags_unsupported_fact(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s3-response-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S3-RESP")
    _seed_affidavit_question(matter_id)
    created = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={},
    )
    assert created.status_code == 200, created.text
    session_payload = created.json()
    session_id = session_payload["id"]
    question = session_payload["questions"][0]

    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/responses",
        headers=_auth(token),
        json={
            "question_id": question["id"],
            "response_text": (
                "The payment is supported by Invoice A, and delivery occurred "
                "at the Pune warehouse."
            ),
            "elapsed_seconds": 42,
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    answer = updated["questions"][0]["responses"][0]
    assert answer["source_affidavit_question_id"] == question["source_affidavit_question_id"]
    assert answer["source_affidavit_statement_id"] == question["source_affidavit_statement_id"]
    assert answer["source_quote"] == question["source_quote"]
    assert answer["unsupported_assertion_added"] is True
    assert answer["review_required"] is True
    assert "source quote" in answer["feedback_text"]
    assert updated["scorecard"]["unsupported_assertion_count"] == 1
    assert updated["scorecard"]["average_response_seconds"] == 42
    actions = _audit_actions(str(boot["company"]["id"]))
    assert "mock_hearing.response_recorded" in actions


def test_low_confidence_response_remains_review_required(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s3-low-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S3-LOW")
    _seed_affidavit_question(matter_id)
    created = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]

    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/responses",
        headers=_auth(token),
        json={"response_text": "No."},
    )

    assert response.status_code == 200, response.text
    answer = response.json()["questions"][0]["responses"][0]
    assert answer["confidence_label"] == "low"
    assert answer["review_required"] is True
    assert answer["answered_question"] is False


def test_complete_mock_hearing_is_idempotent_and_audited(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s3-complete-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S3-COMPLETE")
    _seed_affidavit_question(matter_id)
    created = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]

    first = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/complete",
        headers=_auth(token),
    )
    second = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/complete",
        headers=_auth(token),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "completed"
    assert second.json()["status"] == "completed"
    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(MockHearingSession).where(MockHearingSession.id == session_id))
        assert session.scalar(select(MockHearingResponse)) is None
    actions = _audit_actions(str(boot["company"]["id"]))
    assert "mock_hearing.created" in actions
    assert actions.count("mock_hearing.completed") == 1


def test_disposal_rejects_response_and_completion_without_mutating_session(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s3-disposed-session-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    company_id = str(boot["company"]["id"])
    matter_id = _create_matter(client, token, "LI-S3-DISPOSED-SESSION")
    _seed_affidavit_question(matter_id)
    created = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]
    question_id = created.json()["questions"][0]["id"]
    _dispose_matter(matter_id)

    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/responses",
        headers=_auth(token),
        json={
            "question_id": question_id,
            "response_text": "Invoice A supports the payment.",
        },
    )
    completed = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/complete",
        headers=_auth(token),
    )
    assert response.status_code == 409, response.text
    assert completed.status_code == 409, completed.text
    assert "disposed" in response.text.lower()
    assert "disposed" in completed.text.lower()

    # The historical session remains readable but unchanged.
    read = client.get(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}",
        headers=_auth(token),
    )
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "active"
    assert read.json()["questions"][0]["status"] == "pending"
    assert read.json()["questions"][0]["responses"] == []

    with get_session_factory()() as session:
        mock_session = session.get(MockHearingSession, session_id)
        question = session.get(MockHearingQuestion, question_id)
        assert mock_session is not None
        assert question is not None
        assert mock_session.status == "active"
        assert mock_session.completed_at is None
        assert question.status == "pending"
        assert (
            session.scalar(
                select(MockHearingResponse).where(
                    MockHearingResponse.matter_id == matter_id
                )
            )
            is None
        )
    actions = _audit_actions(company_id)
    assert "mock_hearing.response_recorded" not in actions
    assert "mock_hearing.completed" not in actions


def test_mock_hearing_routes_enforce_cross_tenant_restricted_team_and_ethical_wall(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, f"li-s3-acl-a-{uuid4().hex[:6]}")
    owner_token = str(boot_a["access_token"])
    company_slug = str(boot_a["company"]["slug"])
    matter_id = _create_matter(client, owner_token, "LI-S3-ACL")
    _seed_affidavit_question(matter_id)

    boot_b = _bootstrap(client, f"li-s3-acl-b-{uuid4().hex[:6]}")
    token_b = str(boot_b["access_token"])
    hidden = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token_b),
        json={},
    )
    assert hidden.status_code == 404, hidden.text

    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="mock-li-s3@example.in",
    )
    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    denied_get = client.get(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(member_token),
    )
    denied_post = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(member_token),
        json={},
    )
    assert denied_get.status_code == 404, denied_get.text
    assert denied_post.status_code == 404, denied_post.text

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=_auth(owner_token),
        json={"membership_id": member_id, "reason": "prep"},
    )
    assert grant.status_code == 200, grant.text
    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "conflict"},
    )
    assert wall.status_code == 200, wall.text
    walled = client.get(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(member_token),
    )
    assert walled.status_code == 404, walled.text

    matter_team = _create_matter(client, owner_token, "LI-S3-TEAM")
    _seed_affidavit_question(matter_team)
    _, blocked_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="mock-li-s3-team@example.in",
    )
    factory = get_session_factory()
    with factory() as session:
        team = Team(
            id=str(uuid4()),
            company_id=str(boot_a["company"]["id"]),
            name="Mock Hearing Team",
            slug=f"mock-hearing-{uuid4().hex[:6]}",
        )
        session.add(team)
        session.flush()
        matter = session.get(Matter, matter_team)
        assert matter is not None
        matter.team_id = team.id
        company = session.get(Company, str(boot_a["company"]["id"]))
        assert company is not None
        company.team_scoping_enabled = True
        session.add_all([matter, company])
        session.commit()
    blocked = client.post(
        f"/api/matters/{matter_team}/mock-hearings",
        headers=_auth(blocked_token),
        json={},
    )
    assert blocked.status_code == 404, blocked.text


def test_mock_hearing_output_has_no_emotion_or_psychological_labels(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s3-copy-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S3-COPY")
    _seed_affidavit_question(matter_id)

    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={},
    )

    assert response.status_code == 200, response.text
    lowered = response.text.lower()
    for banned in ("emotion", "psychological", "mental state", "biometric", "voice"):
        assert re.search(rf"\b{re.escape(banned)}\b", lowered) is None
