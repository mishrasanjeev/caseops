from __future__ import annotations

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
            "title": f"Affidavit Intelligence {code}",
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


def _seed_attachment(
    matter_id: str,
    *,
    text: str | None,
    document_type: str | None = "chief_affidavit",
    original_filename: str = "chief-affidavit.txt",
) -> str:
    factory = get_session_factory()
    attachment_id = str(uuid4())
    with factory() as session:
        attachment = MatterAttachment(
            id=attachment_id,
            matter_id=matter_id,
            original_filename=original_filename,
            storage_key=f"test/affidavits/{uuid4().hex}.txt",
            content_type="text/plain",
            size_bytes=len(text or ""),
            sha256_hex=(uuid4().hex + uuid4().hex)[:64],
            processing_status=DocumentProcessingStatus.INDEXED,
            extracted_char_count=len(text or ""),
            extracted_text=text,
            document_type=document_type,
            lifecycle_stage="pleadings" if document_type else None,
        )
        session.add(attachment)
        if text:
            session.add(
                MatterAttachmentChunk(
                    attachment_id=attachment_id,
                    chunk_index=0,
                    content=text,
                    token_count=len(text.split()),
                )
            )
        session.commit()
    return attachment_id


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
            "full_name": "Affidavit Member",
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


def test_affidavit_analysis_extracts_source_anchored_statements_and_questions(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s2-main-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S2-MAIN")
    attachment_id = _seed_attachment(
        matter_id,
        text=(
            "Page 2. I state that on 12.04.2026 the respondent received goods "
            "worth Rs. 5,00,000. The invoice is annexed as Annexure A. "
            "The respondent defaulted on payment and no receipt is identified."
        ),
    )

    response = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["disclaimer"].startswith("Affidavit intelligence is source-backed")
    run = payload["latest_run"]
    assert run["status"] == "completed"
    assert run["attachment_id"] == attachment_id
    statement_types = {statement["statement_type"] for statement in run["statements"]}
    assert {
        "timeline_point",
        "monetary_figure",
        "exhibit_reference",
        "evidence_gap",
    }.issubset(statement_types)
    categories = {question["category"] for question in run["questions"]}
    assert {
        "timeline_inconsistency",
        "financial_scrutiny",
        "document_support",
    }.issubset(categories)
    assert all(question["source_quote"] for question in run["questions"])
    assert all(question["source_chunk_id"] for question in run["questions"])
    assert all(question["review_required"] for question in run["questions"])
    assert "legal advice" in payload["disclaimer"].lower()

    actions = _audit_actions(str(boot["company"]["id"]))
    assert "affidavit_intelligence.analyzed" in actions


def test_summary_only_attachment_without_raw_chunks_returns_insufficient_source_text(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s2-summary-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S2-SUMMARY")
    attachment_id = _seed_attachment(
        matter_id,
        text=None,
        original_filename="generated-summary-only.txt",
    )

    response = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    run = response.json()["latest_run"]
    assert run["status"] == "insufficient_source_text"
    assert run["missing_data"] == ["raw_attachment_text_chunks"]
    assert run["statements"] == []
    assert run["questions"] == []
    factory = get_session_factory()
    with factory() as session:
        assert session.scalar(select(AffidavitStatement)) is None
        assert session.scalar(select(AffidavitQuestion)) is None


def test_affidavit_analysis_does_not_invent_questions_without_source_chunk(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s2-source-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S2-SOURCE")
    source_text = (
        "I state that respondent paid Rs. 10,000 in cash and received goods "
        "on 01.05.2026 under the disputed transaction."
    )
    attachment_id = _seed_attachment(matter_id, text=source_text)

    response = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.text
    questions = response.json()["latest_run"]["questions"]
    assert questions
    assert all(question["source_quote"] in source_text for question in questions)
    low_confidence = [
        question for question in questions if question["confidence_label"] == "low"
    ]
    assert low_confidence
    assert all(question["review_status"] == "review_required" for question in low_confidence)


def test_affidavit_analysis_rerun_versions_cleanly_without_duplicate_latest_results(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s2-rerun-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S2-RERUN")
    attachment_id = _seed_attachment(
        matter_id,
        text=(
            "I state that on 04.05.2026 the respondent received Rs. 25,000. "
            "The respondent defaulted on repayment despite repeated demands."
        ),
    )

    responses = []
    for _ in range(2):
        response = client.post(
            f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
            headers=_auth(token),
        )
        assert response.status_code == 200, response.text
        responses.append(response.json())

    first_latest = responses[0]["latest_run"]
    second_latest = responses[1]["latest_run"]
    assert second_latest["id"] != first_latest["id"]
    assert len(second_latest["statements"]) == len(first_latest["statements"])
    assert len(second_latest["questions"]) == len(first_latest["questions"])
    factory = get_session_factory()
    with factory() as session:
        runs = list(
            session.scalars(
                select(AffidavitIntelligenceRun).where(
                    AffidavitIntelligenceRun.matter_id == matter_id
                )
            )
        )
        assert len(runs) == 2


def test_cross_tenant_attachment_cannot_be_analyzed(client: TestClient) -> None:
    boot_a = _bootstrap(client, f"li-s2-ten-a-{uuid4().hex[:6]}")
    token_a = str(boot_a["access_token"])
    matter_a = _create_matter(client, token_a, "LI-S2-TEN-A")
    attachment_a = _seed_attachment(
        matter_a,
        text="I state that on 01.05.2026 Rs. 10,000 was paid under the contract.",
    )

    boot_b = _bootstrap(client, f"li-s2-ten-b-{uuid4().hex[:6]}")
    token_b = str(boot_b["access_token"])
    matter_b = _create_matter(client, token_b, "LI-S2-TEN-B")

    hidden_matter = client.post(
        f"/api/matters/{matter_a}/attachments/{attachment_a}/affidavit-intelligence/analyze",
        headers=_auth(token_b),
    )
    assert hidden_matter.status_code == 404, hidden_matter.text
    hidden_attachment = client.post(
        f"/api/matters/{matter_b}/attachments/{attachment_a}/affidavit-intelligence/analyze",
        headers=_auth(token_b),
    )
    assert hidden_attachment.status_code == 404, hidden_attachment.text


def test_affidavit_intelligence_routes_enforce_restricted_and_ethical_wall_access(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s2-acl-{uuid4().hex[:6]}")
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    matter_id = _create_matter(client, owner_token, "LI-S2-ACL")
    attachment_id = _seed_attachment(
        matter_id,
        text="I state that respondent paid Rs. 10,000 on 01.05.2026.",
    )
    member_id, member_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="member-li-s2@example.in",
    )

    restricted = client.post(
        f"/api/matters/{matter_id}/access/restricted",
        headers=_auth(owner_token),
        json={"restricted": True},
    )
    assert restricted.status_code == 200, restricted.text
    hidden_get = client.get(
        f"/api/matters/{matter_id}/affidavit-intelligence",
        headers=_auth(member_token),
    )
    assert hidden_get.status_code == 404, hidden_get.text
    hidden_post = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(member_token),
    )
    assert hidden_post.status_code == 404, hidden_post.text

    grant = client.post(
        f"/api/matters/{matter_id}/access/grants",
        headers=_auth(owner_token),
        json={"membership_id": member_id, "reason": "Affidavit prep"},
    )
    assert grant.status_code == 200, grant.text
    visible_get = client.get(
        f"/api/matters/{matter_id}/affidavit-intelligence",
        headers=_auth(member_token),
    )
    assert visible_get.status_code == 200, visible_get.text

    wall = client.post(
        f"/api/matters/{matter_id}/access/walls",
        headers=_auth(owner_token),
        json={"excluded_membership_id": member_id, "reason": "Conflict"},
    )
    assert wall.status_code == 200, wall.text
    walled_get = client.get(
        f"/api/matters/{matter_id}/affidavit-intelligence",
        headers=_auth(member_token),
    )
    assert walled_get.status_code == 404, walled_get.text
    walled_post = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(member_token),
    )
    assert walled_post.status_code == 404, walled_post.text


def test_affidavit_intelligence_routes_enforce_team_scoping(client: TestClient) -> None:
    boot = _bootstrap(client, f"li-s2-team-{uuid4().hex[:6]}")
    owner_token = str(boot["access_token"])
    company_slug = str(boot["company"]["slug"])
    matter_id = _create_matter(client, owner_token, "LI-S2-TEAM")
    attachment_id = _seed_attachment(
        matter_id,
        text="I state that respondent paid Rs. 10,000 on 01.05.2026.",
    )
    _, blocked_token = _invite_member(
        client,
        owner_token=owner_token,
        company_slug=company_slug,
        email="blocked-li-s2@example.in",
    )

    factory = get_session_factory()
    with factory() as session:
        team = Team(
            id=str(uuid4()),
            company_id=str(boot["company"]["id"]),
            name="Affidavit Team",
            slug=f"affidavit-{uuid4().hex[:6]}",
        )
        session.add(team)
        session.flush()
        matter = session.get(Matter, matter_id)
        assert matter is not None
        matter.team_id = team.id
        company = session.get(Company, str(boot["company"]["id"]))
        assert company is not None
        company.team_scoping_enabled = True
        session.add_all([matter, company])
        session.commit()

    hidden_get = client.get(
        f"/api/matters/{matter_id}/affidavit-intelligence",
        headers=_auth(blocked_token),
    )
    assert hidden_get.status_code == 404, hidden_get.text
    hidden_post = client.post(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze",
        headers=_auth(blocked_token),
    )
    assert hidden_post.status_code == 404, hidden_post.text


def test_document_metadata_accepts_chief_and_counter_affidavit_types(
    client: TestClient,
) -> None:
    boot = _bootstrap(client, f"li-s2-types-{uuid4().hex[:6]}")
    token = str(boot["access_token"])
    matter_id = _create_matter(client, token, "LI-S2-TYPES")
    attachment_id = _seed_attachment(
        matter_id,
        text="I state that respondent paid Rs. 10,000 on 01.05.2026.",
        document_type="affidavit",
    )

    chief = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(token),
        json={"document_type": "chief_affidavit"},
    )
    assert chief.status_code == 200, chief.text
    assert chief.json()["document_type"] == "chief_affidavit"
    assert chief.json()["lifecycle_stage"] == "pleadings"

    counter = client.patch(
        f"/api/matters/{matter_id}/attachments/{attachment_id}/metadata",
        headers=_auth(token),
        json={"document_type": "counter_affidavit"},
    )
    assert counter.status_code == 200, counter.text
    assert counter.json()["document_type"] == "counter_affidavit"
    assert counter.json()["lifecycle_stage"] == "pleadings"
