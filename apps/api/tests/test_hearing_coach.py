from __future__ import annotations

import json
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
    ModelRun,
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
            "title": f"Hearing Coach {code}",
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
) -> tuple[str, str]:
    response = client.post(
        "/api/companies/current/users",
        headers=_auth(owner_token),
        json={
            "full_name": "Hearing Coach Member",
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


def _seed_affidavit_question(matter_id: str) -> None:
    source_quote = "I state that respondent paid Rs. 10,000 under Invoice A."
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        attachment = MatterAttachment(
            id=str(uuid4()),
            matter_id=matter.id,
            original_filename="chief-affidavit.txt",
            storage_key=f"test/hearing-coach/{uuid4().hex}.txt",
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
            category="document_support",
            question_text="Which invoice or bank record supports the payment statement?",
            reason="The source affidavit requires document support.",
            source_quote=source_quote,
            confidence_label="low",
            review_required=True,
            review_status="review_required",
            dedupe_key=uuid4().hex,
        )
        session.add(question)
        session.commit()


def _create_session_with_response(
    client: TestClient,
    *,
    token: str,
    matter_id: str,
    response_text: str = "Invoice A and the bank record support the payment statement.",
) -> tuple[str, str]:
    _seed_affidavit_question(matter_id)
    created = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={},
    )
    assert created.status_code == 200, created.text
    session_id = str(created.json()["id"])
    question_id = str(created.json()["questions"][0]["id"])
    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/responses",
        headers=_auth(token),
        json={
            "question_id": question_id,
            "response_text": response_text,
        },
    )
    assert response.status_code == 200, response.text
    return session_id, question_id


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


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(_all_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_all_keys(child))
        return keys
    return set()


def test_hearing_coach_blocks_without_acknowledgement(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s13-consent-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S13-CONSENT")
    session_id, _ = _create_session_with_response(client, token=token, matter_id=matter_id)

    status_response = client.get(
        f"/api/matters/{matter_id}/hearing-coach",
        headers=_auth(token),
    )
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["status"] == "consent_required"
    assert status_response.json()["consent_required"] is True

    blocked = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/coach",
        headers=_auth(token),
        json={"acknowledged": False},
    )

    assert blocked.status_code == 409, blocked.text
    assert "acknowledgement" in blocked.text.lower()


def test_hearing_coach_uses_typed_transcript_source_links_and_audits(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s13-report-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S13-REPORT")
    session_id, _ = _create_session_with_response(
        client,
        token=token,
        matter_id=matter_id,
        response_text="Invoice A supports it, with a new Pune warehouse detail.",
    )

    response = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/coach",
        headers=_auth(token),
        json={"acknowledged": True},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mock_hearing_session_id"] == session_id
    assert payload["consent_acknowledged"] is True
    assert payload["metrics"]["total_responses"] == 1
    assert payload["metrics"]["unsupported_assertion_count"] == 1
    item = payload["feedback_items"][0]
    assert item["response_id"]
    assert item["question_id"]
    assert item["source_affidavit_question_id"]
    assert item["source_affidavit_statement_id"]
    assert item["source_attachment_id"]
    assert "Invoice A supports it" in item["transcript_excerpt"]
    assert "respondent paid Rs. 10,000" in item["source_quote"]
    assert item["clarity_score"] >= 0
    assert item["completeness_score"] >= 0

    banned = (
        "audio",
        "voice",
        "emotion",
        "psychological",
        "biometric",
        "mental",
        "stress",
        "sentiment",
        "personality",
        "lie",
        "credibility",
        "honesty",
    )
    lowered = json.dumps(payload).lower()
    assert all(re.search(rf"\b{re.escape(term)}\b", lowered) is None for term in banned)
    assert all(term not in _all_keys(payload) for term in banned)

    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(ModelRun)) is None
    events = _audit_events(str(boot["company"]["id"]))
    actions = [event.action for event in events]
    assert "hearing_coach.generated" in actions
    generated = next(event for event in events if event.action == "hearing_coach.generated")
    metadata = generated.metadata_json or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    assert metadata["consent_acknowledged"] is True
    assert metadata["response_count"] == 1
    assert "source_quote" not in metadata
    assert "transcript_excerpt" not in metadata


def test_hearing_coach_rerun_is_deterministic_without_duplicate_state(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s13-idem-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S13-IDEM")
    session_id, _ = _create_session_with_response(client, token=token, matter_id=matter_id)

    first = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/coach",
        headers=_auth(token),
        json={"acknowledged": True},
    )
    second = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/coach",
        headers=_auth(token),
        json={"acknowledged": True},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["metrics"] == second_payload["metrics"]
    assert first_payload["feedback_items"] == second_payload["feedback_items"]
    events = _audit_events(str(boot["company"]["id"]))
    assert [event.action for event in events].count("hearing_coach.generated") == 2


def test_disposed_matter_rejects_hearing_coach_generation(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s13-disposed-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S13-DISPOSED")
    session_id, _ = _create_session_with_response(
        client,
        token=token,
        matter_id=matter_id,
    )
    factory = get_session_factory()
    with factory() as session:
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.status = "disposed"
        matter.is_active = False
        session.commit()

    generated = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/coach",
        headers=_auth(token),
        json={"acknowledged": True},
    )
    assert generated.status_code == 409, generated.text
    assert "disposed" in generated.text.lower()

    # Historical status remains readable, but no new generated audit survives.
    status_response = client.get(
        f"/api/matters/{matter_id}/hearing-coach",
        headers=_auth(token),
    )
    assert status_response.status_code == 200, status_response.text
    events = _audit_events(str(boot["company"]["id"]))
    assert all(event.action != "hearing_coach.generated" for event in events)


def test_hearing_coach_requires_typed_mock_hearing_responses(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s13-empty-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S13-EMPTY")
    _seed_affidavit_question(matter_id)
    created = client.post(
        f"/api/matters/{matter_id}/mock-hearings",
        headers=_auth(token),
        json={},
    )
    assert created.status_code == 200, created.text

    blocked = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{created.json()['id']}/coach",
        headers=_auth(token),
        json={"acknowledged": True},
    )

    assert blocked.status_code == 409, blocked.text
    assert "typed mock-hearing responses" in blocked.text


def test_hearing_coach_routes_enforce_cross_tenant_restricted_team_and_ethical_wall(
    client: TestClient,
) -> None:
    boot_a = _bootstrap(client, f"li-s13-acl-a-{uuid4().hex[:6]}")
    owner_token = str(boot_a["access_token"])
    company_slug = str(boot_a["company"]["slug"])
    matter_id = _create_matter(client, owner_token, "LI-S13-ACL")
    session_id, _ = _create_session_with_response(
        client,
        token=owner_token,
        matter_id=matter_id,
    )

    boot_b = _bootstrap(client, f"li-s13-acl-b-{uuid4().hex[:6]}")
    token_b = str(boot_b["access_token"])
    hidden_get = client.get(
        f"/api/matters/{matter_id}/hearing-coach",
        headers=_auth(token_b),
    )
    hidden_post = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/coach",
        headers=_auth(token_b),
        json={"acknowledged": True},
    )
    assert hidden_get.status_code == 404, hidden_get.text
    assert hidden_post.status_code == 404, hidden_post.text

    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="hearing-coach-member@example.in",
    )
    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    denied_get = client.get(
        f"/api/matters/{matter_id}/hearing-coach",
        headers=_auth(member_token),
    )
    denied_post = client.post(
        f"/api/matters/{matter_id}/mock-hearings/{session_id}/coach",
        headers=_auth(member_token),
        json={"acknowledged": True},
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
        f"/api/matters/{matter_id}/hearing-coach",
        headers=_auth(member_token),
    )
    assert walled.status_code == 404, walled.text

    matter_team = _create_matter(client, owner_token, "LI-S13-TEAM")
    team_session_id, _ = _create_session_with_response(
        client,
        token=owner_token,
        matter_id=matter_team,
    )
    _, blocked_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="hearing-coach-team@example.in",
    )
    factory = get_session_factory()
    with factory() as session:
        team = Team(
            id=str(uuid4()),
            company_id=str(boot_a["company"]["id"]),
            name="Hearing Coach Team",
            slug=f"hearing-coach-{uuid4().hex[:6]}",
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
    team_blocked = client.post(
        f"/api/matters/{matter_team}/mock-hearings/{team_session_id}/coach",
        headers=_auth(blocked_token),
        json={"acknowledged": True},
    )
    assert team_blocked.status_code == 404, team_blocked.text
